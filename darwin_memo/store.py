"""The memory store: a population of QA entries under survival pressure.

MeMo keeps memory in the weights of a small trained model. This store is
the structured stand-in for that parametric memory: it holds the same
reflection-QA pairs the MeMo pipeline produces and serves the same
read interface the query protocol expects. ``training/`` shows how to
distill a surviving store into an actual parametric memory model.

What the store adds on top of MeMo is the survival ledger. Entries pay
upkeep every cycle and earn energy only through credited outcomes, so
the population self-curates without any human review or judge model.

How entries are matched is delegated to a :class:`~darwin_memo.retrieval.Retriever`
(lexical by default, embeddings optional). The store keeps one rule
regardless of retriever: relevance scores never read energy, and energy
acts only as a sort tie-break.
"""

from __future__ import annotations

import json
import os
from collections.abc import Collection
from pathlib import Path
from typing import Any

from .retrieval import LexicalRetriever, Retriever, tokenize
from .types import MemoryEntry

__all__ = ["MemoryStore", "tokenize"]


class MemoryStore:
    """Holds entries, delegates retrieval, and runs the energy ledger."""

    def __init__(
        self,
        max_energy: float = 5.0,
        upkeep: float = 0.05,
        retriever: Retriever | None = None,
    ) -> None:
        self.max_energy = max_energy
        self.upkeep = upkeep
        self.retriever: Retriever = retriever or LexicalRetriever()
        self._entries: dict[str, MemoryEntry] = {}
        self._graveyard: dict[str, MemoryEntry] = {}

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

    def get_dead(self, entry_id: str) -> MemoryEntry | None:
        """O(1) graveyard lookup; the graveyard only grows."""
        return self._graveyard.get(entry_id)

    def dead_count(self) -> int:
        return len(self._graveyard)

    def __len__(self) -> int:
        return len(self._entries)

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def retrieve(self, query: str, k: int = 3) -> list[tuple[MemoryEntry, float]]:
        """Rank alive entries against a query.

        Scoring belongs entirely to the retriever. Energy breaks ties
        only: selection pressure must come from outcomes, not from
        retrieval preferring incumbents.
        """
        scored = self.retriever.rank(query, list(self._entries.values()))
        scored.sort(key=lambda pair: (pair[1], pair[0].energy), reverse=True)
        return scored[:k]

    def similarity(self, a: MemoryEntry, b: MemoryEntry) -> float:
        """Pairwise similarity via the retriever, used by consolidation."""
        return self.retriever.similarity(a, b)

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

    def charge_upkeep(self, protect: Collection[str] = ()) -> list[MemoryEntry]:
        """Charge every alive entry one cycle of upkeep, bury the dead.

        Entries in ``protect`` still pay upkeep but are not buried even
        at zero energy: the Ledger escrows entries with unsettled
        outcomes so a pending verdict cannot arrive after the execution.
        """
        protected = set(protect)
        dead: list[MemoryEntry] = []
        for entry in list(self._entries.values()):
            entry.energy -= self.upkeep
            if not entry.alive and entry.id not in protected:
                dead.append(entry)
        for entry in dead:
            self.bury(entry.id)
        return dead

    def bury(self, entry_id: str) -> None:
        entry = self._entries.pop(entry_id, None)
        self.retriever.forget(entry_id)
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

    def to_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "config": {
                "max_energy": self.max_energy,
                "upkeep": self.upkeep,
            },
            "entries": [e.to_dict() for e in self._entries.values()],
            "graveyard": [e.to_dict() for e in self._graveyard.values()],
        }
        retriever_state = self.retriever.dump_state()
        if retriever_state:
            payload["retriever"] = retriever_state
        return payload

    @classmethod
    def from_payload(
        cls, payload: dict[str, Any], retriever: Retriever | None = None
    ) -> MemoryStore:
        # Filter to known keys so files saved by other versions still load.
        config = {
            k: v for k, v in payload["config"].items() if k in ("max_energy", "upkeep")
        }
        store = cls(retriever=retriever, **config)
        for d in payload["entries"]:
            store._entries[d["id"]] = MemoryEntry.from_dict(d)
        for d in payload["graveyard"]:
            store._graveyard[d["id"]] = MemoryEntry.from_dict(d)
        if "retriever" in payload:
            store.retriever.load_state(payload["retriever"])
        return store

    def save(self, path: str | Path) -> None:
        write_json_atomic(path, self.to_payload())

    @classmethod
    def load(cls, path: str | Path, retriever: Retriever | None = None) -> MemoryStore:
        payload = json.loads(Path(path).read_text())
        return cls.from_payload(payload, retriever=retriever)


def write_json_atomic(path: str | Path, payload: dict[str, object]) -> None:
    """Write via a sibling temp file and rename, so a crash mid-write can
    never leave a truncated file behind (the previous snapshot survives)."""
    target = Path(path)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(payload, indent=2))
    os.replace(temp, target)
