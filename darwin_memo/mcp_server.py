"""MCP server: mount a self-curating memory into any MCP client.

    pip install "darwin-memo[mcp]"
    darwin-memo-mcp --memory ~/.darwin-memo/memory.json
    darwin-memo mcp --memory ~/.darwin-memo/memory.json   # same server

Claude Code:

    claude mcp add darwin-memo -- darwin-memo-mcp --memory ~/.darwin-memo/memory.json

The server wraps a :class:`~darwin_memo.ledger.Ledger`, so the agent
carries the full contract: query memory (which opens a ticket), report
the measured outcome later (which settles it), and advance time. The
selection rule survives the transport: ``memory_settle`` takes a
measured delta, never a quality grade, and the docstrings the agent
sees say so.

State persists to one JSON file after every mutating call, so the
memory survives across sessions and the population carries its scars
forward.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .ledger import Ledger
from .observe import audit_digest, filter_events, read_events
from .store import MemoryStore
from .types import EntryKind, MemoryEntry

DEFAULT_MEMORY = "~/.darwin-memo/memory.json"


def build_server(memory_path: Path, resource_scale: float):  # type: ignore[no-untyped-def]
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
            "Self-curating memory. Query it with memory_query, which "
            "returns an answer plus a ticket id. When the real outcome of "
            "acting on that answer is known, call memory_settle with the "
            "MEASURED resource delta (tests passed, bytes freed, dollars "
            "saved): a measurement, never your opinion of answer quality. "
            "If you decide NOT to act on an answer, call memory_abandon "
            "with the ticket id so its escrow releases. Entries that keep "
            "producing bad outcomes die on their own. Call memory_tick at "
            "natural boundaries (end of a session or work unit) so upkeep "
            "and consolidation run."
        ),
    )

    def _persist() -> None:
        ledger.save(memory_path)

    @server.tool()
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

        If you act on the answer, keep the ticket id and call
        memory_settle once the outcome is measurable; if you do not act,
        call memory_abandon with it. A silent result means memory has
        nothing relevant: prefer that silence over guessing.
        """
        ticket = ledger.decide(query, half_life=half_life if half_life > 0 else None)
        _persist()
        return json.dumps(
            {
                "answer": ticket.answer or None,
                "ticket_id": ticket.id if ticket.provenance else None,
                "silent": not ticket.provenance,
            }
        )

    @server.tool()
    def memory_settle(ticket_id: str, delta: float, detail: str = "") -> str:
        """Report the measured outcome for a ticket.

        delta MUST be a measurement of a conserved resource (tests now
        passing minus before, bytes freed, dollars saved). Positive
        reinforces the entries that produced the answer, negative
        drains them. Do not pass a quality score or a vibe.
        """
        landed = ledger.settle(ticket_id, delta, detail)
        _persist()
        if landed:
            return f"settled {ticket_id} at delta {delta:+g}"
        return (
            f"NOT settled: ticket {ticket_id} is unknown, already settled, "
            "or expired; no credit moved"
        )

    @server.tool()
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
    def memory_add(question: str, answer: str, source: str = "agent") -> str:
        """Write a new entry. It starts at spawn energy and must earn
        its keep from here: adding is cheap, surviving is not."""
        entry = store.add(
            MemoryEntry(
                question=question,
                answer=answer,
                kind=EntryKind.EXPERIENCE,
                sources=[source],
            )
        )
        _persist()
        return f"added {entry.id}"

    @server.tool()
    def memory_tick() -> str:
        """Advance one unit of time: upkeep, deaths, consolidation.
        Call at natural boundaries, like the end of a work session."""
        stats = ledger.tick()
        _persist()
        return json.dumps(stats)

    @server.tool()
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
    def memory_obituary(entry_id: str) -> str:
        """Why did this entry die (or how is it doing)? Full credit
        history from the ledger."""
        return ledger.obituary(entry_id)

    @server.tool()
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

    return server


def _add_server_arguments(parser: argparse.ArgumentParser) -> None:
    """One flag set shared by darwin-memo-mcp and ``darwin-memo mcp``."""
    parser.add_argument(
        "--memory",
        default=os.environ.get("DARWIN_MEMO_PATH", DEFAULT_MEMORY),
        help=f"path to the persistent memory file (default {DEFAULT_MEMORY})",
    )
    parser.add_argument(
        "--resource-scale",
        type=float,
        default=1.0,
        help="normalization for settle deltas (see README design notes)",
    )


def cmd_serve(args: argparse.Namespace) -> int:
    server = build_server(
        Path(args.memory).expanduser(), resource_scale=args.resource_scale
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
