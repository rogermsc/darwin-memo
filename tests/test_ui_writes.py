"""The dashboard's write path, and the four checks standing in front of it.

The server was read-only, and the stated reason it needed no authentication
was that there was nothing to authorize. Writes remove that argument, so
each check here is load-bearing: without a guard, a refactor can disarm one
and every test that only exercises the happy path still passes.

Each check is asserted twice -- once that a bad request is refused, once
that the same request succeeds when only that header is corrected -- so a
check that stopped running would show up as a pass on the negative case
that no longer proves anything.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from darwin_memo import Ledger, MemoryEntry, MemoryStore
from darwin_memo.ui import serve


@pytest.fixture
def served(tmp_path: Path):
    """A live dashboard over a store holding one entry and one open ticket."""
    memory = tmp_path / "memory.json"
    store = MemoryStore(upkeep=0.05)
    store.add(
        MemoryEntry(
            question="Are cache files safe to delete?",
            answer="Cache chunk files under cache/ are disposable.",
            sources=["runbook"],
        )
    )
    ledger = Ledger(store, event_log=memory.with_suffix(".events.jsonl"))
    ticket = ledger.decide("Are cache files safe to delete?")
    ledger.save(memory)

    server: ThreadingHTTPServer = serve(memory, 0)
    token: str = server.RequestHandlerClass.args[1]  # type: ignore[attr-defined]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield base, token, memory, ticket.id, store.alive()[0].id
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def post(
    base: str,
    action: str,
    body: dict | None = None,
    *,
    token: str | None = None,
    content_type: str | None = "application/json",
    origin: str | None = None,
    host: str | None = None,
) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{base}/api/{action}",
        data=json.dumps(body or {}).encode(),
        method="POST",
    )
    if content_type:
        request.add_header("Content-Type", content_type)
    if token is not None:
        request.add_header("X-Darwin-Memo-Token", token)
    if origin:
        request.add_header("Origin", origin)
    if host:
        request.add_header("Host", host)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.load(exc)


# ---------------------------------------------------------------- the checks


def test_write_without_the_token_is_refused_and_with_it_lands(served):
    """The token is what a cross-origin script cannot mint: it can only be
    read out of the document, and reading the document is what the origin
    checks stop."""
    base, token, memory, _, _ = served
    before = memory.read_bytes()

    status, body = post(base, "tick")
    assert status == 403, body
    assert memory.read_bytes() == before, "a refused write must not touch the store"

    status, body = post(base, "tick", token=token)
    assert status == 200, body
    assert memory.read_bytes() != before, "the same call with a token must land"


def test_a_stale_token_is_refused(served):
    """A token from a previous process must not work against this one."""
    base, _, _, _, _ = served
    status, _ = post(base, "tick", token="stale-token-from-an-older-server")
    assert status == 403


def test_a_form_content_type_is_refused(served):
    """A form POST is the one cross-origin write a browser sends without a
    preflight, so the JSON content type is what makes a preflight mandatory."""
    base, token, _, _, _ = served
    status, _ = post(
        base, "tick", token=token, content_type="application/x-www-form-urlencoded"
    )
    assert status == 415
    assert post(base, "tick", token=token)[0] == 200


def test_a_foreign_origin_is_refused(served):
    """Another page on localhost must not be able to drive this one."""
    base, token, _, _, _ = served
    assert post(base, "tick", token=token, origin="http://evil.example")[0] == 403
    assert post(base, "tick", token=token, origin="http://127.0.0.1")[0] == 200


def test_a_rebound_host_is_refused(served):
    """DNS rebinding: the browser sends the attacker's hostname in Host,
    which is why this check runs before anything else, reads included."""
    base, token, _, _, _ = served
    assert post(base, "tick", token=token, host="attacker.example")[0] == 421


def test_an_unknown_action_is_not_dispatched(served):
    base, token, _, _, _ = served
    assert post(base, "wipe", token=token)[0] == 404


# ------------------------------------------------------------- the operations


def test_pin_and_unpin_round_trip(served):
    base, token, memory, _, entry_id = served
    assert post(base, "pin", {"id": entry_id}, token=token)[1]["pinned"] is True
    assert Ledger.load(memory).store.get(entry_id).pinned is True
    assert post(base, "unpin", {"id": entry_id}, token=token)[1]["pinned"] is False
    assert Ledger.load(memory).store.get(entry_id).pinned is False


def test_settle_from_the_dashboard_is_marked_operator_entered(served):
    """The one operation that admits human judgment must stay separable
    from a measurement, in the event log and in the per-entry history.
    Everything downstream -- `why`, `audit`, doctor's operator_settled --
    keys off this field."""
    base, token, memory, ticket_id, entry_id = served
    status, body = post(
        base,
        "settle",
        {"ticket_id": ticket_id, "delta": 1200, "detail": "typed"},
        token=token,
    )
    assert status == 200 and body["settled"] is True
    assert body["source"] == "operator"

    logged = [
        json.loads(line)
        for line in memory.with_suffix(".events.jsonl").read_text().splitlines()
    ]
    settles = [event for event in logged if event["event"] == "settle"]
    assert settles and all(event["source"] == "operator" for event in settles)

    notes = Ledger.load(memory).history(entry_id)
    assert any(note.get("source") == "operator" for note in notes)


def test_a_settle_the_ledger_would_reject_is_refused_before_it_gets_there(served):
    """NaN is not a measurement. The ledger already refuses it; the point
    here is that the browser gets a 400 naming the reason rather than a
    silent no-op that looks like success."""
    base, token, _, ticket_id, _ = served
    for delta in (float("nan"), float("inf"), "5", True, None):
        status, _ = post(
            base, "settle", {"ticket_id": ticket_id, "delta": delta}, token=token
        )
        assert status == 400, f"{delta!r} should be refused"


def test_add_requires_both_halves(served):
    base, token, _, _, _ = served
    assert post(base, "add", {"question": "", "answer": "a"}, token=token)[0] == 400
    assert post(base, "add", {"question": "q", "answer": " "}, token=token)[0] == 400
    status, body = post(base, "add", {"question": "q", "answer": "a"}, token=token)
    assert status == 200 and body["id"]


def test_abandon_releases_the_ticket(served):
    base, token, memory, ticket_id, _ = served
    assert post(base, "abandon", {"ticket_id": ticket_id}, token=token)[1]["released"]
    assert Ledger.load(memory).pending() == []


def test_a_get_is_still_a_get(served):
    """Reads must not have picked up a token requirement along the way."""
    base, _, _, _, _ = served
    with urllib.request.urlopen(f"{base}/api/state", timeout=10) as response:
        assert response.status == 200
        assert json.load(response)["counts"]["alive"] == 1
