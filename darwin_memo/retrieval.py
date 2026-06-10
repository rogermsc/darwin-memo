"""Pluggable retrieval strategies for the memory store.

The store owns the energy ledger and persistence; a retriever owns how
entries are matched to queries and to each other. Two implementations
ship: lexical (the zero-dependency default) and embedding-based, which
accepts any function from text to a vector, so any provider fits.

One invariant binds every retriever: scores are pure relevance and
never read entry energy. Selection pressure must come from outcomes,
not from retrieval preferring incumbents. The store applies energy as
a sort tie-break only.
"""

from __future__ import annotations

import math
import re
import zlib
from collections import Counter
from collections.abc import Sequence
from typing import Any, Protocol

from .types import MemoryEntry

# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


class Retriever(Protocol):
    def rank(
        self, query: str, entries: Sequence[MemoryEntry]
    ) -> list[tuple[MemoryEntry, float]]:
        """Score entries against a query. Relevance only, never energy."""
        ...

    def similarity(self, a: MemoryEntry, b: MemoryEntry) -> float:
        """Pairwise similarity in [0, 1], used by consolidation."""
        ...

    def forget(self, entry_id: str) -> None:
        """Drop any cached state for a buried entry."""
        ...

    def dump_state(self) -> dict[str, Any]:
        """State worth persisting alongside the store. {} if none."""
        ...

    def load_state(self, state: dict[str, Any]) -> None:
        """Restore state produced by dump_state."""
        ...


class EmbeddingFn(Protocol):
    def __call__(self, text: str) -> list[float]: ...


# ---------------------------------------------------------------------------
# Lexical retrieval (default)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"[a-z0-9.*]+")

_STOPWORD_TEXT = (
    "a an and are as at be by for from has have in is it of on or that the "
    "this these those to was were will with what which who how when where "
    "why does do under over after before during between within against "
    "but if then than so may might must should could would"
)
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def _stem(token: str) -> str:
    """Light plural stemming: files -> file, logs -> log, but miss stays miss."""
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


class LexicalRetriever:
    """Smoothed-IDF lexical overlap in pure Python.

    ``min_coverage`` is a relevance floor: an entry qualifies only if
    the IDF mass it matches is a meaningful share of the whole query.
    Without it, an entry sharing one structural token ("safe", "file")
    can end up deciding questions it knows nothing about, and the
    environment then punishes otherwise good entries for out-of-domain
    answers. This is MeMo's noisy-retrieval robustness concern showing
    up in miniature: better for memory to stay silent than to guess.
    """

    def __init__(self, min_coverage: float = 0.25) -> None:
        self.min_coverage = min_coverage
        # QA text never mutates after add (only energy and usage counters
        # do), so token sets are cached per entry id and dropped on forget.
        self._token_cache: dict[str, frozenset[str]] = {}

    def _entry_tokens(self, entry: MemoryEntry) -> frozenset[str]:
        """The matchable text of an entry is its question plus answer."""
        cached = self._token_cache.get(entry.id)
        if cached is not None:
            return cached
        tokens = frozenset(tokenize(entry.question + " " + entry.answer))
        self._token_cache[entry.id] = tokens
        return tokens

    def rank(
        self, query: str, entries: Sequence[MemoryEntry]
    ) -> list[tuple[MemoryEntry, float]]:
        query_tokens = set(tokenize(query))
        if not query_tokens or not entries:
            return []

        doc_freq: Counter[str] = Counter()
        for entry in entries:
            doc_freq.update(self._entry_tokens(entry))

        n_docs = len(entries)
        query_idf = {t: math.log(1 + n_docs / (1 + doc_freq[t])) for t in query_tokens}
        query_mass = sum(query_idf.values())
        if query_mass <= 0:
            return []

        scored: list[tuple[MemoryEntry, float]] = []
        for entry in entries:
            tokens = self._entry_tokens(entry)
            score = sum(idf for t, idf in query_idf.items() if t in tokens)
            if score / query_mass >= self.min_coverage:
                scored.append((entry, score))
        return scored

    def similarity(self, a: MemoryEntry, b: MemoryEntry) -> float:
        """Jaccard similarity over QA tokens."""
        ta = self._entry_tokens(a)
        tb = self._entry_tokens(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    def forget(self, entry_id: str) -> None:
        self._token_cache.pop(entry_id, None)

    def dump_state(self) -> dict[str, Any]:
        return {}

    def load_state(self, state: dict[str, Any]) -> None:
        return None


# ---------------------------------------------------------------------------
# Embedding retrieval
# ---------------------------------------------------------------------------


class HashingEmbedder:
    """Zero-dependency character n-gram hashing embedder.

    Each 3-to-5 character n-gram is hashed with crc32 into a fixed-dim
    vector, which is then L2 normalized. crc32 rather than the builtin
    ``hash`` because the builtin is salted per process and would break
    persisted vectors. What this buys is morphology and typo robustness
    ("databse" still lands near database entries). What it does not buy
    is synonym recall; for that, pass a real model through
    :class:`EmbeddingFn`.
    """

    def __init__(self, dims: int = 256, ngram_range: tuple[int, int] = (3, 5)) -> None:
        self.dims = dims
        self.ngram_range = ngram_range

    def __call__(self, text: str) -> list[float]:
        vec = [0.0] * self.dims
        normalized = " ".join(tokenize(text))
        lo, hi = self.ngram_range
        for n in range(lo, hi + 1):
            for i in range(len(normalized) - n + 1):
                gram = normalized[i : i + n]
                h = zlib.crc32(gram.encode("utf-8"))
                sign = 1.0 if (h >> 31) & 1 == 0 else -1.0
                vec[h % self.dims] += sign
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            return vec
        return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b, strict=False))
    da = math.sqrt(sum(x * x for x in a))
    db = math.sqrt(sum(y * y for y in b))
    if da == 0 or db == 0:
        return 0.0
    return num / (da * db)


