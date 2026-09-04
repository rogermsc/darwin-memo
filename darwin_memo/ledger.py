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

import itertools
import json
import math
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .consolidate import consolidate
from .protocol import QueryProtocol
from .retrieval import Retriever
from .store import MemoryStore, store_lock, write_json_atomic
from .survival import SurvivalConfig, advance_lifecycle, assign_credit, is_silent
from .types import EntryKind, MemoryEntry, utc_now_iso

_HISTORY_CAP = 100  # per-entry events kept in memory; the JSONL log is full
_DAMAGE_EPSILON = 1e-9
# Net-positive local settlements an import owes before it may decide.
DEFAULT_PROBATION = 3
EVENT_LOG_MAX_BYTES = 10 * 1024 * 1024  # rotate the JSONL log at this size
EVENT_LOG_KEEP = 3  # rotated files retained alongside the live one


def event_log_paths(path: Path, keep: int = EVENT_LOG_KEEP) -> list[Path]:
    """Every path the event log may occupy after rotation, oldest first.

    Rotation shifts the live file to ``NAME.1`` and bumps each older
    file one suffix up, logrotate style, so ``NAME.keep`` is the oldest
    survivor and the live file is always the newest. Readers that walk
    this list in order see the full log in append order.
    """
    return [path.with_name(f"{path.name}.{i}") for i in range(keep, 0, -1)] + [path]


