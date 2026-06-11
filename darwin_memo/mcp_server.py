"""MCP server: mount a self-curating memory into any MCP client.

    pip install "darwin-memo[mcp]"
    darwin-memo-mcp --memory ~/.darwin-memo/memory.json

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
from .store import MemoryStore
from .types import EntryKind, MemoryEntry

DEFAULT_MEMORY = "~/.darwin-memo/memory.json"


def build_server(memory_path: Path, resource_scale: float):  # type: ignore[no-untyped-def]
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised without extra
        raise SystemExit(
            'The MCP server needs the optional extra: pip install "darwin-memo[mcp]"'
        ) from exc

    memory_path.parent.mkdir(parents=True, exist_ok=True)
    store = MemoryStore.load(memory_path) if memory_path.exists() else MemoryStore()
    event_log = memory_path.with_suffix(".events.jsonl")
    ledger = Ledger(store, resource_scale=resource_scale, event_log=event_log)

    server = FastMCP(
        name="darwin-memo",
        instructions=(
            "Self-curating memory. Query it with memory_query, which "
            "returns an answer plus a ticket id. When the real outcome of "
            "acting on that answer is known, call memory_settle with the "
            "MEASURED resource delta (tests passed, bytes freed, dollars "
            "saved): a measurement, never your opinion of answer quality. "
            "Entries that keep producing bad outcomes die on their own. "
            "Call memory_tick at natural boundaries (end of a session or "
            "work unit) so upkeep and consolidation run."
        ),
    )

    def _persist() -> None:
        store.save(memory_path)

    @server.tool()
    def memory_query(query: str) -> str:
        """Ask the memory a question. Returns the answer and a ticket id.

        If you act on the answer, keep the ticket id and call
        memory_settle once the outcome is measurable. An empty answer
        means memory has nothing relevant: prefer that silence over
        guessing.
        """
        ticket = ledger.decide(query)
        _persist()
        return json.dumps(
            {
                "answer": ticket.answer or None,
                "ticket_id": ticket.id if ticket.provenance else None,
                "silent": not ticket.answer,
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
        ledger.settle(ticket_id, delta, detail)
        _persist()
        return f"settled {ticket_id} at delta {delta:+g}"

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
                "graveyard": len(store.graveyard()),
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

    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="darwin-memo-mcp",
        description="MCP server exposing a self-curating darwin-memo store.",
    )
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
    args = parser.parse_args(argv)

    server = build_server(
        Path(args.memory).expanduser(), resource_scale=args.resource_scale
    )
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
