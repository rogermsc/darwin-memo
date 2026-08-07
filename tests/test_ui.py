"""The local dashboard server: read-only, loopback-only, JSON over observe."""

import json
import os
import threading
import urllib.error
import urllib.request

import pytest

from darwin_memo import Ledger, MemoryEntry, MemoryStore
from darwin_memo.ui import serve, state


@pytest.fixture
def served(tmp_path):
    memory = tmp_path / "memory.json"
    store = MemoryStore(upkeep=0.05)
    store.add(
        MemoryEntry(
            question="What about stale feature flags?",
            answer="Stale feature flags are redundant and safe to remove.",
            sources=["runbook"],
        )
    )
    ledger = Ledger(
        store, resource_scale=1.0, event_log=memory.with_suffix(".events.jsonl")
    )
    ticket = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
    ledger.tick()
    ledger.save(memory)

    server = serve(memory, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", memory, ticket
    server.shutdown()
    server.server_close()


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, json.loads(response.read())


def test_state_endpoint_carries_every_panel(served):
    base, _, _ = served
    status, payload = _get(f"{base}/api/state")
    assert status == 200
    assert set(payload) >= {
        "tick",
        "upkeep",
        "counts",
        "total_energy",
        "doctor",
        "timeline",
        "economics",
        "entries",
        "graveyard",
        "pending",
    }
    assert payload["entries"][0]["ticks_to_starvation"] > 0


def test_entry_endpoint_returns_a_life_and_404s_on_nonsense(served):
    base, _, ticket = served
    status, life = _get(f"{base}/api/entry/{ticket.deciding_entry}")
    assert status == 200
    assert life["id"] == ticket.deciding_entry
    with pytest.raises(urllib.error.HTTPError) as caught:
        _get(f"{base}/api/entry/not-a-real-id")
    assert caught.value.code == 404


def test_static_route_refuses_to_escape_the_bundle(served):
    base, _, _ = served
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{base}/../../../etc/passwd", timeout=5)
    assert caught.value.code == 404
    # /etc/passwd doesn't exist at this repo's bundle depth, so a missing
    # containment check would still 404 it via the not-found branch and
    # mask the hole. pyproject.toml DOES exist three levels up (the repo
    # root) -- this is the case that actually discriminates the check.
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{base}/../../../pyproject.toml", timeout=5)
    assert caught.value.code == 404, (
        "pyproject.toml really exists three levels above the bundle; a "
        "missing containment check serves it with a 200"
    )


def test_serve_refuses_a_non_loopback_host(tmp_path):
    memory = tmp_path / "memory.json"
    MemoryStore().save(memory)
    with pytest.raises(ValueError, match="loopback"):
        serve(memory, port=0, host="0.0.0.0")


def test_state_is_read_only(tmp_path):
    memory = tmp_path / "memory.json"
    store = MemoryStore(upkeep=0.05)
    store.add(MemoryEntry(question="q", answer="a", sources=["runbook"]))
    Ledger(store).save(memory)
    before = memory.read_bytes()
    state(memory)
    assert memory.read_bytes() == before, "the dashboard must never write"


def test_state_endpoint_handles_concurrent_requests(served):
    """ThreadingHTTPServer + a per-request Ledger.load() is a self-collision:
    store_lock() is fcntl LOCK_EX|LOCK_NB, which raises StoreLockedError on
    contention rather than blocking, and flock contends across threads in
    the same process too (it is keyed on the open file description). A
    browser opens /api/state and /api/events at once, so this must not
    500 the dashboard on itself. Threads are all started before any is
    joined, so the requests genuinely overlap rather than queuing up.
    """
    base, _, _ = served
    results: list[int] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def hit() -> None:
        try:
            status, _ = _get(f"{base}/api/state")
        except BaseException as exc:
            with lock:
                errors.append(exc)
        else:
            with lock:
                results.append(status)

    threads = [threading.Thread(target=hit) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, errors
    assert results == [200] * 16


def _served_base(memory):
    """Start a server for a memory file this test builds by hand (not via
    the ``served`` fixture, which needs a working store to seed)."""
    server = serve(memory, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_state_endpoint_answers_with_a_status_on_corrupt_json(tmp_path):
    memory = tmp_path / "memory.json"
    memory.write_text("{not valid json")
    server, base = _served_base(memory)
    try:
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{base}/api/state", timeout=5)
        assert caught.value.code == 500, "must answer, not drop the connection"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
def test_state_endpoint_answers_with_a_status_on_unreadable_file(tmp_path):
    memory = tmp_path / "memory.json"
    MemoryStore().save(memory)
    memory.chmod(0o000)
    server, base = _served_base(memory)
    try:
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{base}/api/state", timeout=5)
        assert caught.value.code == 500, "must answer, not drop the connection"
    finally:
        server.shutdown()
        server.server_close()
        memory.chmod(0o644)  # let tmp_path clean up after itself
