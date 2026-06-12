"""The OpenAI Agents SDK session adapter: protocol shape, lessons layer."""

from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, Protocol, runtime_checkable

import pytest

from darwin_memo import Ledger
from darwin_memo.integrations.openai_agents import (
    Consultation,
    DarwinMemoSession,
    transcript_filename,
)


@runtime_checkable
class _SdkSession(Protocol):
    """Mirror of ``agents.memory.session.Session`` from the live docs.

    The adapter must satisfy this by duck typing, since it never
    imports the SDK. Same members, same async-ness, same signatures.
    """

    session_id: str
    session_settings: Any

    async def get_items(self, limit: int | None = None) -> list[dict[str, Any]]: ...

    async def add_items(self, items: list[dict[str, Any]]) -> None: ...

    async def pop_item(self) -> dict[str, Any] | None: ...

    async def clear_session(self) -> None: ...


def item(role: str, content: str) -> dict[str, Any]:
    return {"role": role, "content": content}


async def fake_runner_turn(
    session: DarwinMemoSession, user_input: str, reply: str
) -> list[dict[str, Any]]:
    """What the SDK runner does per turn: read history, append new items."""
    history = await session.get_items()
    await session.add_items([item("user", user_input), item("assistant", reply)])
    return history


def test_adapter_satisfies_the_session_protocol(tmp_path):
    session = DarwinMemoSession("shape-check", transcript_dir=tmp_path)
    assert isinstance(session, _SdkSession)
    for name in ("get_items", "add_items", "pop_item", "clear_session"):
        assert inspect.iscoroutinefunction(getattr(session, name)), name


def test_fake_consumer_get_add_pop_clear(tmp_path):
    session = DarwinMemoSession("conv-1", transcript_dir=tmp_path)

    async def scenario() -> None:
        assert await fake_runner_turn(session, "hi", "hello") == []
        second = await fake_runner_turn(session, "status?", "all green")
        assert [i["content"] for i in second] == ["hi", "hello"]

        popped = await session.pop_item()
        assert popped == item("assistant", "all green")
        assert len(await session.get_items()) == 3

        await session.clear_session()
        assert await session.get_items() == []
        assert await session.pop_item() is None

    asyncio.run(scenario())


def test_get_items_limit_returns_latest_n_in_chronological_order(tmp_path):
    session = DarwinMemoSession("conv-limit", transcript_dir=tmp_path)

    async def scenario() -> None:
        await session.add_items([item("user", str(i)) for i in range(5)])
        # The docs say: latest N items, still in chronological order.
        assert [i["content"] for i in await session.get_items(limit=2)] == ["3", "4"]
        assert len(await session.get_items(limit=99)) == 5
        # limit=0 asks for the latest zero items, never the whole list.
        assert await session.get_items(limit=0) == []

    asyncio.run(scenario())


def test_sessions_are_isolated_by_session_id(tmp_path):
    a = DarwinMemoSession("agent-a", transcript_dir=tmp_path)
    b = DarwinMemoSession("agent-b", transcript_dir=tmp_path)

    async def scenario() -> None:
        await a.add_items([item("user", "only in a")])
        await b.add_items([item("user", "only in b")])
        assert [i["content"] for i in await a.get_items()] == ["only in a"]
        assert [i["content"] for i in await b.get_items()] == ["only in b"]

    asyncio.run(scenario())
    assert a.transcript_path != b.transcript_path


def test_transcript_file_is_honest_jsonl(tmp_path):
    session = DarwinMemoSession("greppable", transcript_dir=tmp_path)
    asyncio.run(session.add_items([item("user", "find me with grep")]))
    lines = session.transcript_path.read_text().splitlines()
    assert json.loads(lines[0]) == item("user", "find me with grep")


def test_unsafe_session_ids_cannot_collide():
    slashed = transcript_filename("team/alpha")
    underscored = transcript_filename("team_alpha")
    assert slashed != underscored
    assert "/" not in slashed
    assert transcript_filename("team_alpha") == "team_alpha.jsonl"
    assert transcript_filename("") != ".jsonl"


def test_concurrent_add_items_all_land(tmp_path):
    session = DarwinMemoSession("concurrent", transcript_dir=tmp_path)

    async def scenario() -> None:
        await asyncio.gather(
            *(session.add_items([item("user", str(i))]) for i in range(8))
        )
        items = await session.get_items()
        assert sorted(i["content"] for i in items) == sorted(str(i) for i in range(8))

    asyncio.run(scenario())


def test_consult_settle_roundtrip(tmp_path, store_factory):
    lesson_path = tmp_path / "lessons.json"
    ledger = Ledger(store_factory(), resource_scale=2.0)
    session = DarwinMemoSession(
        "support", transcript_dir=tmp_path, ledger=ledger, lesson_path=lesson_path
    )

    consultation = session.consult("Are stale feature flags safe to remove?")
    assert isinstance(consultation, Consultation)
    assert "safe to remove" in consultation.lessons
    assert consultation.ticket_id is not None
    before = {e.id: e.energy for e in ledger.store.alive()}

    # The HOST measured the outcome; the adapter only carries it.
    assert session.settle(consultation.ticket_id, delta=2.0, detail="3 flags gone")
    assert any(e.energy > before[e.id] for e in ledger.store.alive())
    # Settling twice reports the drop instead of pretending it landed.
    assert not session.settle(consultation.ticket_id, delta=2.0)


def test_open_tickets_survive_the_process(tmp_path, store_factory):
    lesson_path = tmp_path / "lessons.json"
    ledger = Ledger(store_factory(), resource_scale=2.0)
    session = DarwinMemoSession(
        "run-1", transcript_dir=tmp_path, ledger=ledger, lesson_path=lesson_path
    )
    consultation = session.consult("Are stale feature flags safe to remove?")
    assert consultation.ticket_id is not None

    # A fresh session in a new process loads the same store and can
    # settle the ticket the old one opened.
    later = DarwinMemoSession("run-2", transcript_dir=tmp_path, lesson_path=lesson_path)
    assert later.settle(consultation.ticket_id, delta=1.0)


def test_abandon_releases_unacted_tickets(tmp_path, store_factory):
    session = DarwinMemoSession(
        "cautious",
        transcript_dir=tmp_path,
        ledger=Ledger(store_factory(), resource_scale=2.0),
    )
    consultation = session.consult("Are stale feature flags safe to remove?")
    assert consultation.ticket_id is not None
    assert session.abandon(consultation.ticket_id)
    assert not session.abandon(consultation.ticket_id)


def test_consult_is_silent_on_an_empty_store(tmp_path):
    session = DarwinMemoSession(
        "fresh", transcript_dir=tmp_path, lesson_path=tmp_path / "lessons.json"
    )
    consultation = session.consult("anything at all?")
    assert consultation.lessons == ""
    assert consultation.ticket_id is None


def test_lesson_methods_require_a_ledger(tmp_path):
    session = DarwinMemoSession("transcript-only", transcript_dir=tmp_path)
    with pytest.raises(RuntimeError, match="no lesson store"):
        session.consult("anything?")
    with pytest.raises(RuntimeError, match="no lesson store"):
        session.settle("nope", 1.0)
