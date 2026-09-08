"""A local operator dashboard over one memory file.

    darwin-memo ui memory.json [--port 8787] [--no-open]

Reads on GET, mutates on POST: pin, unpin, forget, abandon, add, tick
and settle, the same operations the CLI and MCP expose. It was read-only
until the operator surface landed, and the argument for skipping
authentication was precisely that there was nothing to authorize. That
argument is gone, so writes carry four checks (see ``do_POST``): a
loopback ``Host``, a loopback ``Origin`` when the browser sends one, a
JSON content type, and a per-process token minted at startup and
embedded in the page.

The ``Host`` check is the load-bearing one and applies to reads too.
Binding to ``127.0.0.1`` stops remote *network* reach but not
*browser-mediated* reach: a page the operator has open elsewhere can
point its own hostname at 127.0.0.1 (DNS rebinding) and the browser
treats this server as same-origin. A rebound page sends the attacker's
hostname in ``Host``, which is why the check is first, before any route
lookup or file read.

One operation is different in kind. ``settle`` here takes a delta a
person typed, and a typed number is the human judgment this package
exists to exclude. It is not refused -- it is marked: the settle event
and every per-entry note record ``source: "operator"``, ``why`` and
``audit`` show it, and ``doctor`` raises ``operator_settled`` once
hand-entered deltas outweigh measured ones. A store curated by hand
stays usable and stops being evidence, visibly.

The store and the event log are re-read on every request. They are
small, and a dashboard showing yesterday's population is worse than a
re-parse.
"""

from __future__ import annotations

import argparse
import json
import math
import mimetypes
import re
import secrets
import sys
import threading
import webbrowser
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .ledger import Ledger
from .mcp_server import save_with_retry
from .observe import (
    doctor,
    economics,
    entry_life,
    evidence_window,
    filter_events,
    has_evidence,
    read_events,
    timeline,
    top_row,
)
from .store import StoreLockedError

BUNDLE = Path(__file__).parent / "data" / "ui"
LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


# A whole-string match (via fullmatch) for exactly a loopback-shaped
# authority: either a bracketed IPv6 literal ("[::1]") or a bare name/IPv4
# ("127.0.0.1", "localhost"), optionally followed by ":<digits>". Nothing
# may trail the port or the closing bracket -- that is what rejects
# "127.0.0.1:8787@evil.com" (garbage after the port) and "[::1]evil.com"
# (garbage after the bracket), where the old split-on-first-colon /
# strip-to-first-"]" parser truncated instead of refusing. The pattern
# ends in ``\Z``, not ``$`` -- ``$`` also matches just before a trailing
# newline, which would accept a smuggled "host\n" as a bare match.
_HOST_RE = re.compile(
    r"(?:\[(?P<v6>[0-9a-fA-F:]+)\]|(?P<name>[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?))"
    r"(?::(?P<port>\d+))?\Z"
)


def _host_only(raw: str) -> str | None:
    """Parse a ``Host`` header down to a bare, case-folded host name.

    Returns ``None`` for anything that is not *exactly* a loopback name
    or IP literal (brackets stripped for IPv6) plus an optional numeric
    port -- no path, no credentials, no trailing text, no empty string.
    Host names are case-insensitive (RFC 3986/7230: ``LOCALHOST`` must
    match ``localhost``); ``.lower()`` is safe for the IPv6 branch too
    since a loopback literal (``::1``) has no alphabetic characters to
    fold.
    """
    match = _HOST_RE.fullmatch(raw)
    if not match:
        return None
    host = match.group("v6") or match.group("name")
    return host.lower()


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
# Writes take the same lock as reads. A mutation is load-mutate-save and
# must not interleave with a read that holds a half-old ledger, nor with
# another mutation: the flock is per open file description, so two of this
# server's own threads would collide on it rather than serialize.
_STORE_WRITE_LOCK = _STORE_READ_LOCK


def _load(memory: Path) -> tuple[Ledger, list[dict[str, Any]]]:
    with _STORE_READ_LOCK:
        ledger = Ledger.load(memory)
        events = read_events(memory.with_suffix(".events.jsonl"))
    return ledger, events


_WRITE_ACTIONS = frozenset(
    {"pin", "unpin", "forget", "abandon", "add", "tick", "settle"}
)
_MAX_WRITE_BYTES = 64 * 1024


