"""Dynamics: spreading activation + Hebbian reweighting — the moving organic memory.

Phases 3-4 of the organic layer. ``HebbianWeights`` records learned co-recall
strengths; ``OrganicMemory`` ties the Phase 1 associative graph (innate cosine),
Phase 2 activation (fast salience), those learned weights (slow association),
and Phase 4 earned importance into one adaptive object. A recall spreads
activation one hop to related memories and strengthens the links it traverses;
unused links fade on decay.

Organic-only and in-memory: the darwin-memo core is untouched, there are no new
runtime deps, and there is no judge. Activation and learned weights gate
SURFACING and RANKING only.

Phase 4 is the exception, and it is deliberate: ``upkeep_scale()`` exists to be
passed to ``MemoryStore.charge_upkeep``, which makes importance touch survival.
Nothing here calls it — the caller opts in — and the store floors the
multiplier so a potentiated entry starves slower, never not at all. See
``importance.py`` for what this project's own bench measured about letting
usage decide retention.
"""

from __future__ import annotations

from darwin_memo import MemoryEntry, MemoryStore

from .activation import ActivationState
from .activation import surface as _surface
from .associative import Backend, Embedder, build_graph
from .importance import EarnedImportance

SPREAD_FACTOR = 0.5
HEBB_INCREMENT = 0.25
HEBB_DECAY = 0.9
# How much earned importance may lift a neighbour in the ranking. Small
# on purpose: importance is fed by centrality, which is fed by ranking,
# so this term is a loop. At 0.2 an important memory edges past a peer
# of similar relatedness; at 1.0 the loop would decide the ranking by
# itself and relatedness would stop mattering.
IMPORTANCE_BIAS = 0.2
_PRUNE_EPSILON = 1e-3


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


class HebbianWeights:
    """Symmetric learned co-recall strengths in [0, 1], keyed by id pair.

    A link strengthens each time its two ids are recalled together and decays
    globally so associations that stop being used fade back toward zero.
    """

    def __init__(self) -> None:
        self._weights: dict[frozenset[str], float] = {}

    def strengthen(self, a: str, b: str, by: float = HEBB_INCREMENT) -> None:
        """Add ``by`` to the (a, b) link, clamped to 1.0. Self-links ignored."""
        if a == b:
            return
        key = frozenset({a, b})
        self._weights[key] = min(1.0, self._weights.get(key, 0.0) + by)

    def decay(self, factor: float = HEBB_DECAY) -> None:
        """One cycle of forgetting: scale every link by ``factor``; prune ~0."""
        for key in list(self._weights):
            value = self._weights[key] * factor
            if value < _PRUNE_EPSILON:
                del self._weights[key]
            else:
                self._weights[key] = value

    def weight(self, a: str, b: str) -> float:
        """Learned strength of the (a, b) link; 0.0 if none (or a == b)."""
        if a == b:
            return 0.0
        return self._weights.get(frozenset({a, b}), 0.0)

    def neighbors(self, entry_id: str) -> dict[str, float]:
        """All ids learned-linked to ``entry_id`` mapped to their weight."""
        out: dict[str, float] = {}
        for key, value in self._weights.items():
            if entry_id in key:
                (other,) = key - {entry_id}
                out[other] = value
        return out


class OrganicMemory:
    """The moving organic memory: graph + activation + weights + importance.

    Builds an :class:`AssociativeGraph` over the store's living entries (innate
    cosine relatedness), a fresh :class:`ActivationState` (fast recall salience),
    a fresh :class:`HebbianWeights` (slow learned association), and a fresh
    :class:`EarnedImportance` (recalls + credit + centrality). A recall spreads
    activation one hop and strengthens the links it traverses; decay runs the
    two timescales.

    Everything here is surfacing and ranking except ``upkeep_scale()``, which
    the caller must hand to the store for it to mean anything.
    """

    def __init__(
        self,
        store: MemoryStore,
        embedder: Embedder | None = None,
        backend: Backend | None = None,
    ) -> None:
        self.store = store
        self.graph = build_graph(store, embedder, backend)
        self.state = ActivationState()
        self.hebbian = HebbianWeights()
        self.earned = EarnedImportance()

    def related(self, entry_id: str, k: int = 5) -> list[tuple[str, float]]:
        """Effective relatedness: ``clamp01(cosine + learned + bias)``, top-k.

        Takes the cosine top-``2k`` from the innate graph plus any purely
        learned neighbours (cosine treated as 0), overlays the learned weights
        and a small earned-importance bias, re-ranks, and returns the top ``k``
        (deterministic; id breaks ties).

        The bias reads recall counts and earned credit but **not** centrality,
        which is itself derived from this ranking: feeding it back in would
        make the graph's shape an input to its own measurement.
        """
        cosine = dict(self.graph.related(entry_id, 2 * k))
        learned = self.hebbian.neighbors(entry_id)
        candidates = set(cosine) | set(learned)
        # ponytail: recomputed per call, O(alive) each time. Fine at the
        # demo scale this layer targets; cache on a dirty flag if a store
        # ever gets big enough for it to show up.
        scores = self.earned.scores(self.store)
        scored = [
            (
                cid,
                _clamp01(
                    cosine.get(cid, 0.0)
                    + learned.get(cid, 0.0)
                    + IMPORTANCE_BIAS * scores.get(cid, 0.0)
                ),
            )
            for cid in candidates
        ]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:k]

    def centrality(self, k: int = 5) -> dict[str, float]:
        """Mean effective relatedness of each living entry to its neighbours.

        The graph half of importance: a memory wired into many strong links
        is central, one sitting alone is not. Measured off innate cosine plus
        learned weights — the effective view minus its own importance term,
        so centrality never counts itself.
        """
        out: dict[str, float] = {}
        for entry in self.store.alive():
            neighbours = self.graph.related(entry.id, k)
            learned = self.hebbian.neighbors(entry.id)
            scores = [_clamp01(rel + learned.get(nid, 0.0)) for nid, rel in neighbours]
            out[entry.id] = sum(scores) / len(scores) if scores else 0.0
        return out

    def importance(self, entry_id: str) -> float:
        """This entry's earned importance in [0, 1] (0.0 once it is not alive)."""
        return self.earned.scores(self.store, self.centrality()).get(entry_id, 0.0)

    def upkeep_scale(self) -> dict[str, float]:
        """Per-entry upkeep multipliers for ``store.charge_upkeep(scale=...)``.

        **Opt-in, and nothing in darwin-memo calls it for you.** Passing this
        makes usage a retention signal; read the warning at the top of
        ``importance.py`` and this project's salience_matched result before
        wiring it into a loop.
        """
        return self.earned.upkeep_scale(self.store, self.centrality())

    def recall(self, entry_id: str, k: int = 5, spread: float = SPREAD_FACTOR) -> None:
        """The reminder: light up ``entry_id``, spread a fraction of activation
        one hop to its effective neighbours, and strengthen each link traversed.

        Only the entry actually asked for counts as a recall. Neighbours were
        surfaced by association, not requested, and counting them would let
        one memory manufacture importance for everything it touches.
        """
        self.earned.record_recall(entry_id)
        self.state.bump(entry_id)
        for nbr, eff in self.related(entry_id, k):
            self.state.bump(nbr, to=spread * eff)
            self.hebbian.strengthen(entry_id, nbr)

    def decay(self) -> None:
        """One idle cycle: activation fades fast (x0.5), learned links slow (x0.9)."""
        self.state.decay()
        self.hebbian.decay()

    def surface(self, entry: MemoryEntry) -> str:
        """Gist when cold, full detail when this entry is activated."""
        return _surface(entry, self.state)
