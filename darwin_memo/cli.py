"""The darwin-memo command line.

    darwin-memo demo                     watch a poisoned entry go extinct
    darwin-memo encode DOCS... -o FILE   corpus files -> memory.json
    darwin-memo query FILE "question"    interrogate a saved memory
    darwin-memo stats FILE               population, energy, graveyard
    darwin-memo ledger FILE OP ...       decide/settle/tick for scripts
    darwin-memo mcp                      serve the memory over MCP stdio

The demo is self-contained: it carries its own three-document corpus
(including the poisoned forum post) and runs the survival loop against
a real temp directory, so ``pip install darwin-memo && darwin-memo demo``
shows the whole idea with no checkout, no keys, no network.

``ledger`` is the scripting bridge: every Ledger operation as a
subcommand printing one JSON object to stdout, so shell scripts, CI
steps, and host-process plugins (built for the OpenClaw memory plugin,
whose host SDK has no MCP client) get the full decide/settle/tick
contract without speaking MCP or importing Python. Same rule as
everywhere else: ``settle`` takes a measured delta, never a grade.
Invocations against one file must not run concurrently: darwin-memo is
single-writer. The advisory lock makes two operations that overlap on
one file fail loudly (``StoreLockedError``) instead of clobbering each
other silently, but it cannot catch a stale in-memory state saved after
the other invocation finished, so the contract stays single-writer.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from .ci import add_settle_ci_parser
from .encode import Document, LocalEncoder, demo_corpus
from .environments import StorageEnv
from .ledger import Ledger
from .llm import LLMClient
from .mcp_server import register_mcp_command
from .observe import register_observe_commands
from .protocol import QueryProtocol
from .render import register_render_command
from .store import MemoryStore
from .survival import SurvivalConfig, SurvivalLoop, death_cause


def cmd_demo(args: argparse.Namespace) -> int:
    store = MemoryStore(upkeep=0.05)
    for entry in LocalEncoder().encode(demo_corpus()):
        store.add(entry)
    poisoned = {e.id for e in store.alive() if "forum-post" in e.sources}

    print(
        f"Encoded {len(store)} memory entries from 3 documents, "
        f"{len(poisoned)} of them from a poisoned forum post claiming\n"
        'database files are "redundant and safe to remove".\n'
    )
    print(
        "Running 30 survival cycles against a real temp directory.\n"
        "Nothing grades the answers; deleting a protected file costs 3x\n"
        "its size in restore scratch space, and that delta lands on the\n"
        "entries that advised it.\n"
    )

    env = StorageEnv(files_per_cycle=12, seed=11)
    loop = SurvivalLoop(store, env, config=SurvivalConfig(cycles=args.cycles))
    report = loop.run()
    env.cleanup()

    print(report.summary())

    merged_away = {
        ancestor for e in store.alive() + store.graveyard() for ancestor in e.lineage
    }
    print("\nSurvivors:")
    for entry in sorted(store.alive(), key=lambda e: e.energy, reverse=True):
        print(f"  {entry.energy:5.2f} [{entry.kind.value:>12}] {entry.answer[:70]}")
    print("\nGraveyard:")
    for entry in store.graveyard():
        cause = death_cause(entry, poisoned, merged_away)
        print(f"  {cause:>8} [{entry.kind.value:>12}] {entry.answer[:70]}")

    still_poisoned = sum(1 for e in store.alive() if "forum-post" in e.sources)
    print(f"\nPoisoned entries still alive: {still_poisoned}")
    if args.out:
        store.save(args.out)
        print(f"Saved the surviving population to {args.out}")
    return 0


def cmd_encode(args: argparse.Namespace) -> int:
    documents = []
    for path in args.documents:
        p = Path(path)
        if not p.exists():
            print(f"error: {path} not found", file=sys.stderr)
            return 1
        documents.append(Document(doc_id=p.stem, text=p.read_text()))
    store = MemoryStore()
    for entry in LocalEncoder().encode(documents):
        store.add(entry)
    store.save(args.out)
    kinds = Counter(e.kind.value for e in store.alive())
    print(f"Encoded {len(store)} entries from {len(documents)} documents -> {args.out}")
    for kind, count in kinds.most_common():
        print(f"  {kind:>12}: {count}")
    return 0


def _client_for(spec: str | None) -> LLMClient | None:
    """Resolve a --model spec like ollama:llama3.2 into an LLM client."""
    if not spec:
        return None
    if spec.startswith("ollama:"):
        from .llm import OllamaClient, ollama_available

        if not ollama_available():
            print(
                "error: --model ollama:* needs a running Ollama server "
                "(https://ollama.com, `ollama serve`)",
                file=sys.stderr,
            )
            raise SystemExit(1)
        return OllamaClient(model=spec.split(":", 1)[1])
    if spec.startswith("anthropic:"):
        try:
            from .llm import AnthropicClient

            return AnthropicClient(model=spec.split(":", 1)[1])
        except ImportError:
            print(
                "error: --model anthropic:* needs the optional extra: "
                'pip install "darwin-memo[anthropic]"',
                file=sys.stderr,
            )
            raise SystemExit(1) from None
    print(
        f"error: unknown model spec {spec!r}; use ollama:NAME or anthropic:NAME",
        file=sys.stderr,
    )
    raise SystemExit(1)


def cmd_query(args: argparse.Namespace) -> int:
    store = MemoryStore.load(args.memory)
    client = _client_for(args.model)
    answer = QueryProtocol(store, client).answer(args.question)
    if not answer.text:
        print("(memory is silent: no entry clears the relevance floor)")
        return 0
    print(answer.text)
    deciding = store.get(answer.deciding_entry) if answer.deciding_entry else None
    if deciding:
        print(f"  deciding entry: [{deciding.kind.value}] {deciding.question}")
        print(f"  sources: {', '.join(deciding.sources)}")
    elif answer.supporting_entries:
        print(f"  cited entries: {', '.join(answer.supporting_entries)}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    store = MemoryStore.load(args.memory)
    print(f"alive: {len(store)}  graveyard: {len(store.graveyard())}")
    print(f"total energy: {store.total_energy():.2f}")
    shares = store.energy_share_by_kind()
    for kind, share in sorted(shares.items(), key=lambda kv: -kv[1]):
        print(f"  {kind:>12}: {share:.0%} of energy")
    top = sorted(store.alive(), key=lambda e: e.energy, reverse=True)[:5]
    print("strongest entries:")
    for entry in top:
        print(f"  {entry.energy:5.2f}  {entry.question[:70]}")
    return 0


def cmd_ledger(args: argparse.Namespace) -> int:
    """One Ledger operation per invocation, one JSON object on stdout.

    The store auto-creates on first use (a missing file is an empty
    ledger, mirroring the MCP server), and every mutating op saves
    before printing, so a crash can never acknowledge an unsaved
    settlement.
    """
    path = Path(args.memory).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Loads use the default lexical retriever; a store built with an
    # embedding retriever keeps its persisted vectors but ranks
    # lexically here (the CLI cannot construct your embedder).
    # Same event-log convention as the MCP server. Sequential sharing
    # only: the MCP server holds its ledger in memory and saves after
    # every call, so running both against one file concurrently means
    # the server's next save clobbers whatever the CLI wrote.
    event_log = path.with_suffix(".events.jsonl")
    if path.exists():
        ledger = Ledger.load(path, resource_scale=args.scale, event_log=event_log)
    else:
        ledger = Ledger(MemoryStore(), resource_scale=args.scale, event_log=event_log)
    store = ledger.store

    out: dict[str, object]
    save = True
    if args.ledger_op == "decide":
        ticket = ledger.decide(args.question, k=args.k)
        out = {
            # All three fields key on provenance, the silence signal,
            # so consumers never see a ticket without an answer or
            # vice versa.
            "answer": ticket.answer if ticket.provenance else None,
            "ticket_id": ticket.id if ticket.provenance else None,
            "silent": not ticket.provenance,
        }
    elif args.ledger_op == "settle":
        landed = ledger.settle(args.ticket_id, args.delta, detail=args.detail)
        out = {"settled": landed}
    elif args.ledger_op == "abandon":
        out = {"abandoned": ledger.abandon(args.ticket_id)}
    elif args.ledger_op == "add":
        question, answer = args.question.strip(), args.answer.strip()
        if not question or not answer:
            print(
                "error: add requires a non-empty question and answer",
                file=sys.stderr,
            )
            return 1
        out = {"entry_id": ledger.add(question, answer, source=args.source).id}
    elif args.ledger_op == "forget":
        status = ledger.forget(args.entry_id)
        out = {"forgotten": status == "buried"}
        if status == "escrowed":
            out["reason"] = "escrowed by a pending ticket"
    elif args.ledger_op == "tick":
        out = ledger.tick(expire_after=args.expire_after)
    elif args.ledger_op == "stats":
        save = False
        out = {
            "alive": len(store),
            "graveyard": store.dead_count(),
            "pending_tickets": len(ledger.pending()),
            "total_energy": round(store.total_energy(), 3),
            "energy_share_by_kind": {
                k: round(v, 3) for k, v in store.energy_share_by_kind().items()
            },
        }
    else:  # obituary
        save = False
        out = {"obituary": ledger.obituary(args.entry_id)}

    if save:
        ledger.save(path)
    print(json.dumps(out))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="darwin-memo",
        description="Self-curating memory for LLM agents.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="watch a poisoned entry go extinct")
    demo.add_argument("--cycles", type=int, default=30)
    demo.add_argument("-o", "--out", default=None, help="save survivors to a file")
    demo.set_defaults(fn=cmd_demo)

    encode = sub.add_parser("encode", help="encode text files into a memory")
    encode.add_argument("documents", nargs="+")
    encode.add_argument("-o", "--out", default="memory.json")
    encode.set_defaults(fn=cmd_encode)

    query = sub.add_parser("query", help="ask a saved memory a question")
    query.add_argument("memory")
    query.add_argument("question")
    query.add_argument(
        "--model",
        default=None,
        help="LLM for the full 3-stage protocol: ollama:NAME or anthropic:NAME "
        "(default: local retrieval, no model)",
    )
    query.set_defaults(fn=cmd_query)

    stats = sub.add_parser("stats", help="population and energy overview")
    stats.add_argument("memory")
    stats.set_defaults(fn=cmd_stats)

    ledger = sub.add_parser(
        "ledger",
        help="decide/settle/tick as subcommands with JSON output, for scripts",
    )
    ledger.add_argument("memory", help="ledger file; created on first use")
    ledger.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="resource_scale for settle deltas (default 1.0)",
    )
    ledger.set_defaults(fn=cmd_ledger)
    lsub = ledger.add_subparsers(dest="ledger_op", required=True)

    decide = lsub.add_parser("decide", help="answer a query, open a ticket")
    decide.add_argument("question")
    decide.add_argument("-k", type=int, default=3, help="entries to retrieve")

    settle = lsub.add_parser("settle", help="report a ticket's measured outcome")
    settle.add_argument("ticket_id")
    settle.add_argument("delta", type=float, help="a measurement, never a grade")
    settle.add_argument("--detail", default="")

    abandon = lsub.add_parser("abandon", help="release a ticket never acted on")
    abandon.add_argument("ticket_id")

    add = lsub.add_parser("add", help="write a new entry at spawn energy")
    add.add_argument("question")
    add.add_argument("answer")
    add.add_argument("--source", default="agent")

    forget = lsub.add_parser("forget", help="bury an entry by id")
    forget.add_argument("entry_id")

    tick = lsub.add_parser("tick", help="upkeep, deaths, consolidation, expiry")
    tick.add_argument("--expire-after", type=int, default=50)

    lsub.add_parser("stats", help="population overview as JSON")

    obituary = lsub.add_parser("obituary", help="why did this entry die?")
    obituary.add_argument("entry_id")

    register_observe_commands(sub)
    register_render_command(sub)
    add_settle_ci_parser(sub)
    register_mcp_command(sub)

    args = parser.parse_args(argv)
    result: int = args.fn(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