def _apply(memory: Path, action: str, body: dict[str, Any]) -> tuple[int, Any]:
    """Run one mutation under the store lock, then persist it.

    Load-mutate-save inside one lock, because the ledger's in-memory state
    (pending tickets, history) is authoritative for the write and a stale
    copy would clobber whatever another writer landed in between. Reads
    take the same lock, so the dashboard cannot race itself.
    """
    with _STORE_WRITE_LOCK:
        ledger = Ledger.load(memory, event_log=memory.with_suffix(".events.jsonl"))

        def entry_id() -> str:
            value = body.get("id")
            return value if isinstance(value, str) else ""

        if action == "tick":
            result: Any = ledger.tick()
        elif action == "pin":
            result = {"id": entry_id(), "pinned": ledger.pin(entry_id())}
        elif action == "unpin":
            result = {"id": entry_id(), "pinned": not ledger.unpin(entry_id())}
        elif action == "forget":
            result = {"id": entry_id(), "outcome": ledger.forget(entry_id())}
        elif action == "abandon":
            ticket = body.get("ticket_id")
            if not isinstance(ticket, str):
                return 400, {"error": "abandon needs a ticket_id"}
            result = {"ticket_id": ticket, "released": ledger.abandon(ticket)}
        elif action == "add":
            question = body.get("question")
            answer = body.get("answer")
            if not isinstance(question, str) or not question.strip():
                return 400, {"error": "add needs a question"}
            if not isinstance(answer, str) or not answer.strip():
                return 400, {"error": "add needs an answer"}
            source = body.get("source")
            entry = ledger.add(
                question.strip(),
                answer.strip(),
                source=source if isinstance(source, str) and source else "operator",
            )
            result = {"id": entry.id, "question": entry.question}
        elif action == "settle":
            ticket = body.get("ticket_id")
            delta = body.get("delta")
            if not isinstance(ticket, str):
                return 400, {"error": "settle needs a ticket_id"}
            if isinstance(delta, bool) or not isinstance(delta, (int, float)):
                return 400, {"error": "delta must be a number"}
            if not math.isfinite(delta):
                return 400, {
                    "error": "delta must be finite; a NaN is not a measurement"
                }
            detail = body.get("detail")
            # source="operator" is the whole point of allowing this from a
            # browser: the delta was typed by a person, and every downstream
            # reader has to be able to tell that from a measurement.
            landed = ledger.settle(
                ticket,
                float(delta),
                detail=detail if isinstance(detail, str) else "",
                source="operator",
            )
            result = {"ticket_id": ticket, "settled": landed, "source": "operator"}
        else:  # unreachable: do_POST checks the action first
            return 404, {"error": "not found"}

        save_with_retry(ledger, memory)
        return 200, result


