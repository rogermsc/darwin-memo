"""A local, read-only dashboard over one memory file.

    darwin-memo ui memory.json [--port 8787] [--no-open]

Loopback-only and read-only by construction. There are no mutation
endpoints, which is precisely what lets this skip authentication, CSRF
tokens and session handling: nothing a browser can reach here changes
state. Culling, settling and pinning stay on the CLI and MCP, where
every operation is event-logged and audited.

The store and the event log are re-read on every request. They are
small, and a dashboard showing yesterday's population is worse than a
re-parse.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .ledger import Ledger
from .observe import (
    doctor,
    economics,
    entry_life,
    filter_events,
    read_events,
    timeline,
    top_row,
)
from .store import StoreLockedError

BUNDLE = Path(__file__).parent / "data" / "ui"
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})

_NO_BUNDLE = b"""<!doctype html><meta charset="utf-8">
<title>darwin-memo</title>
<body style="font-family:system-ui;max-width:40rem;margin:4rem auto">
<h1>No UI bundle</h1>
<p>This checkout has no built frontend. Build it once:</p>
<pre>cd ui &amp;&amp; npm install &amp;&amp; npm run build</pre>
<p>The JSON API is live regardless: <a href="/api/state">/api/state</a></p>
"""

# Ledger.load() takes the store's sidecar advisory lock (store_lock in
# store.py) via fcntl.flock(LOCK_EX | LOCK_NB), which *raises*
# StoreLockedError on contention instead of blocking and retrying. flock
# is scoped to the open file description, so two threads in this same
# process each doing their own open()+flock() collide with each other
# too, not just with another process. ThreadingHTTPServer hands each
# request its own thread, and a browser opens /api/state and /api/events
# in parallel, so an unguarded per-request Ledger.load() would 500 the
# dashboard on itself. Serializing the read here fixes that; reads are
# fast and the file is small, so a global lock is the cheap right call.
# A StoreLockedError can still surface from a genuinely external writer
# (e.g. `darwin-memo ledger settle` running concurrently against this
# file) and do_GET maps that to a 503, not a crash.
_STORE_READ_LOCK = threading.Lock()


def _load(memory: Path) -> tuple[Ledger, list[dict[str, Any]]]:
    with _STORE_READ_LOCK:
        ledger = Ledger.load(memory)
        events = read_events(memory.with_suffix(".events.jsonl"))
    return ledger, events


def state(memory: Path) -> dict[str, Any]:
    """Everything the dashboard renders, in one read-only pass."""
    ledger, events = _load(memory)
    store = ledger.store
    tick = ledger.tick_count
    upkeep = store.upkeep
    entries = []
    for entry in sorted(store.alive(), key=lambda e: e.energy, reverse=True):
        row = top_row(entry, tick)
        # The operator's actual question, and the one number that makes
        # the starvation cliff visible before it bites.
        row["ticks_to_starvation"] = (
            round(entry.energy / upkeep, 1) if upkeep > 0 else None
        )
        entries.append(row)
    graveyard = []
    for dead in store.graveyard():
        life = entry_life(ledger, dead.id)
        if life is None:
            continue
        graveyard.append(
            {
                "id": life["id"],
                "question": life["question"],
                "cause": life["cause_of_death"] or "unknown",
                "uses": life["uses"],
                "sources": life["sources"],
            }
        )
    return {
        "tick": tick,
        "upkeep": upkeep,
        "counts": {
            "alive": len(store),
            "dead": len(store.graveyard()),
            "pinned": sum(1 for e in store.alive() if e.pinned),
            "pending": len(ledger.pending()),
        },
        "total_energy": round(store.total_energy(), 3),
        "doctor": [f.as_dict() for f in doctor(ledger, events)],
        "timeline": timeline(events),
        "economics": economics(events, store),
        "entries": entries,
        "graveyard": graveyard,
        "pending": [
            {
                "id": ticket.id,
                "query": ticket.query,
                "born_tick": ticket.born_tick,
                "age_ticks": tick - ticket.born_tick,
            }
            for ticket in ledger.pending()
        ],
    }


class _Handler(BaseHTTPRequestHandler):
    """GET-only. Any other verb is a 405; there is nothing to write."""

    server_version = "darwin-memo"

    def __init__(self, memory: Path, *args: Any, **kwargs: Any) -> None:
        self.memory = memory
        super().__init__(*args, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        """Silence per-request logging; the terminal shows the URL only."""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Any) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def do_GET(self) -> None:  # stdlib callback name
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        try:
            if route == "/api/state":
                self._json(200, state(self.memory))
            elif route.startswith("/api/entry/"):
                self._entry(route[len("/api/entry/") :])
            elif route == "/api/events":
                self._events(parse_qs(parsed.query))
            else:
                self._static(route)
        except FileNotFoundError:
            self._json(404, {"error": "memory file not found"})
        except StoreLockedError:
            # A genuine external writer (CLI settle/tick, MCP server)
            # holds the lock right now. Not our bug and not a crash:
            # tell the browser to retry rather than 500ing on it.
            self._json(
                503,
                {
                    "error": "store is locked by another darwin-memo "
                    "process; retry in a moment"
                },
            )

    def _entry(self, entry_id: str) -> None:
        ledger, _ = _load(self.memory)
        life = entry_life(ledger, entry_id)
        if life is None:
            self._json(404, {"error": f"{entry_id} is unknown to this store"})
            return
        self._json(200, life)

    def _events(self, query: dict[str, list[str]]) -> None:
        _, events = _load(self.memory)
        last = query.get("last", ["200"])[0]
        since = query.get("since", [None])[0]
        try:
            limit: int | None = int(last)
        except ValueError:
            limit = 200
        self._json(200, {"events": filter_events(events, since=since, last=limit)})

    def _static(self, route: str) -> None:
        root = BUNDLE.resolve()
        target = (root / route.lstrip("/")).resolve()
        # Containment first, and before any bundle-presence shortcut: a
        # path that climbed out is a 404 whether or not a bundle exists.
        if target != root and root not in target.parents:
            self._json(404, {"error": "not found"})
            return
        if target == root or target.is_dir():
            target = root / "index.html"
        if not BUNDLE.is_dir():
            # No built frontend: the index route explains how to build
            # one; every other path is absent, not a placeholder.
            if target == root / "index.html":
                self._send(200, _NO_BUNDLE, "text/html; charset=utf-8")
            else:
                self._json(404, {"error": "not found"})
            return
        if not target.is_file():
            self._json(404, {"error": "not found"})
            return
        guessed, _ = mimetypes.guess_type(target.name)
        self._send(200, target.read_bytes(), guessed or "application/octet-stream")


def serve(memory: Path, port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Build (but do not start) the dashboard server.

    Refuses a non-loopback bind: the server has no authentication
    because it has no mutations, and that trade only holds on localhost.
    """
    if host not in LOOPBACK:
        raise ValueError(
            f"refusing to bind {host}: the dashboard is unauthenticated "
            "and loopback-only by design"
        )
    return ThreadingHTTPServer((host, port), partial(_Handler, memory))


def cmd_ui(args: argparse.Namespace) -> int:
    memory = Path(args.memory).expanduser()
    if not memory.exists():
        print(f"error: {args.memory} not found")
        return 1
    server = serve(memory, port=args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"darwin-memo ui: {url}  (ctrl-c to stop)")
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0
