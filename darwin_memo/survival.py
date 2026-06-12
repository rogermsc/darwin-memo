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
    """
    normalized = math.tanh(delta / resource_scale)
    credit = config.credit_gain * normalized
    if credit == 0.0:
        return []
    applied: list[tuple[str, float]] = []
    if deciding_entry:
        applied.append((deciding_entry, credit))
        applied.extend(
            (entry_id, credit * config.supporting_share)
            for entry_id in supporting_entries
        )
    elif supporting_entries:
        share = credit / len(supporting_entries)
        applied.extend((entry_id, share) for entry_id in supporting_entries)
    for entry_id, amount in applied:
        store.credit(entry_id, amount, cycle)
    return applied


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

        The two failure modes a new environment hits are silent: memory
        never answers (phrasing mismatch or action vocabulary not read),
        or answers never earn (verify never pays out). Both end the same
        way, the whole population starving at spawn_energy / upkeep
        cycles, so the report says so instead of letting the table look
        like success.
        """
        total_tasks = sum(s.tasks for s in self.stats)
        if not total_tasks:
            return ""
        total_silent = sum(s.silent for s in self.stats)
        # Gross movement, not net: a cycle whose payouts exactly cancel
        # still paid out, and net-zero float equality must not trigger
        # a "never paid" diagnosis.
        never_paid = sum(s.nonzero_outcomes for s in self.stats) == 0
        notes = []
        if total_silent / total_tasks > 0.8:
            notes.append(
                f"memory was silent on {total_silent}/{total_tasks} tasks: "
                "task phrasing likely does not lexically overlap the corpus "
                "(see min_coverage), so nothing can earn energy"
            )
        if never_paid and total_silent / total_tasks <= 0.8:
            notes.append(
                "no task ever produced a nonzero outcome: the environment "
                "never paid out; check that verify() reads your answers (is "
                "decision_polarity's vocabulary right for your action verbs?)"
            )
        if not notes:
            return ""
        return "\n\nWARNING: " + "\nWARNING: ".join(notes)


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
        self.protocol = protocol or QueryProtocol(store)
        self.config = config or SurvivalConfig()

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

        dead = self.store.charge_upkeep()

        merges = 0
        if cfg.consolidate_every and (cycle + 1) % cfg.consolidate_every == 0:
            merges = consolidate(self.store, cycle, threshold=cfg.merge_threshold)

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
        """Energy moves only along provenance, via the shared credit rule."""
        scale = self.config.resource_scale or self.env.resource_scale
        assign_credit(
            self.store,
            trajectory.deciding_entry,
            trajectory.supporting_entries,
            trajectory.outcome.delta,
            scale,
            self.config,
            cycle,
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
