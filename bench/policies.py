"""Curation policies: three survival arms plus five baselines.

Every policy answers the same tasks through the same QueryProtocol and
the same environment. They differ only in what they evict at the end of
each cycle:

- survival / survival_writes: the real SurvivalLoop (energy ledger).
- survival_embedding: the same loop over an EmbeddingRetriever store
  (hashing embedder), testing the mechanism off the lexical-match path.
- evict_on_negative: the if-statement alternative. Evict any entry
  whose decisions have produced K negative outcomes (K=1, instant, in
  the headline suite; K=2,3 in the noisy suite). If the energy ledger
  cannot beat this one-liner on some metric, the report says so.
- evict_consecutive: strikes that a success wipes clean, forgiveness
  as an if-statement (noisy suite).
- quarantine: evict on blame but re-encode a fresh copy after a
  cooldown, the recovery path real deployments have (noisy suite).
- keep_everything: nothing, ever. The no-curation lower bound.
- ttl: age-based eviction, blind to usage and outcomes.
- recency: idle-based eviction, blind to outcomes.
- random_matched: evicts the same NUMBER of entries per cycle that the
  survival arm evicted on the same seed, chosen uniformly at random.
  The sharpest control: same pruning rate, no outcome direction.
- policy_bandit: the literature control for the AEL objection. No
  energy: a successive-elimination bandit statistic over each entry's
  reported decision outcomes, culling when even the optimistic
  confidence bound says the entry wins less than half its decisions.

Baselines share one driver and differ only in their victim selector;
they track entry usage (recency needs it) but never touch energy.
"""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from darwin_memo import (
    Environment,
    MemoryEntry,
    MemoryStore,
    QueryProtocol,
    SurvivalConfig,
    SurvivalLoop,
)

OnCycle = Callable[[int, "CycleRecord"], None]
# A victim selector sees (store, cycle, blame counts, praise counts) and
# names who dies. Blame/praise count how many negative/positive-outcome
# tasks each entry decided THIS cycle; selectors needing lifetime totals
# accumulate in their own closures.
VictimSelector = Callable[
    [MemoryStore, int, "Counter[str]", "Counter[str]"], list[MemoryEntry]
]


@dataclass
class CycleRecord:
    cycle: int
    population: int
    deaths: int
    resource_delta: float


@dataclass
class PolicyResult:
    records: list[CycleRecord] = field(default_factory=list)

    @property
    def death_schedule(self) -> list[int]:
        return [r.deaths for r in self.records]


def _baseline_task_loop(
    store: MemoryStore, env: Environment, cycle: int
) -> tuple[float, Counter[str], Counter[str]]:
    """Answer and act exactly like the survival loop, minus the ledger.

    Returns the cycle's resource delta and per-entry counts of
    negative-outcome decisions (the blame the evict_on_negative family
    acts on) and positive-outcome decisions (the praise the
    consecutive-strikes variant forgives on). Both read the REPORTED
    outcome, exactly like the heuristics they feed would in production.
    """
    protocol = QueryProtocol(store)
    delta = 0.0
    blamed: Counter[str] = Counter()
    praised: Counter[str] = Counter()
    for task in env.tasks(cycle):
        answer = protocol.answer(task.prompt)
        outcome = env.verify(task, answer.text)
        delta += outcome.delta
        if answer.deciding_entry:
            if outcome.delta < 0:
                blamed[answer.deciding_entry] += 1
            elif outcome.delta > 0:
                praised[answer.deciding_entry] += 1
        consulted = list(answer.supporting_entries)
        if answer.deciding_entry:
            consulted.append(answer.deciding_entry)
        for entry_id in consulted:
            entry = store.get(entry_id)
            if entry is not None:
                entry.uses += 1
                entry.last_used_cycle = cycle
    return delta, blamed, praised


def _run_baseline(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    select_victims: VictimSelector,
    on_cycle: OnCycle | None = None,
) -> PolicyResult:
    """One driver for every baseline; policies are victim selectors."""
    result = PolicyResult()
    for cycle in range(cycles):
        delta, blamed, praised = _baseline_task_loop(store, env, cycle)
        victims = select_victims(store, cycle, blamed, praised)
        for entry in victims:
            store.bury(entry.id)
        record = CycleRecord(cycle, len(store), len(victims), delta)
        result.records.append(record)
        if on_cycle:
            on_cycle(cycle, record)
    return result


