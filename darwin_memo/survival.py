"""The survival loop: environment-mediated selection over memory.

This is where the two papers meet. MeMo supplies what is being selected,
a population of reflection-QA memory entries serving a frozen LLM. The
survival paper supplies how selection works:

1. Memory proposes: the query protocol answers each task from entries.
2. The environment acts and measures a real resource delta.
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

from .consolidate import consolidate
from .environments import Environment
from .protocol import QueryProtocol, decision_polarity
from .store import MemoryStore
from .types import CycleStats, EntryKind, MemoryEntry, Trajectory


@dataclass
class SurvivalConfig:
    cycles: int = 30
    credit_gain: float = 0.6
    supporting_share: float = 0.25
    consolidate_every: int = 5
    merge_threshold: float = 0.55
    write_experience: bool = True
    experience_min_delta: float = 0.0
    default_act: bool = False


@dataclass
class SurvivalReport:
    stats: list[CycleStats] = field(default_factory=list)
    trajectories: list[Trajectory] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"{'cycle':>5} {'pop':>4} {'births':>6} {'deaths':>6} {'merges':>6} "
            f"{'energy':>8} {'resource Δ':>12}"
        ]
        for s in self.stats:
            lines.append(
                f"{s.cycle:>5} {s.population:>4} {s.births:>6} {s.deaths:>6} "
                f"{s.merges:>6} {s.total_energy:>8.2f} {s.resource_delta:>12.0f}"
            )
        return "\n".join(lines)


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

    def run(self, on_cycle=None) -> SurvivalReport:
        report = SurvivalReport()
        for cycle in range(self.config.cycles):
            stats = self.run_cycle(cycle, report)
            report.stats.append(stats)
            if on_cycle:
                on_cycle(stats)
        return report

    def run_cycle(self, cycle: int, report: SurvivalReport) -> CycleStats:
        cfg = self.config
        births = 0
        resource_delta = 0.0
        best: Trajectory | None = None

        for task in self.env.tasks(cycle):
            answer = self.protocol.answer(task.prompt)
            act = decision_polarity(answer.text)
            if act is None:
                act = cfg.default_act
            outcome = self.env.verify(task, act, answer_text=answer.text)
            resource_delta += outcome.delta

            trajectory = Trajectory(
                cycle=cycle,
                task=task.prompt,
                answer=answer.text,
                deciding_entry=answer.deciding_entry,
                supporting_entries=answer.supporting_entries,
                outcome=outcome,
            )
            report.trajectories.append(trajectory)
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

        return CycleStats(
            cycle=cycle,
            population=len(self.store),
            births=births,
            deaths=len(dead),
            merges=merges,
            total_energy=self.store.total_energy(),
            resource_delta=resource_delta,
            dead_ids=[e.id for e in dead],
        )

    # ------------------------------------------------------------------

    def _assign_credit(self, trajectory: Trajectory, cycle: int) -> None:
        """Energy moves only along provenance, scaled by the real delta.

        tanh keeps a single huge outcome from making an entry immortal,
        and keeps a single disaster from instantly executing an entry
        that was right ninety-nine times. Selection still gets there,
        it just takes evidence to do it.
        """
        cfg = self.config
        normalized = math.tanh(trajectory.outcome.delta / self.env.resource_scale)
        credit = cfg.credit_gain * normalized
        if credit == 0.0:
            return
        if trajectory.deciding_entry:
            self.store.credit(trajectory.deciding_entry, credit, cycle)
        for entry_id in trajectory.supporting_entries:
            self.store.credit(entry_id, credit * cfg.supporting_share, cycle)

    def _write_experience(self, trajectory: Trajectory, cycle: int) -> int:
        """Distill the cycle's best trajectory into a new entry.

        The survival paper folds surviving behaviors back into the model
        with supervised fine-tuning. The memory-layer analog is a write:
        the successful trajectory becomes a candidate entry, and then it
        has to survive on its own from here.

        The write reinforces the knowledge that produced the outcome, so
        the question comes from the deciding entry, not from the task.
        An earlier version copied the task prompt verbatim and the
        resulting entries lexically matched every future task that shared
        the template, then confidently decided questions they knew
        nothing about. Selection executed them for it, but they kept
        being reborn. Reinforcing provenance avoids that churn.
        """
        parent = (
            self.store.get(trajectory.deciding_entry)
            if trajectory.deciding_entry
            else None
        )
        if parent is None:
            return 0
        question = parent.question
        answer = (
            f"{parent.answer} Confirmed by outcome: {trajectory.outcome.detail}."
        )
        candidate = MemoryEntry(
            question=question,
            answer=answer,
            kind=EntryKind.EXPERIENCE,
            sources=[f"cycle-{cycle}"],
            born_cycle=cycle,
        )
        for existing in self.store.alive():
            if self.store.similarity(candidate, existing) > 0.8:
                return 0
        self.store.add(candidate)
        return 1
