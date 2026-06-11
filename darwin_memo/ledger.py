"""The Ledger: event-driven survival for real-world outcome timing.

``SurvivalLoop`` is batch-shaped: the environment proposes tasks, the
answer is verified in the same call, and credit lands immediately. Real
deployments are event-shaped: a question arrives now (a PR opens), the
outcome arrives later (CI finishes, the cost report lands tomorrow),
and upkeep should follow wall-clock or event cadence, neither of which
belongs to an environment object. The Ledger decouples the three
moments:

- :meth:`decide` answers a query through the normal protocol and
  returns a ticket carrying the provenance.
- :meth:`settle` is called whenever the outcome is known, with the
  measured resource delta. Credit flows along the ticket's provenance
  exactly as in the loop. If the answer is never acted on, call
  :meth:`abandon` so the ticket releases its escrow.
- :meth:`tick` advances time: upkeep, deaths, optional consolidation.

Escrow keeps the timing honest: entries named by ANY unsettled ticket
still pay upkeep but cannot be buried or merged away, so a verdict can
never arrive after the execution. Tickets left unsettled past
``expire_after`` ticks settle at delta zero (the outcome never arrived,
which earns nothing).

Persistence is the Ledger's job, because tickets must survive the
process that minted them: :meth:`save` writes one JSON file holding the
store AND the ledger state (pending tickets, tick count, history), and
:meth:`load` restores both. The file is forward and backward compatible
with plain ``MemoryStore`` files: a store-only file loads with fresh
ledger state, and ``MemoryStore.load`` ignores the ledger key.

Every event appends to an optional JSONL log, and :meth:`obituary`
answers the production question "why did this entry die" from that
history. The same selection rule applies throughout: no judge anywhere,
``settle`` takes a measurement.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .consolidate import consolidate
from .protocol import QueryProtocol
from .retrieval import Retriever
from .store import MemoryStore, write_json_atomic
from .survival import SurvivalConfig, assign_credit, is_silent

_HISTORY_CAP = 100  # per-entry events kept in memory; the JSONL log is full
_DAMAGE_EPSILON = 1e-9


@dataclass
class Ticket:
    """One decision waiting for its outcome."""

    query: str
    answer: str
    deciding_entry: str | None
    supporting_entries: list[str]
    born_tick: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def provenance(self) -> list[str]:
        ids = list(self.supporting_entries)
        if self.deciding_entry:
            ids.append(self.deciding_entry)
        return ids


class Ledger:
    """decide / settle / tick over a memory store, with escrow."""

    def __init__(
        self,
        store: MemoryStore,
        protocol: QueryProtocol | None = None,
        config: SurvivalConfig | None = None,
        resource_scale: float | None = None,
        event_log: str | Path | None = None,
    ) -> None:
        self.store = store
        self.protocol = protocol or QueryProtocol(store)
        self.config = config or SurvivalConfig()
        if resource_scale is not None:
            self.config.resource_scale = resource_scale
        if self.config.resource_scale is None:
            self.config.resource_scale = 1.0
        self.event_log = Path(event_log) if event_log else None
        self.tick_count = 0
        self._pending: dict[str, Ticket] = {}
        self._history: dict[str, list[str]] = {}
        self._damaged: set[str] = set()

    # ------------------------------------------------------------------
    # The three moments
    # ------------------------------------------------------------------

    def decide(self, query: str, k: int = 3) -> Ticket:
        """Answer a query and open a ticket for its eventual outcome."""
        answer = self.protocol.answer(query, k=k)
        ticket = Ticket(
            query=query,
            answer=answer.text,
            deciding_entry=answer.deciding_entry,
            supporting_entries=answer.supporting_entries,
            born_tick=self.tick_count,
        )
        if ticket.provenance:
            self._pending[ticket.id] = ticket
        self._log(
            "decide",
            ticket=ticket.id,
            query=query,
            silent=is_silent(
                answer.text, answer.deciding_entry, answer.supporting_entries
            ),
            provenance=ticket.provenance,
        )
        return ticket

    def settle(self, ticket_id: str, delta: float, detail: str = "") -> bool:
        """Report the measured outcome for a ticket. Credit flows now.

        ``delta`` is a measurement of a conserved resource, never a
        grade. Returns True when the settlement landed, False when the
        ticket is unknown, already settled, or expired: callers (and
        agents) must be able to tell a real settlement from a dropped
        one. The False path stays a no-op rather than an exception
        because duplicate deliveries are normal in event-driven systems.
        """
        ticket = self._pending.pop(ticket_id, None)
        if ticket is None:
            self._log("settle_dropped", ticket=ticket_id, delta=delta, detail=detail)
            return False

        applied = assign_credit(
            self.store,
            ticket.deciding_entry,
            ticket.supporting_entries,
            delta,
            self.config.resource_scale or 1.0,
            self.config,
            self.tick_count,
        )
        for entry_id, credit in applied:
            if credit < -_DAMAGE_EPSILON:
                self._damaged.add(entry_id)
            self._note(
                entry_id,
                f"tick {self.tick_count}: credit {credit:+.3f} "
                f"(measured delta {delta:+g}{', ' + detail if detail else ''})",
            )

        # Escrow released for THIS ticket: bury what is dead, unless
        # another pending ticket still escrows it. The invariant is that
        # a verdict can never arrive after the execution, and that must
        # hold per ticket, not per settlement.
        still_escrowed = self._escrowed_ids()
        for entry_id in ticket.provenance:
            entry = self.store.get(entry_id)
            if entry is not None and not entry.alive and entry_id not in still_escrowed:
                self.store.bury(entry_id)
                self._note(entry_id, f"buried at tick {self.tick_count} on settle")
        self._log("settle", ticket=ticket.id, delta=delta, detail=detail)
        return True

    def abandon(self, ticket_id: str) -> bool:
        """Release a ticket whose answer was never acted on.

        A decision that led to no action has no outcome to measure;
        abandoning settles it at delta zero so its escrow releases
        instead of pinning entries until expiry. Conservative agents
        should abandon every no-act ticket.
        """
        return self.settle(ticket_id, 0.0, detail="abandoned: not acted on")

    def tick(self, expire_after: int | None = 50) -> dict[str, Any]:
        """Advance one unit of time: expiry, upkeep, consolidation."""
        self.tick_count += 1

        expired = []
        if expire_after is not None:
            expired = [
                t.id
                for t in self._pending.values()
                if self.tick_count - t.born_tick > expire_after
            ]
            for ticket_id in expired:
                self.settle(ticket_id, 0.0, detail="expired unsettled")

        escrowed = self._escrowed_ids()
        dead = self.store.charge_upkeep(protect=escrowed)
        for entry in dead:
            cause = (
                "executed: negative outcomes drained it"
                if entry.id in self._damaged
                else "starved: never earned its upkeep"
            )
            self._note(
                entry.id,
                f"died at tick {self.tick_count} ({cause}; "
                f"uses={entry.uses}, last_used_tick={entry.last_used_cycle})",
            )

        merges = 0
        if (
            self.config.consolidate_every
            and self.tick_count % self.config.consolidate_every == 0
        ):
            merges = consolidate(
                self.store,
                self.tick_count,
                threshold=self.config.merge_threshold,
                exclude=escrowed,
            )

        stats = {
            "tick": self.tick_count,
            "population": len(self.store),
            "deaths": len(dead),
            "merges": merges,
            "pending": len(self._pending),
            "expired": len(expired),
            "total_energy": round(self.store.total_energy(), 3),
        }
        self._log("tick", **stats)
        return stats

    # ------------------------------------------------------------------
    # Persistence: tickets must survive the process that minted them
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        """One file, atomically written: the store plus the ledger state.

        ``MemoryStore.load`` ignores the ledger key, so the file remains
        a valid plain store file for store-only consumers.
        """
        payload = self.store.to_payload()
        payload["ledger"] = {
            "tick_count": self.tick_count,
            "pending": [asdict(t) for t in self._pending.values()],
            "history": {k: list(v) for k, v in self._history.items()},
            "damaged": sorted(self._damaged),
        }
        write_json_atomic(path, payload)

    @classmethod
    def load(
        cls,
        path: str | Path,
        protocol: QueryProtocol | None = None,
        config: SurvivalConfig | None = None,
        resource_scale: float | None = None,
        event_log: str | Path | None = None,
        retriever: Retriever | None = None,
    ) -> Ledger:
        """Restore a ledger (and its store) saved by :meth:`save`.

        A plain store file (no ledger key) loads with fresh ledger
        state, so upgrading from MemoryStore persistence just works.
        """
        payload = json.loads(Path(path).read_text())
        store = MemoryStore.from_payload(payload, retriever=retriever)
        ledger = cls(
            store,
            protocol=protocol,
            config=config,
            resource_scale=resource_scale,
            event_log=event_log,
        )
        state = payload.get("ledger")
        if state:
            ledger.tick_count = int(state.get("tick_count", 0))
            for t in state.get("pending", []):
                ticket = Ticket(**t)
                ledger._pending[ticket.id] = ticket
            ledger._history = {k: list(v) for k, v in state.get("history", {}).items()}
            ledger._damaged = set(state.get("damaged", []))
        return ledger

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def pending(self) -> list[Ticket]:
        return list(self._pending.values())

    def obituary(self, entry_id: str) -> str:
        """Why did this entry die? Answered from the ledger's history."""
        entry = self.store.get(entry_id) or self.store.get_dead(entry_id)
        if entry is None:
            heirs = [
                e
                for e in self.store.alive() + self.store.graveyard()
                if entry_id in e.lineage
            ]
            if heirs:
                return f"{entry_id}: merged into {heirs[0].id} ({heirs[0].question!r})"
            return f"{entry_id}: unknown to this store"

        lines = [
            f"{entry.id} [{entry.kind.value}] {entry.question!r}",
            f"  energy={entry.energy:.3f} uses={entry.uses} alive={entry.alive}",
        ]
        heirs = [
            e
            for e in self.store.alive() + self.store.graveyard()
            if entry.id in e.lineage
        ]
        if heirs:
            lines.append(f"  merged into {heirs[0].id}")
        lines.extend(f"  {event}" for event in self._history.get(entry.id, []))
        if not self._history.get(entry.id) and not entry.alive and not heirs:
            lines.append(
                "  no credited outcomes on record: starved (never earned"
                " enough to cover upkeep)"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------

    def _escrowed_ids(self) -> set[str]:
        return {entry_id for t in self._pending.values() for entry_id in t.provenance}

    def _note(self, entry_id: str, event: str) -> None:
        history = self._history.setdefault(entry_id, [])
        history.append(event)
        if len(history) > _HISTORY_CAP:
            del history[: len(history) - _HISTORY_CAP]

    def _log(self, kind: str, **payload: Any) -> None:
        if self.event_log is None:
            return
        record = {"event": kind, "tick": self.tick_count, **payload}
        with self.event_log.open("a") as f:
            f.write(json.dumps(record) + "\n")
