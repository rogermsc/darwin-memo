"""OpenAI Agents SDK session adapter: lessons next to the transcript.

The SDK's built-in Sessions (``SQLiteSession`` and friends) are
transcript replay: the runner reads the history before a turn and
appends the new items after it. That covers short-term context. The
long-term slot, lessons that persist across sessions and earn or lose
their place by measured outcomes, is vacant. This adapter fills it with
a darwin-memo :class:`~darwin_memo.ledger.Ledger` while remaining a
faithful Session for the transcript part.

:class:`DarwinMemoSession` implements the SDK's ``Session`` protocol by
duck typing: no import of the ``openai-agents`` package, no new
dependencies. The protocol (``agents.memory.session.Session``, a
``@runtime_checkable`` Protocol) requires a ``session_id`` attribute
and four async methods: ``get_items``, ``add_items``, ``pop_item``,
``clear_session``. Per the SDK docs, ``get_items(limit=N)`` returns the
latest N items in chronological order. Transcript items live in one
JSONL file per session id: honest, greppable, and trivially inspected.

The darwin-memo value-add is explicit and opt-in, never wired into the
transcript path: :meth:`DarwinMemoSession.consult` runs ``decide``
against the lesson store and returns rendered lessons for injection,
and :meth:`DarwinMemoSession.settle` reports the measured outcome. The
host app decides outcomes; the adapter never invents deltas. If a
consulted answer is not acted on, call
:meth:`DarwinMemoSession.abandon` so its escrow releases.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..ledger import Ledger
from ..store import MemoryStore

__all__ = ["Consultation", "DarwinMemoSession"]

# The SDK's item type (``agents.items.TResponseInputItem``) is a union
# of TypedDicts in the model input-item format, e.g.
# ``{"role": "user", "content": "Hello"}``. The adapter stores whatever
# JSON-serializable mapping the runner hands it, verbatim.
TResponseInputItem = dict[str, Any]

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


def transcript_filename(session_id: str) -> str:
    """Map a session id to a filesystem-safe JSONL filename.

    Ids that are already safe map to ``<id>.jsonl`` so the directory
    stays greppable. Ids needing sanitization get a short content hash
    appended, so distinct ids can never collide onto one file (for
    example ``team/alpha`` and ``team_alpha``).
    """
    safe = _UNSAFE_CHARS.sub("_", session_id)
    if safe != session_id or not safe:
        digest = hashlib.sha256(session_id.encode()).hexdigest()[:8]
        safe = f"{safe or 'session'}-{digest}"
    return f"{safe}.jsonl"


@dataclass(frozen=True)
class Consultation:
    """One :meth:`DarwinMemoSession.consult` result.

    ``lessons`` is the rendered text to inject into the turn (empty
    when memory was silent: prefer that silence over guessing).
    ``ticket_id`` is what the host settles once the outcome of acting
    on the lessons is measured; it is None when memory was silent,
    because a silent answer opens no ticket.
    """

    ticket_id: str | None
    lessons: str


class DarwinMemoSession:
    """SDK ``Session`` plus an opt-in darwin-memo lesson layer.

    Pass it wherever the SDK takes a session::

        result = await Runner.run(agent, user_input, session=session)

    The transcript side is a faithful protocol implementation backed by
    one JSONL file per session id under ``transcript_dir``. The lesson
    side needs a ledger: pass a constructed :class:`Ledger` (hosts that
    share one lesson store across sessions, which is the point of
    long-term memory), or just ``lesson_path`` and the adapter loads or
    creates one there. When ``lesson_path`` is set, every consult,
    settle, and abandon persists, so open tickets survive the process
    that minted them.

    The adapter never invents deltas. ``settle`` takes the measurement
    the host made (tests passed, bytes freed, dollars saved), exactly
    like every other darwin-memo surface.
    """

    # The SDK protocol also names ``session_settings``; the runner may
    # read it. Typed Any because importing the SDK's SessionSettings
    # would break the dependency-free contract.
    session_settings: Any = None

    def __init__(
        self,
        session_id: str,
        transcript_dir: str | Path,
        ledger: Ledger | None = None,
        lesson_path: str | Path | None = None,
        resource_scale: float | None = None,
    ) -> None:
        self.session_id = session_id
        directory = Path(transcript_dir).expanduser()
        directory.mkdir(parents=True, exist_ok=True)
        self.transcript_path = directory / transcript_filename(session_id)
        self._lock = asyncio.Lock()

        self._lesson_path = Path(lesson_path).expanduser() if lesson_path else None
        if ledger is not None:
            self._ledger: Ledger | None = ledger
        elif self._lesson_path is not None and self._lesson_path.exists():
            self._ledger = Ledger.load(self._lesson_path, resource_scale=resource_scale)
        elif self._lesson_path is not None:
            self._lesson_path.parent.mkdir(parents=True, exist_ok=True)
            self._ledger = Ledger(MemoryStore(), resource_scale=resource_scale)
        else:
            self._ledger = None

    # ------------------------------------------------------------------
    # The SDK Session protocol (transcript replay)
    # ------------------------------------------------------------------

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
        """Retrieve the conversation history for this session.

        With ``limit=None`` every stored item returns. With a limit,
        the latest N items return in chronological order, exactly as
        the SDK protocol specifies: selection is from the tail, the
        list still reads oldest to newest.
        """
        async with self._lock:
            items = await asyncio.to_thread(self._read_items)
        if limit is None:
            return items
        if limit <= 0:
            return []
        return items[-limit:]

    async def add_items(self, items: list[TResponseInputItem]) -> None:
        """Append new items to the conversation history."""
        async with self._lock:
            await asyncio.to_thread(self._append_items, list(items))

    async def pop_item(self) -> TResponseInputItem | None:
        """Remove and return the most recent item; None when empty."""
        async with self._lock:
            return await asyncio.to_thread(self._pop_last)

    async def clear_session(self) -> None:
        """Delete all items for this session (the transcript file)."""
        async with self._lock:
            await asyncio.to_thread(self.transcript_path.unlink, missing_ok=True)

    # ------------------------------------------------------------------
    # The darwin-memo layer (explicit, opt-in, never on the hot path)
    # ------------------------------------------------------------------

    def consult(self, question: str, k: int = 3) -> Consultation:
        """Ask the lesson store before a turn. Opens a ticket.

        Returns the rendered lessons to inject (empty when memory has
        nothing relevant) and the ticket id to settle later. The host
        decides what to do with the lessons and, crucially, measures
        the outcome itself: the adapter never grades anything.
        """
        ledger = self._require_ledger()
        ticket = ledger.decide(question, k=k)
        self._persist(ledger)
        return Consultation(
            ticket_id=ticket.id if ticket.provenance else None,
            lessons=ticket.answer,
        )

    def settle(self, ticket_id: str, delta: float, detail: str = "") -> bool:
        """Report the measured outcome for a consult ticket.

        ``delta`` is a measurement of a conserved resource the host
        made, never a quality grade and never something this adapter
        computes. Returns True when the settlement landed, False when
        the ticket is unknown, already settled, or expired.
        """
        ledger = self._require_ledger()
        landed = ledger.settle(ticket_id, delta, detail)
        self._persist(ledger)
        return landed

    def abandon(self, ticket_id: str) -> bool:
        """Release a ticket whose lessons were never acted on."""
        ledger = self._require_ledger()
        landed = ledger.abandon(ticket_id)
        self._persist(ledger)
        return landed

    # ------------------------------------------------------------------

    def _require_ledger(self) -> Ledger:
        if self._ledger is None:
            raise RuntimeError(
                "this DarwinMemoSession has no lesson store: pass ledger= "
                "or lesson_path= to use consult/settle/abandon"
            )
        return self._ledger

    def _persist(self, ledger: Ledger) -> None:
        # Open tickets must survive the process that minted them, so
        # every lesson operation saves when a path is configured.
        if self._lesson_path is not None:
            ledger.save(self._lesson_path)

    def _read_items(self) -> list[TResponseInputItem]:
        try:
            text = self.transcript_path.read_text()
        except FileNotFoundError:
            return []
        items: list[TResponseInputItem] = [
            json.loads(line) for line in text.splitlines() if line.strip()
        ]
        return items

    def _append_items(self, items: list[TResponseInputItem]) -> None:
        with self.transcript_path.open("a") as f:
            for item in items:
                f.write(json.dumps(item) + "\n")

    def _pop_last(self) -> TResponseInputItem | None:
        items = self._read_items()
        if not items:
            return None
        last = items.pop()
        text = "".join(json.dumps(item) + "\n" for item in items)
        self.transcript_path.write_text(text)
        return last