def run_survival(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    seed: int,
    config: SurvivalConfig,
    on_cycle: OnCycle | None = None,
    protocol: QueryProtocol | None = None,
) -> PolicyResult:
    loop = SurvivalLoop(store, env, protocol=protocol, config=config)
    result = PolicyResult()
    for cycle in range(cycles):
        stats, _ = loop.run_cycle(cycle)
        record = CycleRecord(
            cycle=cycle,
            population=stats.population,
            deaths=stats.deaths,
            resource_delta=stats.resource_delta,
        )
        result.records.append(record)
        if on_cycle:
            on_cycle(cycle, record)
    return result


def run_keep_everything(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    on_cycle: OnCycle | None = None,
) -> PolicyResult:
    return _run_baseline(store, env, cycles, lambda s, c, b, p: [], on_cycle)


def run_ttl(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    ttl: int = 10,
    on_cycle: OnCycle | None = None,
) -> PolicyResult:
    def expired(
        s: MemoryStore, cycle: int, blamed: Counter[str], praised: Counter[str]
    ) -> list[MemoryEntry]:
        return [e for e in s.alive() if cycle - e.born_cycle >= ttl]

    return _run_baseline(store, env, cycles, expired, on_cycle)


def run_recency(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    window: int = 10,
    on_cycle: OnCycle | None = None,
) -> PolicyResult:
    def idle(
        s: MemoryStore, cycle: int, blamed: Counter[str], praised: Counter[str]
    ) -> list[MemoryEntry]:
        return [
            e
            for e in s.alive()
            if cycle - max(e.last_used_cycle, e.born_cycle) >= window
        ]

    return _run_baseline(store, env, cycles, idle, on_cycle)


def run_random_matched(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    seed: int,
    death_schedule: list[int],
    on_cycle: OnCycle | None = None,
) -> PolicyResult:
    """Evict survival's per-cycle death counts, but pick victims at random."""
    rng = random.Random(seed * 1000 + 17)

    def random_victims(
        s: MemoryStore, cycle: int, blamed: Counter[str], praised: Counter[str]
    ) -> list[MemoryEntry]:
        budget = death_schedule[cycle] if cycle < len(death_schedule) else 0
        alive = s.alive()
        return rng.sample(alive, k=min(budget, len(alive)))

    return _run_baseline(store, env, cycles, random_victims, on_cycle)


def run_evict_on_negative(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    on_cycle: OnCycle | None = None,
    strikes: int = 1,
) -> PolicyResult:
    """The if-statement baseline: evict any entry whose decisions have
    produced ``strikes`` negative outcomes, lifetime. At the default of
    one strike this is the instant version: no energy, no forgiveness,
    no starvation of the useless. Higher strike counts are the obvious
    noise-tolerance upgrade a practitioner would write, and the noisy
    suite runs them so the ledger is compared against the heuristic's
    best self, not a strawman. Strikes never reset or decay: that is
    the structural difference from the energy ledger, where earning
    replenishes the buffer. If the full ledger cannot beat this on some
    metric, the benchmark says so."""
    lifetime: Counter[str] = Counter()

    def the_blamed(
        s: MemoryStore, cycle: int, blamed: Counter[str], praised: Counter[str]
    ) -> list[MemoryEntry]:
        lifetime.update(blamed)
        return [e for e in s.alive() if lifetime[e.id] >= strikes]

    return _run_baseline(store, env, cycles, the_blamed, on_cycle)


def run_evict_consecutive(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    on_cycle: OnCycle | None = None,
    strikes: int = 2,
) -> PolicyResult:
    """Strikes that a success wipes clean: the strongest cheap heuristic.

    An entry's strike count resets to zero in any cycle where it also
    decided a positive-outcome task, then accumulates that cycle's
    blame; ``strikes`` total gets it evicted. This is forgiveness as an
    if-statement, and the closest a counter gets to the ledger's
    earn-back without inventing energy. Granularity is the cycle, so a
    cycle containing both a success and a failure forgives first and
    then counts the failure.
    """
    count: Counter[str] = Counter()

    def strike_out(
        s: MemoryStore, cycle: int, blamed: Counter[str], praised: Counter[str]
    ) -> list[MemoryEntry]:
        for entry_id in praised:
            count[entry_id] = 0
        count.update(blamed)
        return [e for e in s.alive() if count[e.id] >= strikes]

    return _run_baseline(store, env, cycles, strike_out, on_cycle)