class EmbeddingRetriever:
    """Cosine retrieval over vectors from any embedding function.

    The embedding function is anything matching :class:`EmbeddingFn`,
    so a sentence-transformers model, an API embedding endpoint, or the
    zero-dependency :class:`HashingEmbedder` all fit. Vectors are cached
    per entry id and persist through ``MemoryStore.save``, which matters
    when embeddings cost money.

    ``min_similarity`` plays the role lexical ``min_coverage`` plays:
    below the floor, memory stays silent rather than guessing.

    Honest scaling note: ``rank`` is O(population x dims) in pure
    Python. Fine to a few thousand entries; past that you want numpy or
    an ANN index, which is deliberately out of scope for the
    zero-dependency core.

    Consolidation note: cosine similarity runs hotter than Jaccard. If
    you use this retriever with the survival loop, raise
    ``SurvivalConfig.merge_threshold`` to roughly 0.85-0.9 or unrelated
    entries will merge.
    """

    def __init__(self, embed: EmbeddingFn, min_similarity: float = 0.30) -> None:
        self.embed = embed
        self.min_similarity = min_similarity
        self._vectors: dict[str, list[float]] = {}

    def _entry_vector(self, entry: MemoryEntry) -> list[float]:
        cached = self._vectors.get(entry.id)
        if cached is not None:
            return cached
        vec = self.embed(entry.question + " " + entry.answer)
        self._vectors[entry.id] = vec
        return vec

    def rank(
        self, query: str, entries: Sequence[MemoryEntry]
    ) -> list[tuple[MemoryEntry, float]]:
        if not entries:
            return []
        query_vec = self.embed(query)
        scored: list[tuple[MemoryEntry, float]] = []
        for entry in entries:
            score = _cosine(query_vec, self._entry_vector(entry))
            if score >= self.min_similarity:
                scored.append((entry, score))
        return scored

    def similarity(self, a: MemoryEntry, b: MemoryEntry) -> float:
        return max(0.0, _cosine(self._entry_vector(a), self._entry_vector(b)))

    def forget(self, entry_id: str) -> None:
        self._vectors.pop(entry_id, None)

    def dump_state(self) -> dict[str, Any]:
        return {"vectors": dict(self._vectors)}

    def load_state(self, state: dict[str, Any]) -> None:
        vectors = state.get("vectors", {})
        self._vectors.update(
            {str(k): [float(x) for x in v] for k, v in vectors.items()}
        )
