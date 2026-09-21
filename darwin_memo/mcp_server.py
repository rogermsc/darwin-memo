"""MCP server: mount a self-curating memory into any MCP client.

    pip install "darwin-memo[mcp]"
    darwin-memo-mcp --memory ~/.darwin-memo/memory.json
    darwin-memo mcp --memory ~/.darwin-memo/memory.json   # same server

Claude Code:

    claude mcp add darwin-memo -- darwin-memo-mcp --memory ~/.darwin-memo/memory.json

Each tool reloads its ledger within a local POSIX file transaction. Pending
outcome tickets survive restarts. Use --ci-authority to expose only query,
add, and inspection; the host then owns settlement and retention changes.
Agent-supplied outcomes carry source="agent", not independent verification.

"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import ParamSpec, Protocol, TypeVar

from .ledger import Ledger
from .observe import audit_digest, doctor, filter_events, read_events, top_row
from .store import MemoryStore, StoreLockedError, store_lock

P = ParamSpec("P")
R = TypeVar("R")

DEFAULT_MEMORY = "~/.darwin-memo/memory.json"
_PERSIST_RETRIES = 5
_PERSIST_BACKOFF = 0.05  # seconds; grows linearly per attempt


class _Persistable(Protocol):
    def save(self, path: str | Path) -> None: ...


def save_with_retry(
    ledger: _Persistable,
    path: str | Path,
    retries: int = _PERSIST_RETRIES,
    backoff: float = _PERSIST_BACKOFF,
) -> None:
    """Persist the ledger, retrying a transient StoreLockedError.

    MCP operations hold the lock across load, mutation, and save, so nested
    saves reuse it. This helper remains available for existing Python callers.
    It never reloads stale state; stale snapshots remain rejected. Callers
    must retry their entire transaction after contention or a changed file.
    """
    for attempt in range(retries):
        try:
            ledger.save(path)
            return
        except StoreLockedError:
            if attempt == retries - 1:
                raise
            time.sleep(backoff * (attempt + 1))


def build_server(  # type: ignore[no-untyped-def]
    memory_path: Path, resource_scale: float, *, allow_settlement: bool = True
):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        # Naming the underlying error matters: mcp 2.0.0 removed
        # mcp.server.fastmcp, so this fires with the extra correctly
        # installed, and a message that only says "install the extra"
        # sends the reader to re-run a command that already succeeded.
        raise SystemExit(
            "The MCP server could not import mcp.server.fastmcp "
            f"({exc}). Install the optional extra with "
            'pip install "darwin-memo[mcp]"; if it is already installed, '
            "check the version, which must be >=1.10,<2."
        ) from exc

    memory_path.parent.mkdir(parents=True, exist_ok=True)
    event_log = memory_path.with_suffix(".events.jsonl")
    # Ledger.load restores BOTH the store and the ledger state (pending
    # tickets, tick count, history), so tickets survive server restarts:
    # the whole point of decide-now-settle-later.
    if memory_path.exists():
        ledger = Ledger.load(
            memory_path, resource_scale=resource_scale, event_log=event_log
        )
    else:
        ledger = Ledger(
            MemoryStore(), resource_scale=resource_scale, event_log=event_log
        )
    store = ledger.store

    server = FastMCP(
        name="darwin-memo",
        instructions=(
            "Query memory before a task and keep its ticket. "
            "Associate it with your task using the repository CI workflow. "
            "CI reports observable outcomes; settlement does not prove causation. "
            + (
                "Agent-supplied settlement is enabled."
                if allow_settlement
                else "Settlement and retention mutations are reserved for the host; "
                "this client can query and add lessons."
            )
        ),
    )

    def operation(fn: Callable[P, R]) -> Callable[P, R]:
        @wraps(fn)
        def call(*args: P.args, **kwargs: P.kwargs) -> R:
            nonlocal ledger, store
            with store_lock(memory_path):
                ledger = (
                    Ledger.load(
                        memory_path, resource_scale=resource_scale, event_log=event_log
                    )
                    if memory_path.exists()
                    else Ledger(
                        MemoryStore(),
                        resource_scale=resource_scale,
                        event_log=event_log,
                    )
                )
                store = ledger.store
                return fn(*args, **kwargs)

        return call

    def _persist() -> None:
        save_with_retry(ledger, memory_path)

    @server.tool()
    @operation
    def memory_query(query: str, half_life: float = 0) -> str:
        """Ask the memory a question. Returns the answer and a ticket id.

        Answers carry each entry's age (UTC recorded timestamp, born
        tick, last settled tick; "age unknown" for entries persisted
        before timestamps existed), and near-duplicate entries that
        disagree surface together as a dated conflict block, newest
        first, instead of one silently winning. Weigh stale advice
        accordingly. half_life greater than zero opts into
        recency-weighted ranking, halving scores every that many ticks
        since an entry last settled; it reorders results only and never
        moves energy.

        If you act on the answer, keep the ticket id for the host's outcome
        workflow. Without --ci-authority, memory_settle and memory_abandon
        also accept agent input. A silent result means memory has
        nothing relevant: prefer that silence over guessing.

        ``deciding_entry`` and ``supporting_entries`` are the ids credit
        will flow to. Pass one to memory_obituary to see what that entry
        has earned, or to memory_forget if the advice was simply wrong.
        """
        ticket = ledger.decide(query, half_life=half_life if half_life > 0 else None)
        _persist()
        return json.dumps(
            {
                "answer": ticket.answer or None,
                "ticket_id": ticket.id if ticket.provenance else None,
                "silent": not ticket.provenance,
                # Without these the agent gets an answer it cannot trace:
                # every inspection tool here is keyed by entry id, and the
                # ticket id opens none of them.
                "deciding_entry": ticket.deciding_entry,
                "supporting_entries": list(ticket.supporting_entries),
            }
        )

    @server.tool()
    @operation
    def memory_settle(ticket_id: str, delta: float, detail: str = "") -> str:
        """Report an agent-supplied outcome for a ticket.

        delta is an agent-supplied outcome, not independently verified. Positive
        reinforces the entries that produced the answer, negative
        drains them. Do not pass a quality score or a vibe.
        """
        landed = ledger.settle(ticket_id, delta, detail, source="agent")
        _persist()
        if landed:
            return f"settled {ticket_id} at delta {delta:+g}"
        return (
            f"NOT settled: ticket {ticket_id} is unknown, already settled, "
            "or expired; no credit moved"
        )

    @server.tool()
    @operation
    def memory_abandon(ticket_id: str) -> str:
        """Release a ticket whose answer you did not act on.

        No action means no outcome to measure; abandoning settles at
        delta zero so the entries it escrowed can be curated normally.
        """
        landed = ledger.abandon(ticket_id)
        _persist()
        return (
            f"abandoned {ticket_id}"
            if landed
            else f"ticket {ticket_id} was not pending; nothing to abandon"
        )

    @server.tool()
    @operation
    def memory_add(question: str, answer: str, source: str = "agent") -> str:
        """Write a new entry. It starts at spawn energy and must earn
        its keep from here: adding is cheap, surviving is not."""
        # Through the ledger, not store.add directly: ledger.add stamps
        # born_cycle from the current tick, logs the birth to the audit, and
        # applies admission gating. store.add left born_cycle at 0, so an
        # agent-added entry showed as the oldest in the store and ranked as
        # ancient under recency weighting, with no birth event recorded.
        entry = ledger.add(question, answer, source)
        _persist()
        return f"added {entry.id}"

    @server.tool()
    @operation
    def memory_tick() -> str:
        """Advance one unit of time: upkeep, deaths, consolidation.
        Call at natural boundaries, like the end of a work session."""
        stats = ledger.tick()
        _persist()
        return json.dumps(stats)

    @server.tool()
    @operation
    def memory_stats() -> str:
        """Population overview: alive, graveyard, energy by kind."""
        return json.dumps(
            {
                "alive": len(store),
                "graveyard": store.dead_count(),
                "pending_tickets": len(ledger.pending()),
                "total_energy": round(store.total_energy(), 3),
                "energy_share_by_kind": {
                    k: round(v, 3) for k, v in store.energy_share_by_kind().items()
                },
            }
        )

    @server.tool()
    @operation
    def memory_obituary(entry_id: str) -> str:
        """Why did this entry die (or how is it doing)? Full credit
        history from the ledger."""
        return ledger.obituary(entry_id)

    @server.tool()
    @operation
    def memory_pending() -> str:
        """Open tickets, with their ids: decisions still awaiting an outcome.

        memory_stats reports only how many there are, which is no help to
        a host that lost a ticket id across a restart. Settle the ones you
        acted on, abandon the ones you did not; a ticket left open escrows
        its entries, which keep paying upkeep but cannot be buried or
        merged until the verdict lands.
        """
        return json.dumps(
            {
                "tick": ledger.tick_count,
                "pending": [
                    {
                        "ticket_id": ticket.id,
                        "query": ticket.query,
                        "born_tick": ticket.born_tick,
                        "age_ticks": ledger.tick_count - ticket.born_tick,
                        "deciding_entry": ticket.deciding_entry,
                    }
                    for ticket in ledger.pending()
                ],
            }
        )

    @server.tool()
    @operation
    def memory_top(limit: int = 10) -> str:
        """Living entries ranked by balance: what this memory is made of.

        Balance is the entry's energy. Every entry pays upkeep each tick
        and earns only from settled outcomes, so a high balance means
        repeatedly measured-useful, and ticks_to_starvation is how long
        the entry has left if it never earns again.
        """
        ranked = sorted(store.alive(), key=lambda e: e.energy, reverse=True)
        return json.dumps(
            {
                "tick": ledger.tick_count,
                "alive": len(store),
                "entries": [
                    top_row(entry, ledger.tick_count, store)
                    for entry in ranked[: max(1, limit)]
                ],
            }
        )

    @server.tool()
    @operation
    def memory_doctor() -> str:
        """Name the failure mode behind a store that is not earning.

        Returns findings with a code, a severity, the evidence behind
        each one, and what to do about it -- rather than leaving several
        different degeneracies looking identical from the outside. An
        empty findings list on a store that has never ticked means "no
        evidence yet", not "healthy"; ``evidence_window`` says which.
        """
        events = read_events(event_log)
        findings = [f.as_dict() for f in doctor(ledger, events)]
        return json.dumps(
            {
                "findings": findings,
                "evidence_window": {
                    "events": len(events),
                    "ticks": ledger.tick_count,
                },
            }
        )

    @server.tool()
    @operation
    def memory_forget(entry_id: str) -> str:
        """Bury an entry outright, without waiting for selection.

        For advice that is wrong but inert: selection can only remove what
        it measures, and an entry nothing acts on is never settled, so it
        starves only slowly and answers in the meantime. Refused for a
        pinned entry (unpin it first) and for one escrowed against an open
        ticket; the reply says which.
        """
        outcome = ledger.forget(entry_id)
        _persist()
        return json.dumps({"entry_id": entry_id, "outcome": outcome})

    @server.tool()
    @operation
    def memory_pin(entry_id: str) -> str:
        """Protect an entry from starvation and merges.

        A pin is a standing claim that this entry is correct regardless of
        what it earns, so it suspends the only mechanism that removes bad
        memory. Pin sparingly, and prefer letting an entry earn its place.
        """
        pinned = ledger.pin(entry_id)
        _persist()
        return json.dumps({"entry_id": entry_id, "pinned": pinned})

    @server.tool()
    @operation
    def memory_unpin(entry_id: str) -> str:
        """Return a pinned entry to normal selection pressure."""
        unpinned = ledger.unpin(entry_id)
        _persist()
        return json.dumps({"entry_id": entry_id, "pinned": not unpinned})

    @server.tool()
    @operation
    def memory_audit(since: str = "", last: int = 0) -> str:
        """Digest of the event log: decisions, settlements, culls, and
        energy flow with top gainers and losers. The audit trail for
        spotting a poisoned entry's rise and death. ``since`` is an
        ISO-8601 UTC floor, ``last`` keeps only the newest N events;
        zero values mean no filter."""
        events = filter_events(
            read_events(event_log), since=since or None, last=last or None
        )
        return json.dumps(audit_digest(events, store=store))

    if not allow_settlement:
        for name in (
            "memory_settle",
            "memory_tick",
            "memory_abandon",
            "memory_forget",
            "memory_pin",
            "memory_unpin",
        ):
            server.remove_tool(name)
    return server


def _add_server_arguments(parser: argparse.ArgumentParser) -> None:
    """One flag set shared by darwin-memo-mcp and ``darwin-memo mcp``."""
    parser.add_argument(
        "--memory",
        default=os.environ.get("DARWIN_MEMO_PATH", DEFAULT_MEMORY),
        help=f"path to the persistent memory file (default {DEFAULT_MEMORY})",
    )
    parser.add_argument(
        "--ci-authority",
        action="store_true",
        help="expose query, add, and inspection; "
        "reserve settlement and retention for CI",
    )
    parser.add_argument(
        "--resource-scale",
        type=float,
        default=1.0,
        help="normalization for settle deltas (see README design notes)",
    )


def cmd_serve(args: argparse.Namespace) -> int:
    server = build_server(
        Path(args.memory).expanduser(),
        resource_scale=args.resource_scale,
        allow_settlement=not args.ci_authority,
    )
    server.run()
    return 0


def register_mcp_command(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Attach mcp, so cli.py stays one import plus one call.

    Registry clients construct ``uvx [runtimeArguments]
    darwin-memo@VERSION [packageArguments]``, and uvx runs the console
    script named after the package: the main darwin-memo CLI, not
    darwin-memo-mcp. This subcommand gives that machine-built launch a
    working server entry point (server.json passes ``mcp`` as a package
    argument); darwin-memo-mcp stays for humans and existing configs.
    """
    mcp = sub.add_parser(
        "mcp",
        help="serve the memory over MCP stdio (same server as darwin-memo-mcp)",
    )
    _add_server_arguments(mcp)
    mcp.set_defaults(fn=cmd_serve)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="darwin-memo-mcp",
        description="MCP server exposing a self-curating darwin-memo store.",
    )
    _add_server_arguments(parser)
    return cmd_serve(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
