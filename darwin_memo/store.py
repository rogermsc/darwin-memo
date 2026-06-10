"""The memory store: a population of QA entries under survival pressure.

MeMo keeps memory in the weights of a small trained model. This store is
the structured stand-in for that parametric memory: it holds the same
reflection-QA pairs the MeMo pipeline produces and serves the same
read interface the query protocol expects. ``training/`` shows how to
distill a surviving store into an actual parametric memory model.

What the store adds on top of MeMo is the survival ledger. Entries pay
upkeep every cycle and earn energy only through credited outcomes, so
the population self-curates without any human review or judge model.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from .types import MemoryEntry

_TOKEN_RE = re.compile(r"[a-z0-9.*]+")

_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it of on or that the "
    "this these those to was were will with what which who how when where "
    "why does do under over after before during between within against "
    "but if then than so may might must should could would".split()
)


def _stem(token: str) -> str:
    """Light plural stemming: files -> file, logs -> log, but miss stays miss."""
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    return [
        _stem(t) for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS
    ]


class MemoryStore:
    """Holds entries, scores retrieval lexically, and runs the energy ledger."""

    def __init__(self, max_energy: float = 5.0, upkeep: float = 0.05) -> None:
        self.max_energy = max_energy
        self.upkeep = upkeep
        self._entries: dict[str, MemoryEntry] = {}
        self._graveyard: dict[str, MemoryEntry] = {}
        # QA text never mutates after add (only energy and usage counters
        # do), so token sets are cached per entry id and dropped on bury.
        self._token_cache: dict[str, frozenset[str]] = {}

    # ------------------------------------------------------------------
    # Population access
    # ------------------------------------------------------------------

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        self._entries[entry.id] = entry
        return entry

    def get(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.get(entry_id)

    def alive(self) -> list[MemoryEntry]:
        return list(self._entries.values())

    def graveyard(self) -> list[MemoryEntry]:
        return list(self._graveyard.values())

    def __len__(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def _entry_tokens(self, entry: MemoryEntry) -> frozenset[str]:
        """The matchable text of an entry is its question plus answer."""
        cached = self._token_cache.get(entry.id)
        if cached is not None:
            return cached
        tokens = frozenset(tokenize(entry.question + " " + entry.answer))
        if entry.id in self._entries:
            self._token_cache[entry.id] = tokens
        return tokens

    def retrieve(
        self, query: str, k: int = 3, min_coverage: float = 0.25
    ) -> list[tuple[MemoryEntry, float]]:
        """Rank alive entries against a query.

        Scoring is smoothed-IDF lexical overlap in pure Python. Energy
        breaks ties only: selection pressure must come from outcomes, not
        from retrieval preferring incumbents.

        ``min_coverage`` is a relevance floor: an entry qualifies only if
        the IDF mass it matches is a meaningful share of the whole query.
        Without it, an entry sharing one structural token ("safe", "file")
        can end up deciding questions it knows nothing about, and the
        environment then punishes otherwise good entries for out-of-domain
        answers. This is MeMo's noisy-retrieval robustness concern showing
        up in miniature: better for memory to stay silent than to guess.
        """
        query_tokens = set(tokenize(query))
        if not query_tokens or not self._entries:
            return []

        doc_freq: Counter[str] = Counter()
        for entry in self._entries.values():
            doc_freq.update(self._entry_tokens(entry))

        n_docs = len(self._entries)
        query_idf = {
            t: math.log(1 + n_docs / (1 + doc_freq[t])) for t in query_tokens
        }
        query_mass = sum(query_idf.values())
        if query_mass <= 0:
            return []

        scored: list[tuple[MemoryEntry, float]] = []
        for entry in self._entries.values():
            tokens = self._entry_tokens(entry)
            score = sum(idf for t, idf in query_idf.items() if t in tokens)
            if score / query_mass >= min_coverage:
                scored.append((entry, score))

        scored.sort(key=lambda pair: (pair[1], pair[0].energy), reverse=True)
        return scored[:k]

    def similarity(self, a: MemoryEntry, b: MemoryEntry) -> float:
        """Jaccard similarity over QA tokens, used by consolidation."""
        ta = self._entry_tokens(a)
        tb = self._entry_tokens(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    # ------------------------------------------------------------------
    # Survival ledger
    # ------------------------------------------------------------------

    def credit(self, entry_id: str, amount: float, cycle: int) -> None:
        entry = self._entries.get(entry_id)
        if entry is None:
            return
        entry.energy = min(self.max_energy, entry.energy + amount)
        entry.uses += 1
        entry.last_used_cycle = cycle

    def charge_upkeep(self) -> list[MemoryEntry]:
        """Charge every alive entry one cycle of upkeep, bury the dead."""
        dead: list[MemoryEntry] = []
        for entry in list(self._entries.values()):
            entry.energy -= self.upkeep
            if not entry.alive:
                dead.append(entry)
        for entry in dead:
            self.bury(entry.id)
        return dead

    def bury(self, entry_id: str) -> None:
        entry = self._entries.pop(entry_id, None)
        self._token_cache.pop(entry_id, None)
        if entry is not None:
            entry.energy = min(entry.energy, 0.0)
            self._graveyard[entry.id] = entry

    def total_energy(self) -> float:
        return sum(e.energy for e in self._entries.values())

    def energy_share_by_kind(self) -> dict[str, float]:
        """Where the probability mass sits, in the survival paper's framing."""
        total = self.total_energy()
        if total <= 0:
            return {}
        shares: dict[str, float] = {}
        for entry in self._entries.values():
            shares[entry.kind.value] = shares.get(entry.kind.value, 0.0) + entry.energy
        return {k: v / total for k, v in shares.items()}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        payload = {
            "config": {
                "max_energy": self.max_energy,
                "upkeep": self.upkeep,
            },
            "entries": [e.to_dict() for e in self._entries.values()],
            "graveyard": [e.to_dict() for e in self._graveyard.values()],
        }
        Path(path).write_text(json.dumps(payload, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "MemoryStore":
        payload = json.loads(Path(path).read_text())
        store = cls(**payload["config"])
        for d in payload["entries"]:
            store._entries[d["id"]] = MemoryEntry.from_dict(d)
        for d in payload["graveyard"]:
            store._graveyard[d["id"]] = MemoryEntry.from_dict(d)
        return store
