"""Dynamics: spreading activation + Hebbian reweighting — the moving organic memory.

Phase 3 of the organic layer. ``HebbianWeights`` records learned co-recall
strengths; ``OrganicMemory`` ties the Phase 1 associative graph (innate cosine),
Phase 2 activation (fast salience), and these learned weights (slow association)
into one adaptive object. A recall spreads activation one hop to related
memories and strengthens the links it traverses; unused links fade on decay.

Organic-only and in-memory: the darwin-memo core is untouched, there are no new
runtime deps, and there is no judge. Activation and learned weights gate
SURFACING and RANKING only — there is no code path from this module to the
energy ledger. Value is still earned only by survival.
"""

from __future__ import annotations

from darwin_memo import MemoryEntry, MemoryStore

from .activation import ActivationState
from .activation import surface as _surface
from .associative import Backend, Embedder, build_graph

SPREAD_FACTOR = 0.5
HEBB_INCREMENT = 0.25
HEBB_DECAY = 0.9
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
    """The moving organic memory: graph + activation + learned weights as one.

    Builds an :class:`AssociativeGraph` over the store's living entries (innate
    cosine relatedness), a fresh :class:`ActivationState` (fast recall salience),
    and a fresh :class:`HebbianWeights` (slow learned association). A recall
    spreads activation one hop and strengthens the links it traverses; decay
    runs the two timescales. Surfacing/ranking only — never survival.
    """

    def __init__(
        self,
        store: MemoryStore,
        embedder: Embedder | None = None,
        backend: Backend | None = None,
    ) -> None:
        self.graph = build_graph(store, embedder, backend)
        self.state = ActivationState()
        self.hebbian = HebbianWeights()

    def related(self, entry_id: str, k: int = 5) -> list[tuple[str, float]]:
        """Effective relatedness: ``clamp01(cosine + learned)``, top-k.

        Takes the cosine top-``2k`` from the innate graph plus any purely
        learned neighbours (cosine treated as 0), overlays the learned weights,
        re-ranks, and returns the top ``k`` (deterministic; id breaks ties).
        """
        cosine = dict(self.graph.related(entry_id, 2 * k))
        learned = self.hebbian.neighbors(entry_id)
        candidates = set(cosine) | set(learned)
        scored = [
            (cid, _clamp01(cosine.get(cid, 0.0) + learned.get(cid, 0.0)))
            for cid in candidates
        ]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:k]

    def recall(
        self, entry_id: str, k: int = 5, spread: float = SPREAD_FACTOR
    ) -> None:
        """The reminder: light up ``entry_id``, spread a fraction of activation
        one hop to its effective neighbours, and strengthen each link traversed.
        """
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
