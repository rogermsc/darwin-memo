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
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .retrieval import LexicalRetriever, Retriever, tokenize
from .temporal import recency_weight
from .types import EntryKind, MemoryEntry

# fcntl is POSIX-only. CI runs Linux, so the flock path is the tested
# one; where the import fails (Windows) the advisory lock degrades to a
# no-op, which is exactly the lockless behavior every release before
# 0.5.0 had on every platform. The single-writer contract is unchanged
# either way.
try:
    import fcntl
except ImportError:  # pragma: no cover - Windows only
    fcntl = None  # type: ignore[assignment]

__all__ = ["MemoryStore", "StoreLockedError", "tokenize"]


class StoreLockedError(RuntimeError):
    """Another process holds the advisory lock on a store file."""


@contextmanager
def store_lock(path: str | Path) -> Iterator[None]:
    """Hold the sidecar advisory lock for one persistence operation.

    darwin-memo is single-writer by contract, and this lock does not
    change that: there is no blocking, no waiting, no multi-writer
    merge. What it adds is noise. Two operations overlapping on one
    store file used to clobber each other silently (last writer wins);
    now the second one raises :class:`StoreLockedError` instead. The
    lock is ``fcntl.flock`` with ``LOCK_EX | LOCK_NB`` on a sidecar
    file (``memory.json.lock``), held only for the duration of one save
    or load, so the atomic temp-file-and-rename dance on the store file
    itself never touches the lock. The sidecar is never unlinked:
    removing it would race a concurrent acquisition onto a dead inode.
    """
    if fcntl is None:  # pragma: no cover - Windows only
        yield
        return
    target = Path(path)
    lock_path = target.with_name(target.name + ".lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise StoreLockedError(
                f"{lock_path} is held by another process. darwin-memo "
                "is single-writer: concurrent operations on one store "
                "file would silently overwrite each other, so this one "
                "refuses to run. Retry after the holder finishes."
            ) from exc
        yield
    finally:
        os.close(fd)


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

    def retrieve(
        self,
        query: str,
        k: int = 3,
        *,
        half_life: float | None = None,
        now_cycle: int | None = None,
        kind: EntryKind | str | None = None,
        source: str | None = None,
    ) -> list[tuple[MemoryEntry, float]]:
        """Rank alive entries against a query.

        Scoring belongs entirely to the retriever. Energy breaks ties
        only: selection pressure must come from outcomes, not from
        retrieval preferring incumbents.

        ``kind`` and ``source`` filter the candidate population before
        ranking; an entry matches ``source`` when it appears in its
        ``sources`` list, and an unknown ``kind`` raises ``ValueError``
        rather than silently matching nothing.

        ``half_life`` opts into recency-weighted ranking, off by
        default: scores halve for every ``half_life`` ticks since an
        entry last settled (its born tick if it never has). A pure
        ranking concern, like everything else here: balances, credit
        assignment, and survival economics never see it. A non-positive
        ``half_life`` raises ``ValueError`` rather than silently ranking
        without recency. ``now_cycle``
        anchors the decay clock; callers that track time (the Ledger)
        pass their tick count, and when omitted the latest tick
        recorded on any alive entry stands in.
        """
        if half_life is not None and half_life <= 0:
            raise ValueError(
                f"half_life must be positive, got {half_life}; pass None "
                "to rank without recency weighting"
            )
        entries = list(self._entries.values())
        if kind is not None:
            kind_value = EntryKind(kind).value
            entries = [e for e in entries if e.kind.value == kind_value]
        if source is not None:
            entries = [e for e in entries if source in e.sources]
        scored = self.retriever.rank(query, entries)
        if half_life is not None and scored:
            if now_cycle is None:
                now_cycle = max(
                    max(e.born_cycle, e.last_used_cycle) for e in self._entries.values()
                )
            scored = [
                (entry, score * recency_weight(entry, now_cycle, half_life))
                for entry, score in scored
            ]
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
        with store_lock(path):
            write_json_atomic(path, self.to_payload())

    @classmethod
    def load(cls, path: str | Path, retriever: Retriever | None = None) -> MemoryStore:
        with store_lock(path):
            payload = json.loads(Path(path).read_text())
        return cls.from_payload(payload, retriever=retriever)


def write_json_atomic(path: str | Path, payload: dict[str, object]) -> None:
    """Write via a sibling temp file and rename, so a crash mid-write can
    never leave a truncated file behind (the previous snapshot survives)."""
    target = Path(path)
    temp = target.with_name(target.name + ".tmp")
    temp.write_text(json.dumps(payload, indent=2))
    os.replace(temp, target)
