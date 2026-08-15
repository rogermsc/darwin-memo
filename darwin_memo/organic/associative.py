"""Associative graph: one vector per memory and relevance-weighted neighbours.

The substrate for the organic-memory layer. Additive and read-only w.r.t.
survival: it never touches energy. Zero-dependency by default (HashingEmbedder
+ brute-force cosine); an optional turbovec backend handles scale.
"""

from __future__ import annotations

import math
from typing import Protocol

from darwin_memo import MemoryEntry, MemoryStore
from darwin_memo.retrieval import HashingEmbedder


class Embedder(Protocol):
    def __call__(self, text: str) -> list[float]: ...


class Backend(Protocol):
    def add(self, entry_id: str, vector: list[float]) -> None: ...
    def remove(self, entry_id: str) -> None: ...
    def search(
        self, vector: list[float], k: int, exclude: str | None = None
    ) -> list[tuple[str, float]]: ...


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class BruteForceBackend:
    """Exact top-k cosine over an in-memory vector dict. Zero-dep; fine at the
    demo scale darwin-memo targets."""

    def __init__(self) -> None:
        self._vectors: dict[str, list[float]] = {}

    def add(self, entry_id: str, vector: list[float]) -> None:
        self._vectors[entry_id] = vector

    def remove(self, entry_id: str) -> None:
        self._vectors.pop(entry_id, None)

    def search(
        self, vector: list[float], k: int, exclude: str | None = None
    ) -> list[tuple[str, float]]:
        scored = [
            (eid, _cosine(vector, vec))
            for eid, vec in self._vectors.items()
            if eid != exclude
        ]
        # Ties keep insertion order, and never break on the id: an id is
        # ``uuid4().hex[:12]``, so an id tiebreak is a coin flip at a fixed
        # seed. Python's sort is stable and ``reverse=True`` does not reverse
        # equal elements, so score-only ordering falls back to the order
        # entries were added --- which callers control and the corpus fixes.
        # Ties are the common case here, not a corner one: HashingEmbedder
        # puts unrelated entries at cosine 0.0 in bulk, and everything
        # downstream (centrality, importance, upkeep relief) reads this rank.
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]


def _entry_text(entry: MemoryEntry) -> str:
    """Gist + detail, the text we embed for relatedness."""
    return f"{entry.question} {entry.answer}"


class AssociativeGraph:
    """Memories embedded into a vector space with relevance-weighted links."""

    def __init__(
        self, embedder: Embedder | None = None, backend: Backend | None = None
    ) -> None:
        self.embedder: Embedder = embedder or HashingEmbedder()
        self.backend: Backend = backend or BruteForceBackend()
        self._vectors: dict[str, list[float]] = {}
        self._ordinals: dict[str, int] = {}
        self._next_ordinal = 0

    def add(self, entry: MemoryEntry) -> None:
        vec = self.embedder(_entry_text(entry))
        self._vectors[entry.id] = vec
        if entry.id not in self._ordinals:
            self._ordinals[entry.id] = self._next_ordinal
            self._next_ordinal += 1
        self.backend.add(entry.id, vec)

    def ordinal(self, entry_id: str) -> int:
        """Insertion position, for callers that must break a tie somehow.

        The only stable order in play: ids are random per process, so any
        ranking that resolves equal scores by id is unreproducible. Unknown
        ids sort last.
        """
        return self._ordinals.get(entry_id, self._next_ordinal)

    def remove(self, entry_id: str) -> None:
        self._vectors.pop(entry_id, None)
        self._ordinals.pop(entry_id, None)
        self.backend.remove(entry_id)

    @property
    def ids(self) -> set[str]:
        """Every id currently embedded in the graph.

        Exists so a caller holding a graph and a store can tell whether the
        two have drifted apart without reaching into private state.
        """
        return set(self._vectors)

    def related(self, entry_id: str, k: int = 5) -> list[tuple[str, float]]:
        """Up to k related memory ids with relevance in [0, 1] (cosine, clamped)."""
        vec = self._vectors.get(entry_id)
        if vec is None:
            return []
        return [
            (eid, max(0.0, min(1.0, score)))
            for eid, score in self.backend.search(vec, k, exclude=entry_id)
        ]


def build_graph(
    store: MemoryStore,
    embedder: Embedder | None = None,
    backend: Backend | None = None,
) -> AssociativeGraph:
    """Build a graph from a store's living entries."""
    graph = AssociativeGraph(embedder, backend)
    for entry in store.alive():
        graph.add(entry)
    return graph


def store_related(
    store: MemoryStore,
    entry_id: str,
    k: int = 5,
    embedder: Embedder | None = None,
    backend: Backend | None = None,
) -> list[tuple[str, float]]:
    """Convenience: related memories for one entry, built from the store."""
    return build_graph(store, embedder, backend).related(entry_id, k)
