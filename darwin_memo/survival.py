"""The survival loop: environment-mediated selection over memory.

This is where the two papers meet. MeMo supplies what is being selected,
a population of reflection-QA memory entries serving a frozen LLM. The
survival paper supplies how selection works:

1. Memory proposes: the query protocol answers each task from entries.
2. The environment reads the answer, acts, and measures a real
   resource delta.
3. Credit flows only to the entries that produced the answer. Positive
   deltas add energy, negative deltas drain it.
4. Every entry pays upkeep every cycle. Energy at zero means death.
5. Periodically, Negative-Space consolidation prunes and merges.

There is no reward model and no judge anywhere. An entry that is wrong,
stale, or useless has no way to stay alive, and an entry can only fake
fitness by actually producing outcomes that persist, at which point it
is not faking. That is the survival paper's argument for why proxy
optimization is evolutionarily unstable here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .consolidate import DEFAULT_MERGE_THRESHOLD, consolidate
from .diagnose import selection_findings
from .environments import Environment
from .protocol import QueryProtocol
from .store import MemoryStore
from .types import CycleStats, EntryKind, MemoryEntry, Trajectory


@dataclass
class SurvivalConfig:
    cycles: int = 30
    credit_gain: float = 0.6
    supporting_share: float = 0.25
    consolidate_every: int = 5
    merge_threshold: float = DEFAULT_MERGE_THRESHOLD
    write_experience: bool = True
    experience_min_delta: float = 0.0
    experience_dedup_threshold: float = 0.8
    # None means "use the environment's resource_scale". The Ledger,
    # which has no environment, sets this directly so the whole credit
    # formula lives in one config object.
    resource_scale: float | None = None
    # Admission gating (docs/threat-model.md): entries written through
    # Ledger.add start with this many juvenile settlements ahead of
    # them. 0 disables gating and keeps existing behavior byte for
    # byte; 3 is the documented default when you turn it on. While
    # juvenile, a deciding entry earns and loses at supporting_share,
    # and one negative deciding outcome denies admission outright.
    admission_window: int = 0
    # EXPERIMENTAL, and measured rather than asserted: charge upkeep only
    # on cycles that carried a measured outcome, so a store is not billed
    # for time in which nothing was measurable. Off by default; every
    # published benchmark ran flat upkeep and stays byte-identical.
    #
    # Read the trade before turning this on. MIN_UPKEEP_SCALE exists so a
    # caller may slow an entry's burn rate but never stop it, because
    # upkeep reaching zero is a pin nobody granted (see
    # MemoryStore.charge_upkeep). This stops it for the WHOLE population
    # at once, which changes no relative ordering between entries but does
    # hand an adversary who can suppress measurements control of the
    # clock. bench's `withholding` suite is what decides whether that is
    # ever worth it; until it says so, treat this as unproven.
    upkeep_requires_settlement: bool = False
    # How much provenance agreement consolidation requires on top of
    # similarity; see darwin_memo.consolidate.SOURCE_POLICIES. "off" is
    # the published behaviour and every committed benchmark ran it, so
    # it stays the default and those files stay byte-identical.
    # limitations.tex names this as the obvious fix for consolidation
    # laundering; docs/benchmarks.md records what it is actually worth.
    merge_source_policy: str = "off"


def assign_credit(
    store: MemoryStore,
    deciding_entry: str | None,
    supporting_entries: list[str],
    delta: float,
    resource_scale: float,
    config: SurvivalConfig,
    cycle: int,
) -> list[tuple[str, float]]:
    """The one credit rule, shared by SurvivalLoop, Ledger, and examples.

    tanh keeps a single huge outcome from making an entry immortal, and
    keeps a single disaster from instantly executing an entry that was
    right ninety-nine times. When a deciding entry is named it takes
    full credit and supporters take a share; when no single entry
    decided, credit spreads evenly. Returns the (entry_id, credit)
    pairs that were applied, so callers can record them.

    Two trust-lifecycle exceptions. A juvenile decider (an entry still
    inside its admission window, see ``SurvivalConfig.admission_window``)
    takes the supporting share instead of full credit, so a young
    lesson cannot bank energy faster than incumbents while it is still
    unproven. And on the even-spread path (no deciding entry named), an
    entry that may not decide (a probationary import) takes its even
    share AT the supporting share: an import in a two-citation
    settlement must not earn double the ``credit_gain *
    supporting_share`` ride-along cap the threat model documents.
    Neither exception touches pre-lifecycle arithmetic, because such
    entries did not exist before the lifecycle did. The counters
    themselves advance in :func:`advance_lifecycle`, called by
    Ledger.settle and the loop's credit path.
    """
    normalized = math.tanh(delta / resource_scale)
    credit = config.credit_gain * normalized
    if credit == 0.0:
        return []
    applied: list[tuple[str, float]] = []
    if deciding_entry:
        decider = store.get(deciding_entry)
        weight = (
            config.supporting_share
            if decider is not None and decider.juvenile > 0
            else 1.0
        )
        applied.append((deciding_entry, credit * weight))
        applied.extend(
            (entry_id, credit * config.supporting_share)
            for entry_id in supporting_entries
        )
    elif supporting_entries:
        share = credit / len(supporting_entries)
        for entry_id in supporting_entries:
            entry = store.get(entry_id)
            if entry is not None and not entry.may_decide:
                applied.append((entry_id, share * config.supporting_share))
            else:
                applied.append((entry_id, share))
    for entry_id, amount in applied:
        store.credit(entry_id, amount, cycle)
    return applied


def advance_lifecycle(
    store: MemoryStore,
    applied: list[tuple[str, float]],
    delta: float,
    deciding_entry: str | None,
) -> list[tuple[str, str]]:
    """Advance probation and juvenile counters after one credited outcome.

    The one lifecycle rule, shared by Ledger.settle and SurvivalLoop's
    credit path so an import graduates (and a juvenile is admitted or
    denied) no matter which consumer measured the outcome.

    Probation (imported entries): each net-positive credit pays one
    installment; at zero the entry graduates and may decide. Negative
    credits drain energy as usual but never count toward graduation.

    Juvenile window (admission-gated local entries): every credited
    settlement advances the window, but a negative measured delta while
    the entry DECIDED denies admission outright: the balance zeroes and
    the caller's burial path executes it. Riding along on someone
    else's bad decision drains energy without denying admission.
    Zero-delta outcomes apply no credit and reach neither counter.

    Returns ``(entry_id, event)`` pairs, event one of ``"graduated"``,
    ``"admitted"``, ``"admission_denied"``, so callers can narrate them.
    """
    events: list[tuple[str, str]] = []
    for entry_id, credit in applied:
        entry = store.get(entry_id)
        if entry is None:
            continue
        if entry.probation > 0 and credit > 0:
            entry.probation -= 1
            if entry.probation == 0:
                events.append((entry_id, "graduated"))
        if entry.juvenile > 0:
            if delta < 0 and entry_id == deciding_entry:
                entry.energy = 0.0
                entry.juvenile = 0
                events.append((entry_id, "admission_denied"))
                continue
            entry.juvenile -= 1
            if entry.juvenile == 0:
                events.append((entry_id, "admitted"))
    return events


def is_silent(answer_text: str, deciding: str | None, supporting: list[str]) -> bool:
    """Did memory contribute nothing to this answer?

    Empty text is silence in local mode. In LLM mode the model always
    produces prose, so silence means no provenance: nothing retrieved,
    or the model explicitly cited no sources.
    """
    return not answer_text or (deciding is None and not supporting)


def death_cause(
    entry: MemoryEntry, poisoned_ids: set[str], merged_away: set[str]
) -> str:
    """Classify a graveyard entry: merged, executed, or starved.

    Executed means the entry decided real actions (uses > 0) that the
    environment punished; a poisoned entry that was never consulted
    simply starved like any other unused knowledge.
    """
    if entry.id in merged_away:
        return "merged"
    if entry.id in poisoned_ids and entry.uses > 0:
        return "executed"
    return "starved"


@dataclass
class SurvivalReport:
    """Cycle stats plus the full trajectory log.

    Trajectories are observability for inspection and demos; nothing in
    the loop reads them back.
    """

    stats: list[CycleStats] = field(default_factory=list)
    trajectories: list[Trajectory] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"{'cycle':>5} {'pop':>4} {'births':>6} {'deaths':>6} {'merges':>6} "
            f"{'energy':>8} {'resource Δ':>12} {'silent':>8}"
        ]
        for s in self.stats:
            silence = f"{s.silent}/{s.tasks}" if s.tasks else "-"
            lines.append(
                f"{s.cycle:>5} {s.population:>4} {s.births:>6} {s.deaths:>6} "
                f"{s.merges:>6} {s.total_energy:>8.2f} {s.resource_delta:>12.0f} "
                f"{silence:>8}"
            )
        return "\n".join(lines) + self.health_warning()

    def health_warning(self) -> str:
        """A plain-language diagnosis when the run looks degenerate.

        The failure modes a new environment hits are silent: memory
        never answers (phrasing mismatch or action vocabulary not read),
        or answers never earn (verify never pays out). Both end the same
        way, the whole population starving at spawn_energy / upkeep
        cycles, so the report says so instead of letting the table look
        like success. The rules live in :mod:`darwin_memo.diagnose` so
        the Ledger's ``doctor`` diagnoses identically.
        """
        total_tasks = sum(s.tasks for s in self.stats)
        if not total_tasks:
            return ""
        findings = selection_findings(
            decides=total_tasks,
            silent=sum(s.silent for s in self.stats),
            # Gross movement, not net: see selection_findings.
            nonzero_outcomes=sum(s.nonzero_outcomes for s in self.stats),
            settles=total_tasks,
        )
        if not findings:
            return ""
        return "\n\nWARNING: " + "\nWARNING: ".join(
            f"{f.summary}: {f.fix}" for f in findings
        )


class SurvivalLoop:
    """Runs environment-mediated selection over a memory store."""

    def __init__(
        self,
        store: MemoryStore,
        env: Environment,
        protocol: QueryProtocol | None = None,
        config: SurvivalConfig | None = None,
    ) -> None:
        self.store = store
        self.env = env
        self.config = config or SurvivalConfig()
        # Default protocol flags conflicting advice at the same floor
        # this loop consolidates at; see Ledger.__init__ for the why.
        self.protocol = protocol or QueryProtocol(
            store, conflict_threshold=self.config.merge_threshold
        )

    def run(self) -> SurvivalReport:
        report = SurvivalReport()
        for cycle in range(self.config.cycles):
            stats, trajectories = self.run_cycle(cycle)
            report.stats.append(stats)
            report.trajectories.extend(trajectories)
        return report

    def run_cycle(self, cycle: int) -> tuple[CycleStats, list[Trajectory]]:
        cfg = self.config
        births = 0
        resource_delta = 0.0
        tasks_seen = 0
        silent = 0
        trajectories: list[Trajectory] = []
        best: Trajectory | None = None

        nonzero_outcomes = 0
        for task in self.env.tasks(cycle):
            answer = self.protocol.answer(task.prompt)
            tasks_seen += 1
            if is_silent(answer.text, answer.deciding_entry, answer.supporting_entries):
                silent += 1
            outcome = self.env.verify(task, answer.text)
            resource_delta += outcome.delta
            if outcome.delta != 0:
                nonzero_outcomes += 1

            trajectory = Trajectory(
                cycle=cycle,
                task=task.prompt,
                answer=answer.text,
                deciding_entry=answer.deciding_entry,
                supporting_entries=answer.supporting_entries,
                outcome=outcome,
            )
            trajectories.append(trajectory)
            self._assign_credit(trajectory, cycle)

            if outcome.delta > cfg.experience_min_delta and (
                best is None or outcome.delta > best.outcome.delta
            ):
                best = trajectory

        if cfg.write_experience and best is not None:
            births += self._write_experience(best, cycle)

        # The population-level clock. `nonzero_outcomes` is this cycle's
        # own evidence count, so the decision reads no per-entry state and
        # every surviving entry is shifted by the same amount -- which is
        # what separates it from salience-style relief, where usage cannot
        # tell "used" from "useful" and the poison is the most-used entry.
        paced_quiet = cfg.upkeep_requires_settlement and nonzero_outcomes == 0
        dead = [] if paced_quiet else self.store.charge_upkeep()

        merges = 0
        if cfg.consolidate_every and (cycle + 1) % cfg.consolidate_every == 0:
            merges = consolidate(
                self.store,
                cycle,
                threshold=cfg.merge_threshold,
                source_policy=cfg.merge_source_policy,
            )

        stats = CycleStats(
            cycle=cycle,
            population=len(self.store),
            births=births,
            deaths=len(dead),
            merges=merges,
            total_energy=self.store.total_energy(),
            resource_delta=resource_delta,
            tasks=tasks_seen,
            silent=silent,
            nonzero_outcomes=nonzero_outcomes,
        )
        return stats, trajectories

    # ------------------------------------------------------------------

    def _assign_credit(self, trajectory: Trajectory, cycle: int) -> None:
        """Energy moves only along provenance, via the shared credit rule.

        The trust lifecycle advances here too: a probationary import
        that rides along on a verified win in the loop pays an
        installment exactly as it would on a Ledger settlement, and a
        juvenile entry is admitted or denied the same way (the denial
        zeroes its balance; this cycle's upkeep buries it).
        """
        scale = self.config.resource_scale or self.env.resource_scale
        applied = assign_credit(
            self.store,
            trajectory.deciding_entry,
            trajectory.supporting_entries,
            trajectory.outcome.delta,
            scale,
            self.config,
            cycle,
        )
        advance_lifecycle(
            self.store,
            applied,
            trajectory.outcome.delta,
            trajectory.deciding_entry,
        )

    def _write_experience(self, trajectory: Trajectory, cycle: int) -> int:
        """Distill the cycle's best trajectory into a new entry.

        The survival paper folds surviving behaviors back into the model
        with supervised fine-tuning. The memory-layer analog is a write:
        the successful trajectory becomes a candidate entry, and then it
        has to survive on its own from here. This method is the intended
        override seam for richer distillation (an LLM summarizing the
        trajectory, for example).

        The write reinforces the knowledge that produced the outcome, so
        the question comes from the deciding entry, not from the task.
        An earlier version copied the task prompt verbatim and the
        resulting entries lexically matched every future task that shared
        the template, then confidently decided questions they knew
        nothing about. Selection executed them for it, but they kept
        being reborn. Reinforcing provenance avoids that churn.

        In LLM mode a multi-citation answer has no single decider; the
        first cited entry stands in as parent (citation order is the
        model's own ranking of what it used).
        """
        parent_id = trajectory.deciding_entry or (
            trajectory.supporting_entries[0] if trajectory.supporting_entries else None
        )
        parent = self.store.get(parent_id) if parent_id else None
        if parent is None:
            return 0
        candidate = MemoryEntry(
            question=parent.question,
            answer=(
                f"{parent.answer} Confirmed by outcome: {trajectory.outcome.detail}."
            ),
            kind=EntryKind.EXPERIENCE,
            sources=[f"cycle-{cycle}"],
            born_cycle=cycle,
        )
        for existing in self.store.alive():
            if (
                self.store.similarity(candidate, existing)
                > self.config.experience_dedup_threshold
            ):
                return 0
        self.store.add(candidate)
        return 1