def note_text(event: str | dict[str, Any]) -> str:
    """Render one history note; saves from older versions stored strings."""
    if isinstance(event, str):
        return event
    return str(event.get("text", event))


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
        event_log_max_bytes: int = EVENT_LOG_MAX_BYTES,
        event_log_keep: int = EVENT_LOG_KEEP,
    ) -> None:
        self.store = store
        self.config = config or SurvivalConfig()
        if resource_scale is not None:
            self.config.resource_scale = resource_scale
        if self.config.resource_scale is None:
            self.config.resource_scale = 1.0
        # The default protocol flags conflicting advice at the same
        # similarity floor this ledger consolidates at, so "near
        # duplicate" cannot mean two different things in one ledger
        # (configs over cosine retrievers raise merge_threshold, and
        # conflict surfacing must follow).
        self.protocol = protocol or QueryProtocol(
            store, conflict_threshold=self.config.merge_threshold
        )
        self.event_log = Path(event_log) if event_log else None
        self.event_log_max_bytes = event_log_max_bytes
        self.event_log_keep = event_log_keep
        self.tick_count = 0
        self._pending: dict[str, Ticket] = {}
        self._history: dict[str, list[str | dict[str, Any]]] = {}
        self._damaged: set[str] = set()

    # ------------------------------------------------------------------
    # The three moments
    # ------------------------------------------------------------------

    def decide(
        self,
        query: str,
        k: int = 3,
        *,
        half_life: float | None = None,
        kind: str | None = None,
        source: str | None = None,
    ) -> Ticket:
        """Answer a query and open a ticket for its eventual outcome.

        The ticket carries the consult-surface rendering of the answer:
        entry text plus its age line, or a dated conflict block when
        near-duplicate entries disagree (see ``darwin_memo.temporal``).
        ``half_life`` opts into recency-weighted ranking anchored at
        this ledger's tick count; ``kind`` and ``source`` filter the
        candidate entries. All three are pure retrieval concerns:
        escrow, credit, and settlement never see them.

        Probation is enforced inside the protocol (local retrieval
        never elects a probationary decider; LLM mode demotes or
        withholds at the citation parse site, see
        ``QueryProtocol._enforce_probation``), so every protocol
        consumer inherits it. This method re-checks anyway: a custom
        protocol that overrides ``answer`` bypasses the parse site,
        and a ticket must never carry a probationary decider. When
        every consulted entry is probationary the answer is withheld
        entirely: imported knowledge alone never drives a decision
        and never earns from its own answer.
        """
        answer = self.protocol.answer(
            query,
            k=k,
            half_life=half_life,
            now_cycle=self.tick_count,
            kind=kind,
            source=source,
        )
        text = answer.annotated_text or answer.text
        deciding = answer.deciding_entry
        supporting = list(answer.supporting_entries)
        if deciding is not None:
            decider = self.store.get(deciding)
            if decider is not None and not decider.may_decide:
                supporting.append(deciding)
                deciding = None
        withheld: list[str] = []
        if deciding is None and supporting:
            on_probation = [
                entry_id
                for entry_id in supporting
                if (e := self.store.get(entry_id)) is not None and not e.may_decide
            ]
            if len(on_probation) == len(supporting):
                withheld = supporting
                supporting = []
                text = ""
        ticket = Ticket(
            query=query,
            answer=text,
            deciding_entry=deciding,
            supporting_entries=supporting,
            born_tick=self.tick_count,
        )
        if ticket.provenance:
            self._pending[ticket.id] = ticket
        extra: dict[str, Any] = {"withheld": withheld} if withheld else {}
        self._log(
            "decide",
            ticket=ticket.id,
            query=query,
            silent=is_silent(text, deciding, supporting),
            provenance=ticket.provenance,
            **extra,
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
        if not math.isfinite(delta):
            # A NaN or infinity is not a measurement. Left unguarded it would
            # bypass the tanh energy cap (min(cap, nan) is nan) and write an
            # invalid JSON token into the event log, breaking the audit and the
            # dashboard. Reject it as a no-op, like an unknown ticket, and keep
            # the log valid by not echoing the value.
            self._log("settle_rejected", ticket=ticket_id, detail="non-finite delta")
            return False
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
                event="settle",
                ticket=ticket.id,
                credit=round(credit, 6),
                delta=delta,
                detail=detail,
            )
        denied: set[str] = set()
        for entry_id, event in advance_lifecycle(
            self.store, applied, delta, ticket.deciding_entry
        ):
            if event == "admission_denied":
                denied.add(entry_id)
            self._note_lifecycle(entry_id, event, delta, ticket)

        # Escrow released for THIS ticket: bury what is dead, unless
        # another pending ticket still escrows it. The invariant is that
        # a verdict can never arrive after the execution, and that must
        # hold per ticket, not per settlement.
        still_escrowed = self._escrowed_ids()
        buried: list[str] = []
        for entry_id in ticket.provenance:
            entry = self.store.get(entry_id)
            if entry is None:
                continue
            if entry.pinned:
                # Pin means nothing removes this. Settlement damage may
                # drain a pinned balance below zero, but the sweep floors
                # it at zero exactly as charge_upkeep does, instead of
                # burying: a pinned entry survives bad outcomes the same
                # way it survives starvation, until a human unpins it.
                entry.energy = max(entry.energy, 0.0)
                continue
            # A denied juvenile decider has already received its terminal
            # verdict, so escrow no longer protects it. Without the `denied`
            # override a second pending ticket keeps it un-buried while
            # advance_lifecycle has already zeroed its juvenile counter, and
            # that ticket's next positive settle re-admits it at full deciding
            # credit -- defeating the admission control precisely for the entry
            # it targets.
            if not entry.alive and (
                entry_id not in still_escrowed or entry_id in denied
            ):
                self.store.bury(entry_id)
                buried.append(entry_id)
                self._note(
                    entry_id,
                    f"buried at tick {self.tick_count} on settle",
                    event="buried",
                    via="settle",
                    cause="executed" if entry_id in self._damaged else "starved",
                )
        self._log(
            "settle",
            ticket=ticket.id,
            delta=delta,
            detail=detail,
            applied=[{"entry": e, "credit": round(c, 6)} for e, c in applied],
            buried=buried,
        )
        return True

    def abandon(self, ticket_id: str) -> bool:
        """Release a ticket whose answer was never acted on.

        A decision that led to no action has no outcome to measure;
        abandoning settles it at delta zero so its escrow releases
        instead of pinning entries until expiry. Conservative agents
        should abandon every no-act ticket.
        """
        return self.settle(ticket_id, 0.0, detail="abandoned: not acted on")

    def add(self, question: str, answer: str, source: str = "agent") -> MemoryEntry:
        """Write a new entry through the ledger, so the event is logged.

        The entry starts at spawn energy and must earn its keep from
        here: adding is cheap, surviving is not. When admission gating
        is on (``config.admission_window`` > 0) the entry also starts
        juvenile: its deciding credit is capped at the supporting share
        and one negative deciding outcome buries it on the spot, which
        bounds the cold-start damage a wrong young lesson can cause.
        """
        juvenile = max(0, self.config.admission_window)
        entry = self.store.add(
            MemoryEntry(
                question=question,
                answer=answer,
                kind=EntryKind.EXPERIENCE,
                sources=[source],
                born_cycle=self.tick_count,
                juvenile=juvenile,
            )
        )
        window = f", juvenile window {juvenile}" if juvenile else ""
        self._note(
            entry.id,
            f"born at tick {self.tick_count} "
            f"(source {source}, stake {entry.energy:g}{window})",
            event="birth",
            source=source,
            stake=entry.energy,
        )
        self._log(
            "add", entry=entry.id, question=question, source=source, stake=entry.energy
        )
        return entry

    def import_entries(
        self,
        entries: Iterable[MemoryEntry],
        source: str,
        probation: int = DEFAULT_PROBATION,
    ) -> list[MemoryEntry]:
        """Copy foreign entries in on probation: they re-earn locally.

        Each living foreign entry arrives as a fresh local entry at
        spawn energy (a foreign balance is foreign-earned and does not
        transfer), keeps its id and text, and carries provenance:
        ``imported_from`` is the caller's source label and
        ``imported_at`` the import time. While ``probation`` > 0 the
        entry cannot be the deciding entry of any ticket; it rides
        along as support, settles normally when co-consulted, and
        graduates after ``probation`` net-positive settlements.
        ``probation=0`` imports at full status, which is the bootstrap
        path for a source you trust completely.

        Import is idempotent on ids: an id already present in this
        store, living or buried, is skipped, so re-importing the same
        source neither duplicates entries nor resurrects ones that
        died here.
        """
        stamp = utc_now_iso()
        imported: list[MemoryEntry] = []
        for foreign in entries:
            if not foreign.alive:
                continue
            if (
                self.store.get(foreign.id) is not None
                or self.store.get_dead(foreign.id) is not None
            ):
                continue
            entry = self.store.add(
                MemoryEntry(
                    question=foreign.question,
                    answer=foreign.answer,
                    kind=foreign.kind,
                    sources=list(foreign.sources),
                    born_cycle=self.tick_count,
                    probation=max(0, probation),
                    imported_from=source,
                    imported_at=stamp,
                    id=foreign.id,
                )
            )
            imported.append(entry)
            self._note(
                entry.id,
                f"imported at tick {self.tick_count} from {source} "
                f"(probation {entry.probation}, stake {entry.energy:g})",
                event="import",
                source=source,
                probation=entry.probation,
                stake=entry.energy,
            )
            self._log(
                "import", entry=entry.id, source=source, probation=entry.probation
            )
        return imported

    def pin(self, entry_id: str) -> bool:
        """Protect a living entry from starvation culling and merges.

        A pinned entry still pays upkeep but its balance floors at zero
        instead of triggering burial, consolidation never merges it
        away, and ``forget`` refuses it until unpinned. For
        rare-but-critical knowledge whose payoff cadence is longer than
        the starvation horizon: the fire-extinguisher lesson that pays
        off once a year must survive the wait. Pinning opts the entry
        out of selection's kill switch, so pin sparingly
        (docs/threat-model.md). Returns False when the id is not alive.
        """
        entry = self.store.get(entry_id)
        if entry is None:
            return False
        if not entry.pinned:
            entry.pinned = True
            self._note(
                entry_id,
                f"pinned at tick {self.tick_count}: culling and merges disabled",
                event="pinned",
            )
            self._log("pin", entry=entry_id)
        return True

    def unpin(self, entry_id: str) -> bool:
        """Remove pin protection; survival pressure resumes next tick."""
        entry = self.store.get(entry_id)
        if entry is None:
            return False
        if entry.pinned:
            entry.pinned = False
            self._note(
                entry_id,
                f"unpinned at tick {self.tick_count}: survival pressure resumes",
                event="unpinned",
            )
            self._log("unpin", entry=entry_id)
        return True

    def forget(self, entry_id: str) -> str:
        """Bury an entry, honoring escrow. Returns the outcome.

        ``"buried"`` on success, ``"missing"`` when the entry is not
        alive, and ``"escrowed"`` when a pending ticket names it:
        burying an escrowed entry would let a later settle report
        success while crediting a corpse, violating the invariant that
        a verdict can never arrive after the execution. ``"pinned"``
        when the entry is pinned: pin means nothing removes this, so
        an explicit forget requires an explicit unpin first. This is
        the one bury path callers should use; ``store.bury`` is the
        raw mechanism and enforces nothing.
        """
        if entry_id in self._escrowed_ids():
            self._log("forget_refused", entry=entry_id, reason="escrowed")
            return "escrowed"
        entry = self.store.get(entry_id)
        if entry is None:
            return "missing"
        if entry.pinned:
            self._log("forget_refused", entry=entry_id, reason="pinned")
            return "pinned"
        self.store.bury(entry_id)
        self._note(
            entry_id,
            f"buried at tick {self.tick_count} by forget",
            event="buried",
            via="forget",
            cause="forgotten",
        )
        self._log("forget", entry=entry_id)
        return "buried"

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
            cause = "executed" if entry.id in self._damaged else "starved"
            reason = (
                "executed: negative outcomes drained it"
                if cause == "executed"
                else "starved: never earned its upkeep"
            )
            self._note(
                entry.id,
                f"died at tick {self.tick_count} ({reason}; "
                f"uses={entry.uses}, last_used_tick={entry.last_used_cycle})",
                event="death",
                cause=cause,
                uses=entry.uses,
                last_used_tick=entry.last_used_cycle,
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
                source_policy=self.config.merge_source_policy,
            )

        stats = {
            "tick": self.tick_count,
            "population": len(self.store),
            "deaths": len(dead),
            "merges": merges,
            "pending": len(self._pending),
            "expired": len(expired),
            "total_energy": round(self.store.total_energy(), 3),
            "upkeep_charged": self.store.last_upkeep_charged,
        }
        self._log("tick", **stats, dead_entries=[e.id for e in dead])
        return stats

    # ------------------------------------------------------------------
    # Persistence: tickets must survive the process that minted them
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        """One file, atomically written: the store plus the ledger state.

        ``MemoryStore.load`` ignores the ledger key, so the file remains
        a valid plain store file for store-only consumers. The write
        holds the sidecar advisory lock: an overlapping save or load on
        the same file raises ``StoreLockedError`` instead of silently
        clobbering (see :func:`darwin_memo.store.store_lock`).
        """
        payload = self.store.to_payload()
        payload["ledger"] = {
            "tick_count": self.tick_count,
            "pending": [asdict(t) for t in self._pending.values()],
            "history": {k: list(v) for k, v in self._history.items()},
            "damaged": sorted(self._damaged),
        }
        with store_lock(path):
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
        with store_lock(path):
            raw = Path(path).read_text()
        try:
            payload = json.loads(raw)
            store = MemoryStore.from_payload(payload, retriever=retriever)
        except (json.JSONDecodeError, KeyError, TypeError, AttributeError) as exc:
            # AttributeError covers a structurally-wrong-but-valid-JSON store
            # (e.g. {"config": null} -> null.items() in from_payload); without
            # it the raw traceback would escape the fail-closed base-store
            # abstain in settle-ci, which only catches ValueError.
            raise ValueError(f"{path} is not a valid darwin-memo store: {exc}") from exc
        ledger = cls(
            store,
            protocol=protocol,
            config=config,
            resource_scale=resource_scale,
            event_log=event_log,
        )
        state = payload.get("ledger")
        if isinstance(state, dict):
            # The whole ledger block is attacker-committed and unreviewed in the
            # CI lesson store, so a malformed CONTAINER -- not just one bad
            # ticket -- must degrade to dropped fields, never a traceback that
            # bricks every future settle. Each field is guarded the way one bad
            # ticket already is below, and the flaky sidecar already is in
            # load_flips. Anything unparseable falls back to the empty default
            # __init__ set.
            try:
                ledger.tick_count = int(state.get("tick_count", 0))
            except (TypeError, ValueError):
                ledger.tick_count = 0
            pending = state.get("pending", [])
            for t in pending if isinstance(pending, list) else []:
                try:
                    ticket = Ticket(**t)
                except TypeError:
                    # A structurally-invalid committed ticket is dropped, not
                    # fatal: in the CI lesson store the PR being measured
                    # commits this file and nobody reviews it, so one bad ticket
                    # must not brick every future load. Mirrors load_flips.
                    continue
                ledger._pending[ticket.id] = ticket
            history = state.get("history", {})
            if isinstance(history, dict):
                ledger._history = {
                    k: list(v)
                    for k, v in history.items()
                    if isinstance(v, (list, tuple))
                }
            damaged = state.get("damaged", [])
            if isinstance(damaged, (list, tuple, set)):
                ledger._damaged = set(damaged)
        return ledger

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------

    def pending(self) -> list[Ticket]:
        return list(self._pending.values())

    def history(self, entry_id: str) -> list[str | dict[str, Any]]:
        """Per-entry history notes, oldest first, capped at _HISTORY_CAP.

        New notes are dicts (tick, ts, text, plus structured fields per
        event); notes persisted by older versions are plain strings.
        Render either with :func:`note_text`.
        """
        return list(self._history.get(entry_id, []))

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
        lines.extend(f"  {note_text(event)}" for event in self.history(entry.id))
        if not self._history.get(entry.id) and not entry.alive and not heirs:
            lines.append(
                "  no credited outcomes on record: starved (never earned"
                " enough to cover upkeep)"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------

    def _escrowed_ids(self) -> set[str]:
        return {entry_id for t in self._pending.values() for entry_id in t.provenance}

    def _note_lifecycle(
        self, entry_id: str, event: str, delta: float, ticket: Ticket
    ) -> None:
        """Narrate one lifecycle event from :func:`advance_lifecycle`.

        The arithmetic lives in ``darwin_memo.survival`` so the loop
        advances the same counters; what is ledger-specific is the
        history note, the event log line, and marking a denied entry
        damaged so the settle sweep and the obituary call it executed.
        """
        if event == "graduated":
            self._note(
                entry_id,
                f"graduated from probation at tick {self.tick_count}: "
                "may decide from here",
                event="graduated",
                lifecycle="probation",
            )
            self._log("graduate", entry=entry_id, lifecycle="probation")
        elif event == "admitted":
            self._note(
                entry_id,
                f"admitted at tick {self.tick_count}: juvenile window "
                "complete, full deciding credit from here",
                event="graduated",
                lifecycle="admission",
            )
            self._log("graduate", entry=entry_id, lifecycle="admission")
        elif event == "admission_denied":
            self._damaged.add(entry_id)
            self._note(
                entry_id,
                f"admission denied at tick {self.tick_count}: negative "
                f"outcome ({delta:+g}) while deciding inside the "
                "juvenile window",
                event="admission_denied",
                delta=delta,
                ticket=ticket.id,
            )
            self._log("admission_denied", entry=entry_id, delta=delta)

    def _note(self, entry_id: str, text: str, **data: Any) -> None:
        history = self._history.setdefault(entry_id, [])
        history.append(
            {"tick": self.tick_count, "ts": utc_now_iso(), "text": text, **data}
        )
        if len(history) > _HISTORY_CAP:
            del history[: len(history) - _HISTORY_CAP]

    def _log(self, kind: str, **payload: Any) -> None:
        if self.event_log is None:
            return
        record = {
            "event": kind,
            "tick": self.tick_count,
            "ts": utc_now_iso(),
            **payload,
        }
        self._rotate_event_log()
        with self.event_log.open("a") as f:
            f.write(json.dumps(record) + "\n")

    def _rotate_event_log(self) -> None:
        """Shift a full live log one suffix up before the next append.

        Rotation runs when the live file has reached the byte threshold,
        so one file can overshoot by at most a single record. The oldest
        rotated file beyond ``event_log_keep`` falls off the end. Audit
        readers walk :func:`event_log_paths` and never notice.
        """
        log = self.event_log
        if log is None or self.event_log_max_bytes <= 0 or self.event_log_keep <= 0:
            return
        try:
            if log.stat().st_size < self.event_log_max_bytes:
                return
        except FileNotFoundError:
            return
        paths = event_log_paths(log, keep=self.event_log_keep)
        paths[0].unlink(missing_ok=True)
        for older, newer in itertools.pairwise(paths):
            if newer.exists():
                newer.rename(older)