def run_quarantine(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    suspend: int = 3,
    on_cycle: OnCycle | None = None,
) -> PolicyResult:
    """Evict on blame, but the knowledge comes back after a cooldown.

    Eviction is permanent in every other baseline, while in deployments
    the evicted lesson's source often still exists: re-encoding it is
    cheap. This arm models that recovery path: a blamed entry is buried
    immediately, and ``suspend`` cycles later a fresh copy (same QA
    text, spawn-fresh id and energy) re-enters the population. The
    ``deaths`` column counts suspensions; revivals are silent, matching
    how the survival loop's births column ignores resurrection too.
    """
    pending: dict[int, list[MemoryEntry]] = {}
    result = PolicyResult()
    for cycle in range(cycles):
        for ancestor in pending.pop(cycle, []):
            store.add(
                MemoryEntry(
                    question=ancestor.question,
                    answer=ancestor.answer,
                    kind=ancestor.kind,
                    sources=list(ancestor.sources),
                    born_cycle=cycle,
                )
            )
        delta, blamed, _praised = _baseline_task_loop(store, env, cycle)
        victims = [e for e in store.alive() if blamed[e.id] > 0]
        for entry in victims:
            store.bury(entry.id)
            pending.setdefault(cycle + suspend, []).append(entry)
        record = CycleRecord(cycle, len(store), len(victims), delta)
        result.records.append(record)
        if on_cycle:
            on_cycle(cycle, record)
    return result


def run_policy_bandit(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    on_cycle: OnCycle | None = None,
    threshold: float = 0.5,
) -> PolicyResult:
    """The bandit control arm: confidence bounds instead of energy.

    The objection this arm exists to test (the AEL line, arXiv
    2604.21725): conserved-resource settlement is unnecessary, because
    a simple bandit statistic over retrieval outcomes curates just as
    well under noise. So here it is, run rather than argued. Each
    entry is a bandit arm. Every measured task it decides is a pull
    paying reward 1 (positive reported delta) or 0 (negative); an
    entry is culled when even its optimistic estimate
    ``mean + sqrt(ln(T) / (2n))`` drops below ``threshold``
    (successive elimination with a Hoeffding radius, T = total pulls
    recorded so far across all entries). Stdlib, deterministic, no
    RNG anywhere.

    Three structural differences from the ledger, all on purpose:
    confidence radii forgive (one lie cannot execute a many-pull
    entry, the bandit's version of the energy buffer); nothing
    starves (an entry that never decides is never pulled and so never
    culled, dead weight is immortal); and the reward reads only the
    reported SIGN, so a wrong delete costing 3x what a right one
    earns is invisible, putting break-even at win rate 0.5 even where
    the value break-even is far higher. The two-pull guard exists
    because ln(1) = 0 collapses the radius to zero and would make the
    first failure an instant execution, which is evict_on_negative
    k=1, not a bandit.
    """
    pulls: Counter[str] = Counter()
    wins: Counter[str] = Counter()

    def confidently_bad(
        s: MemoryStore, cycle: int, blamed: Counter[str], praised: Counter[str]
    ) -> list[MemoryEntry]:
        pulls.update(blamed)
        pulls.update(praised)
        wins.update(praised)
        total = sum(pulls.values())
        if total < 2:
            return []
        log_total = math.log(total)
        return [
            e
            for e in s.alive()
            if pulls[e.id]
            and wins[e.id] / pulls[e.id] + math.sqrt(log_total / (2 * pulls[e.id]))
            < threshold
        ]

    return _run_baseline(store, env, cycles, confidently_bad, on_cycle)


ARMS = (
    "survival",
    "survival_writes",
    "survival_embedding",
    "evict_on_negative",
    "keep_everything",
    "ttl",
    "recency",
    "random_matched",
)

# The noisy suite's arm set: the ledger against the heuristic family's
# best selves, plus the no-curation canary (its TRUE deltas must be
# invariant to measurement noise, which validates the harness).
NOISY_ARMS = (
    "survival",
    "evict_on_negative",  # strikes=1 unless overridden
    "evict_consecutive",
    "quarantine",
    "keep_everything",
)
