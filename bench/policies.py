"""Curation policies: the survival arms plus four baselines.

Every policy answers the same tasks through the same QueryProtocol and
the same environment. They differ only in what they evict at the end of
each cycle:

- survival / survival_writes: the real SurvivalLoop (energy ledger).
- keep_everything: nothing, ever. The no-curation lower bound.
- ttl: age-based eviction, blind to usage and outcomes.
- recency: idle-based eviction, blind to outcomes.
- random_matched: evicts the same NUMBER of entries per cycle that the
  survival arm evicted on the same seed, chosen uniformly at random.
  The sharpest control: same pruning rate, no outcome direction.

Baselines track entry usage (recency needs it) but never touch energy.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field

from darwin_memo import (
    Environment,
    MemoryStore,
    QueryProtocol,
    SurvivalConfig,
    SurvivalLoop,
)

OnCycle = Callable[[int, "CycleRecord"], None]


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


def _baseline_task_loop(store: MemoryStore, env: Environment, cycle: int) -> float:
    """Answer and act exactly like the survival loop, minus the ledger."""
    protocol = QueryProtocol(store)
    delta = 0.0
    for task in env.tasks(cycle):
        answer = protocol.answer(task.prompt)
        outcome = env.verify(task, answer.text)
        delta += outcome.delta
        consulted = list(answer.supporting_entries)
        if answer.deciding_entry:
            consulted.append(answer.deciding_entry)
        for entry_id in consulted:
            entry = store.get(entry_id)
            if entry is not None:
                entry.uses += 1
                entry.last_used_cycle = cycle
    return delta


def run_survival(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    seed: int,
    config: SurvivalConfig,
    on_cycle: OnCycle | None = None,
) -> PolicyResult:
    loop = SurvivalLoop(store, env, config=config)
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
    seed: int,
    on_cycle: OnCycle | None = None,
) -> PolicyResult:
    result = PolicyResult()
    for cycle in range(cycles):
        delta = _baseline_task_loop(store, env, cycle)
        record = CycleRecord(cycle, len(store), 0, delta)
        result.records.append(record)
        if on_cycle:
            on_cycle(cycle, record)
    return result


def run_ttl(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    seed: int,
    ttl: int = 10,
    on_cycle: OnCycle | None = None,
) -> PolicyResult:
    result = PolicyResult()
    for cycle in range(cycles):
        delta = _baseline_task_loop(store, env, cycle)
        expired = [e for e in store.alive() if cycle - e.born_cycle >= ttl]
        for entry in expired:
            store.bury(entry.id)
        record = CycleRecord(cycle, len(store), len(expired), delta)
        result.records.append(record)
        if on_cycle:
            on_cycle(cycle, record)
    return result


def run_recency(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    seed: int,
    window: int = 10,
    on_cycle: OnCycle | None = None,
) -> PolicyResult:
    result = PolicyResult()
    for cycle in range(cycles):
        delta = _baseline_task_loop(store, env, cycle)
        idle = [
            e
            for e in store.alive()
            if cycle - max(e.last_used_cycle, e.born_cycle) >= window
        ]
        for entry in idle:
            store.bury(entry.id)
        record = CycleRecord(cycle, len(store), len(idle), delta)
        result.records.append(record)
        if on_cycle:
            on_cycle(cycle, record)
    return result


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
    result = PolicyResult()
    for cycle in range(cycles):
        delta = _baseline_task_loop(store, env, cycle)
        budget = death_schedule[cycle] if cycle < len(death_schedule) else 0
        alive = store.alive()
        victims = rng.sample(alive, k=min(budget, len(alive)))
        for entry in victims:
            store.bury(entry.id)
        record = CycleRecord(cycle, len(store), len(victims), delta)
        result.records.append(record)
        if on_cycle:
            on_cycle(cycle, record)
    return result


ARMS = (
    "survival",
    "survival_writes",
    "keep_everything",
    "ttl",
    "recency",
    "random_matched",
)
