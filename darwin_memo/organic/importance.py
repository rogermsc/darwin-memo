"""Earned importance + potentiation — Phase 4 of the organic layer.

Importance accumulates from three measured quantities, never a judgement:
how often a memory is recalled, how much outcome credit it has actually
earned, and how central it is in the associative graph. It does two things:
biases retrieval ranking, and — when a caller opts in by passing
``upkeep_scale()`` to ``MemoryStore.charge_upkeep`` — *slows upkeep*, so an
important memory starves more slowly. Death remains an energy-floor event:
the store clamps any multiplier at ``MIN_UPKEEP_SCALE``, so potentiation
stretches the starvation horizon and never removes it.

READ THIS BEFORE WIRING IT INTO A LOOP. Potentiation makes usage a
retention signal, and this repo has measured that design losing. The
``salience_matched`` arm (``bench/results/salience.json``, 10 seeds) ranked
victims by recency+importance and killed poison in 0.20 of runs against
random eviction's 0.80 and survival's 1.00, because usage cannot tell
"used" from "useful" — consulted poison gets shielded. That arm is the
stronger form (importance picks the victim); this is the gentler one
(importance slows the burn). Nothing in darwin-memo calls ``upkeep_scale()``
for you: ``SurvivalLoop`` and ``Ledger`` charge flat upkeep exactly as
before. Wire it deliberately, and measure your own store when you do.
"""

from __future__ import annotations

from darwin_memo import MemoryStore
from darwin_memo.store import MIN_UPKEEP_SCALE

# Equal weights: the three components are different units (a count, an
# energy balance, a cosine) and there is no measured basis for ranking
# one above another. Each is normalised into [0, 1] against the live
# population before averaging, so importance is a *relative* standing
# within one store rather than an absolute score.
RECALL_WEIGHT = 1 / 3
CREDIT_WEIGHT = 1 / 3
CENTRALITY_WEIGHT = 1 / 3
# Maximum upkeep relief at importance 1.0. Kept inside the store's own
# floor so the policy here can never be the thing that makes an entry
# unkillable, whatever it is tuned to.
MAX_RELIEF = 0.5
SPAWN_ENERGY = 1.0


def _normalise(value: float, peak: float) -> float:
    """``value`` as a fraction of the population's peak, in [0, 1]."""
    if peak <= 0.0:
        return 0.0
    return max(0.0, min(1.0, value / peak))


class EarnedImportance:
    """Recall counts + earned credit + graph centrality, as one [0, 1] score.

    Counts live here rather than on the entry: importance is organic state,
    and writing it onto :class:`MemoryEntry` would put a usage signal inside
    the object the selection path reads.
    """

    def __init__(self) -> None:
        self._recalls: dict[str, int] = {}

    def record_recall(self, entry_id: str) -> None:
        self._recalls[entry_id] = self._recalls.get(entry_id, 0) + 1

    def recalls(self, entry_id: str) -> int:
        return self._recalls.get(entry_id, 0)

    def scores(
        self, store: MemoryStore, centrality: dict[str, float] | None = None
    ) -> dict[str, float]:
        """Importance in [0, 1] for every living entry, highest-first ties intact.

        ``centrality`` is the mean effective relatedness of each entry to its
        neighbours, supplied by :class:`OrganicMemory` (which owns the graph).
        Absent, the component contributes zero rather than being guessed.
        """
        alive = store.alive()
        if not alive:
            return {}
        centrality = centrality or {}
        peak_recalls = float(max((self.recalls(e.id) for e in alive), default=0))
        # Credit is energy earned ABOVE the spawn grant: an entry that has
        # only ever paid upkeep has earned nothing, and a brand-new entry
        # must not read as important merely for being new.
        credits = {e.id: max(0.0, e.energy - SPAWN_ENERGY) for e in alive}
        peak_credit = max(credits.values(), default=0.0)
        return {
            e.id: (
                RECALL_WEIGHT * _normalise(self.recalls(e.id), peak_recalls)
                + CREDIT_WEIGHT * _normalise(credits[e.id], peak_credit)
                + CENTRALITY_WEIGHT * max(0.0, min(1.0, centrality.get(e.id, 0.0)))
            )
            for e in alive
        }

    def upkeep_scale(
        self, store: MemoryStore, centrality: dict[str, float] | None = None
    ) -> dict[str, float]:
        """Per-entry upkeep multipliers for ``MemoryStore.charge_upkeep(scale=...)``.

        ``1.0`` at importance 0 down to ``1 - MAX_RELIEF`` at importance 1,
        floored again at the store's ``MIN_UPKEEP_SCALE`` so a retuned
        ``MAX_RELIEF`` cannot buy immortality.
        """
        return {
            entry_id: max(MIN_UPKEEP_SCALE, 1.0 - MAX_RELIEF * score)
            for entry_id, score in self.scores(store, centrality).items()
        }