def state(memory: Path) -> dict[str, Any]:
    """Everything the dashboard renders, in one read-only pass."""
    ledger, events = _load(memory)
    store = ledger.store
    tick = ledger.tick_count
    upkeep = store.upkeep
    entries = [
        top_row(entry, tick, store)
        for entry in sorted(store.alive(), key=lambda e: e.energy, reverse=True)
    ]
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
    window = evidence_window(ledger, events)
    return {
        # Which file this is. Nothing on screen said, so two dashboards on
        # two ports were indistinguishable tabs.
        "store": {
            "path": str(memory),
            "name": memory.name,
            "max_energy": store.max_energy,
            "merge_threshold": ledger.config.merge_threshold,
            "admission_window": ledger.config.admission_window,
        },
        "tick": tick,
        "upkeep": upkeep,
        "counts": {
            "alive": len(store),
            "dead": len(store.graveyard()),
            "pinned": sum(1 for e in store.alive() if e.pinned),
            "pending": len(ledger.pending()),
        },
        "total_energy": round(store.total_energy(), 3),
        # An empty doctor list means "healthy" or "nothing measured yet", and
        # the dashboard showed a green all-clear for both. This says which.
        "evidence": {**window, "diagnosed": has_evidence(window)},
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
    """GET reads the store; POST mutates it under the checks in do_POST.

    Every other verb keeps stdlib's own 501, which is the honest answer.
    """

    server_version = "darwin-memo"

    def __init__(self, memory: Path, token: str, *args: Any, **kwargs: Any) -> None:
        self.memory = memory
        self.token = token
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
        # DNS rebinding: loopback BIND stops remote network reach, but a
        # page the operator has open elsewhere can point its own
        # hostname at 127.0.0.1 and get same-origin treatment from the
        # browser, which is exactly the "no auth needed" argument in
        # the module docstring breaking down. Reject before any other
        # work -- no route lookup, no file read -- so an unexpected
        # Host can never reach a handler that would answer it.
        host = _host_only(self.headers.get("Host") or "")
        if host not in LOOPBACK:
            self._json(
                421, {"error": "unexpected Host; the dashboard is loopback-only"}
            )
            return
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
        except Exception as exc:  # a dev server must answer, not drop the connection
            # A local read-only dashboard that kills its request thread
            # gives the browser no status at all, which reads as "server
            # is broken" for what is usually a corrupt or unreadable
            # memory file. Surface it instead of swallowing it.
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

    def do_POST(self) -> None:  # stdlib callback name
        """Mutations, behind four checks that all have to pass.

        The read-only server needed no authentication because there was
        nothing to authorize. Writes change that, so:

        1. ``Host`` must be loopback -- same check as GET, and the one that
           actually defeats DNS rebinding, because a rebound page sends the
           attacker's hostname.
        2. ``Origin``, when the browser sends one, must be loopback too, so
           another app on localhost cannot drive this one.
        3. ``Content-Type`` must be JSON. A form POST cannot set it without
           triggering a CORS preflight this server never answers.
        4. A per-process token, minted at startup and embedded in the page,
           must arrive in ``X-Darwin-Memo-Token``. Cross-origin script
           cannot read the page, so it cannot mint the header.
        """
        host = _host_only(self.headers.get("Host") or "")
        if host not in LOOPBACK:
            self._json(
                421, {"error": "unexpected Host; the dashboard is loopback-only"}
            )
            return
        origin = self.headers.get("Origin")
        if origin is not None:
            parsed_origin = urlparse(origin)
            if _host_only(parsed_origin.netloc) not in LOOPBACK:
                self._json(403, {"error": "cross-origin writes are refused"})
                return
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        if ctype != "application/json":
            self._json(415, {"error": "writes must be application/json"})
            return
        if self.headers.get("X-Darwin-Memo-Token") != self.token:
            self._json(403, {"error": "missing or stale write token; reload the page"})
            return

        route = unquote(urlparse(self.path).path)
        action = route[len("/api/") :] if route.startswith("/api/") else ""
        if action not in _WRITE_ACTIONS:
            self._json(404, {"error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > _MAX_WRITE_BYTES:
            self._json(413, {"error": "request too large"})
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"error": "body is not valid JSON"})
            return
        if not isinstance(body, dict):
            self._json(400, {"error": "body must be a JSON object"})
            return

        try:
            status, payload = _apply(self.memory, action, body)
            self._json(status, payload)
        except FileNotFoundError:
            self._json(404, {"error": "memory file not found"})
        except StoreLockedError:
            self._json(
                503,
                {
                    "error": "store is locked by another darwin-memo "
                    "process; retry in a moment"
                },
            )
        except Exception as exc:  # a dev server must answer, not drop the connection
            self._json(500, {"error": f"{type(exc).__name__}: {exc}"})

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
        if target.name == "index.html":
            # The write token reaches the page here rather than through an
            # endpoint, so that only something able to READ this document
            # can mint a write. Cross-origin script cannot.
            html = target.read_text(encoding="utf-8").replace(
                "<head>",
                f'<head><meta name="darwin-memo-token" content="{self.token}">',
                1,
            )
            self._send(200, html.encode(), "text/html; charset=utf-8")
            return
        guessed, _ = mimetypes.guess_type(target.name)
        self._send(200, target.read_bytes(), guessed or "application/octet-stream")


def serve(memory: Path, port: int, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Build (but do not start) the dashboard server.

    Refuses a non-loopback bind. The dashboard can now write -- pin,
    forget, tick, settle -- so the old "no auth because no mutations"
    argument is gone and the loopback bind matters more, not less. It is
    still not an authentication system: it is a single-operator tool on
    one machine, and the per-process token below only stops OTHER local
    pages from driving it.
    """
    if host not in LOOPBACK:
        raise ValueError(
            f"refusing to bind {host}: the dashboard writes to your store "
            "and is loopback-only by design"
        )
    token = secrets.token_urlsafe(32)
    return ThreadingHTTPServer((host, port), partial(_Handler, memory, token))


def cmd_ui(args: argparse.Namespace) -> int:
    memory = Path(args.memory).expanduser()
    if not memory.exists():
        print(f"error: {args.memory} not found")
        return 1
    server = serve(memory, port=args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"darwin-memo ui: {url}  (ctrl-c to stop)")
    print(f"  store: {memory}")
    if not BUNDLE.is_dir():
        # From a source checkout darwin_memo/data/ui is gitignored and built
        # at release time. Saying so here beats letting the browser be the
        # first place the reader learns it.
        print(
            "  note: this checkout has no built frontend, so the page is a "
            "placeholder.\n"
            "        build it once with: cd ui && npm install && npm run build\n"
            "        the JSON API at /api/state works either way.",
            file=sys.stderr,
        )
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0
