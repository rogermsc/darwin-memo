"""The local dashboard server: read-only, loopback-only, JSON over observe."""

import http.client
import json
import os
import threading
import urllib.error
import urllib.parse
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


@pytest.fixture
def served_with_bundle(tmp_path, monkeypatch, served):
    """A stub bundle so static routing is exercised for real.

    Without a built bundle every non-index route 404s regardless of the
    containment check, which is exactly what made the traversal test
    decorative. ``served`` already started the server thread, but
    ``_static`` reads ``BUNDLE`` from module globals on every call (it's
    never captured into a local or a default arg), so patching it here,
    after the thread is already running, still takes effect on the next
    request.
    """
    bundle = tmp_path / "bundle"
    (bundle / "assets").mkdir(parents=True)
    (bundle / "index.html").write_text("<!doctype html><title>stub</title>")
    (bundle / "assets" / "index-abc123.js").write_text("export default 1;\n")
    # A file that genuinely exists one level above the bundle. Whether
    # "/../../../pyproject.toml" happens to resolve onto a real file
    # depends on where pytest happens to put tmp_path -- it does NOT
    # reach this repo's actual pyproject.toml once BUNDLE is patched to
    # a tmp_path location, so that assertion alone can't be trusted to
    # discriminate here. This sibling file is real and adjacent by
    # construction, so escaping to it is unambiguous either way.
    (tmp_path / "secret.txt").write_text("do not serve me")
    monkeypatch.setattr("darwin_memo.ui.BUNDLE", bundle)
    return served


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.status, json.loads(response.read())


def _raw_get(base, path, host_header):
    """A GET with an explicit, caller-controlled Host header.

    ``urllib.request`` derives Host from the URL and offers no clean way
    to override it, which is exactly the header this must control: the
    socket still connects to 127.0.0.1 like every other test in this
    file (DNS rebinding is a Host-header attack, not a network-origin
    one), only the header lies.
    """
    parsed = urllib.parse.urlsplit(base)
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=5)
    try:
        conn.putrequest("GET", path, skip_host=True)
        conn.putheader("Host", host_header)
        conn.endheaders()
        response = conn.getresponse()
        return response.status, response.read()
    finally:
        conn.close()


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


def test_events_endpoint_returns_a_bounded_window(served):
    """I-4: zero prior coverage of the _events handler at all. The
    server-side contract EventStream.tsx depends on: 200, an "events"
    key, a list, bounded by `last`."""
    base, _, _ = served
    status, payload = _get(f"{base}/api/events?last=5")
    assert status == 200
    assert isinstance(payload["events"], list)
    assert 0 < len(payload["events"]) <= 5
    assert {"event"} <= set(payload["events"][0])


def test_events_endpoint_defaults_without_a_last_param(served):
    base, _, _ = served
    status, payload = _get(f"{base}/api/events")
    assert status == 200
    assert len(payload["events"]) > 0


def test_events_endpoint_does_not_500_on_a_non_numeric_last(served):
    """`int(last)` raises ValueError on garbage input; the handler must
    fall back rather than 500 the dashboard on a malformed query string."""
    base, _, _ = served
    status, payload = _get(f"{base}/api/events?last=notanumber")
    assert status == 200
    assert isinstance(payload["events"], list)


def test_static_route_refuses_to_escape_the_bundle(tmp_path, monkeypatch, served):
    """No-bundle behaviour, asserted regardless of whether this checkout
    happens to have a built frontend under darwin_memo/data/ui/ -- BUNDLE
    is monkeypatched to a path that does not exist, the same way
    ``served_with_bundle`` patches it to a stub, so the test holds
    whether or not `cd ui && npm run build` has ever been run locally.
    Every non-index route 404s via the bundle-missing fallback
    regardless of containment -- neither assertion below can actually
    catch a deleted containment check (see
    test_static_route_with_a_real_bundle_serves_assets_and_still_404s_escapes
    for the one that does). Kept anyway to document the no-bundle path.
    """
    monkeypatch.setattr("darwin_memo.ui.BUNDLE", tmp_path / "no-such-bundle")
    base, _, _ = served
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{base}/../../../etc/passwd", timeout=5)
    assert caught.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{base}/../../../pyproject.toml", timeout=5)
    assert caught.value.code == 404


def test_static_route_with_a_real_bundle_serves_assets_and_still_404s_escapes(
    served_with_bundle,
):
    base, _, _ = served_with_bundle
    with urllib.request.urlopen(f"{base}/assets/index-abc123.js", timeout=5) as resp:
        assert resp.status == 200
        assert resp.read() == b"export default 1;\n"
    # A bundle now exists, so a 404 here can only come from containment --
    # the no-bundle fallback that masked this in the other tests is not in
    # play. "../secret.txt" is one level above the bundle (the fixture
    # writes it into tmp_path, the bundle's parent) and genuinely exists,
    # unlike "/../../../pyproject.toml" -- that only reaches a real file
    # relative to this repo's actual BUNDLE, not to a tmp_path stand-in,
    # so it can't be trusted to discriminate a deleted containment check
    # under this fixture (confirmed by mutation: see task-4-report.md).
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(f"{base}/../secret.txt", timeout=5)
    assert caught.value.code == 404


def test_serve_refuses_a_non_loopback_host(tmp_path):
    memory = tmp_path / "memory.json"
    MemoryStore().save(memory)
    with pytest.raises(ValueError, match="loopback"):
        serve(memory, port=0, host="0.0.0.0")


def test_do_get_rejects_a_spoofed_host_header(served):
    """I-2: a loopback BIND stops remote network reach but not
    browser-mediated DNS rebinding, where a page the operator has open
    elsewhere points its own hostname at 127.0.0.1 and gets same-origin
    treatment. The socket below connects to 127.0.0.1 exactly like
    every other request in this file; only the Host header lies, which
    is the actual attack surface this must close."""
    base, _, _ = served
    status, body = _raw_get(base, "/api/state", "evil.example.com")
    assert status == 421
    assert "loopback" in json.loads(body)["error"]


def test_do_get_rejects_a_spoofed_host_with_a_port(served):
    base, _, _ = served
    status, _ = _raw_get(base, "/api/state", "evil.example.com:9999")
    assert status == 421


def test_do_get_accepts_every_loopback_host_form(served):
    """Both-directions proof: the guard must not reject the legitimate
    traffic every other test in this file depends on."""
    base, _, _ = served
    parsed = urllib.parse.urlsplit(base)
    for host_header in (
        "127.0.0.1",
        f"127.0.0.1:{parsed.port}",
        "localhost",
        f"localhost:{parsed.port}",
        "[::1]",
        f"[::1]:{parsed.port}",
    ):
        status, _ = _raw_get(base, "/api/state", host_header)
        assert status == 200, host_header


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
