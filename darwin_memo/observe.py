"""Observability commands: the audit surface over what the engine records.

    darwin-memo top FILE [--limit N] [--json]               leaderboard
    darwin-memo why FILE ENTRY_ID [--json]                  one life story
    darwin-memo audit FILE [--since TS] [--last N] [--json] event digest

All three are read-only presentation over data the Ledger already
keeps: the living population, the graveyard, per-entry history notes
persisted in the memory file, and the JSONL event log (read across
rotated files, see :func:`darwin_memo.ledger.event_log_paths`). The
audit digest is the anti-poisoning trail: a poisoned entry's rise shows
up under top gainers while it earns, its negative settlements put it
under top losers, and its burial lands in the cull list, with nothing
but measured settlements in between.

Files saved by older versions lack timestamps and structured history;
missing fields render as unknown (None in JSON) instead of crashing.
``register_observe_commands`` attaches the subparsers so cli.py stays
one import plus one call.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .ledger import Ledger, note_text
from .store import MemoryStore
from .types import MemoryEntry

_TOP_MOVERS = 5  # gainers and losers listed in the audit digest


# ----------------------------------------------------------------------
# top: living entries ranked by balance
# ----------------------------------------------------------------------


def _top_row(entry: MemoryEntry, tick: int) -> dict[str, Any]:
    return {
        "id": entry.id,
        "balance": round(entry.energy, 3),
        "kind": entry.kind.value,
        "sources": list(entry.sources),
        "born_tick": entry.born_cycle,
        "age_ticks": max(0, tick - entry.born_cycle),
        "last_settled_tick": (
            entry.last_used_cycle if entry.last_used_cycle >= 0 else None
        ),
        "uses": entry.uses,
        "pinned": entry.pinned,
        "probation": entry.probation,
        "question": entry.question,
    }


def cmd_top(args: argparse.Namespace) -> int:
    ledger = _load_ledger(args.memory)
    if ledger is None:
        return 1
    ranked = sorted(ledger.store.alive(), key=lambda e: e.energy, reverse=True)
    rows = [_top_row(entry, ledger.tick_count) for entry in ranked[: args.limit]]
    if args.json:
        print(
            json.dumps(
                {
                    "tick": ledger.tick_count,
                    "alive": len(ledger.store),
                    "entries": rows,
                }
            )
        )
        return 0
    if not rows:
        print("no living entries")
        return 0
    print(
        f"{'balance':>8} {'id':>12} {'kind':>12} {'age':>5} {'settled':>8}"
        "  source / question"
    )
    for row in rows:
        settled = (
            "never"
            if row["last_settled_tick"] is None
            else f"t{row['last_settled_tick']}"
        )
        source = ",".join(row["sources"]) or "-"
        flags = ""
        if row["pinned"]:
            flags += " [pinned]"
        if row["probation"]:
            flags += f" [probation {row['probation']}]"
        print(
            f"{row['balance']:>8.3f} {row['id']:>12} {row['kind']:>12} "
            f"{row['age_ticks']:>5} {settled:>8}  [{source}] "
            f"{row['question'][:48]}{flags}"
        )
    return 0


# ----------------------------------------------------------------------
# why: one entry's full life story, dead or alive
# ----------------------------------------------------------------------


def _event_payload(event: str | dict[str, Any]) -> dict[str, Any]:
    """Normalize one history note; legacy saves stored plain strings."""
    if isinstance(event, str):
        return {"text": event}
    return dict(event)


def _cause_of_death(events: list[dict[str, Any]], merged: bool) -> str:
    """Read the cause from structured notes, fall back to text, then unknown."""
    if merged:
        return "merged"
    for event in reversed(events):
        if event.get("event") in ("death", "buried") and "cause" in event:
            return str(event["cause"])
    for event in reversed(events):
        text = str(event.get("text", ""))
        for cause in ("executed", "starved", "forget"):
            if cause in text:
                return "forgotten" if cause == "forget" else cause
    return "unknown"


def entry_life(ledger: Ledger, entry_id: str) -> dict[str, Any] | None:
    """One entry's story: birth, every settlement, merges, death.

    Works for dead entries through the graveyard, which only grows.
    Returns None when the id is unknown to the store entirely.
    """
    store = ledger.store
    entry = store.get(entry_id) or store.get_dead(entry_id)
    heirs = [e for e in store.alive() + store.graveyard() if entry_id in e.lineage]
    if entry is None and not heirs:
        return None

    events = [_event_payload(e) for e in ledger.history(entry_id)]
    settlements = [e for e in events if e.get("event") == "settle"]
    birth = next((e for e in events if e.get("event") == "birth"), None)
    living = store.get(entry_id) is not None
    status = "living" if living else ("merged" if heirs else "dead")
    return {
        "id": entry_id,
        "status": status,
        "question": entry.question if entry else None,
        "answer": entry.answer if entry else None,
        "kind": entry.kind.value if entry else None,
        "sources": list(entry.sources) if entry else [],
        "balance": round(entry.energy, 3) if entry else None,
        "uses": entry.uses if entry else None,
        "pinned": entry.pinned if entry else False,
        "probation": entry.probation if entry else 0,
        "juvenile": entry.juvenile if entry else 0,
        "birth": {
            "tick": entry.born_cycle if entry else None,
            "ts": (birth or {}).get("ts"),
            "source": (birth or {}).get("source")
            or (entry.sources[0] if entry and entry.sources else None),
            "stake": (birth or {}).get("stake"),
        },
        "settlements": settlements,
        "merged_into": heirs[0].id if heirs else None,
        "cause_of_death": None if living else _cause_of_death(events, bool(heirs)),
        "events": events,
    }


def cmd_why(args: argparse.Namespace) -> int:
    ledger = _load_ledger(args.memory)
    if ledger is None:
        return 1
    life = entry_life(ledger, args.entry_id)
    if life is None:
        print(f"error: {args.entry_id} is unknown to this store", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(life))
        return 0

    print(f"{life['id']} [{life['kind']}] {life['status']}: {life['question']!r}")
    balance = "unknown" if life["balance"] is None else f"{life['balance']:.3f}"
    print(f"  balance={balance} uses={life['uses']}")
    if life["pinned"]:
        print("  pinned: starvation and merges cannot remove it")
    if life["probation"]:
        print(
            f"  probation: {life['probation']} net-positive settlements"
            " until it may decide"
        )
    if life["juvenile"]:
        print(f"  juvenile: {life['juvenile']} settlements left in admission window")
    birth = life["birth"]
    stake = "unknown" if birth["stake"] is None else f"{birth['stake']:g}"
    print(
        f"  born at tick {birth['tick']} "
        f"(source {birth['source'] or 'unknown'}, stake {stake})"
    )
    for event in life["events"]:
        if event.get("event") == "birth":
            continue
        print(f"  {note_text(event)}")
    if life["merged_into"]:
        print(f"  merged into {life['merged_into']}")
    if life["cause_of_death"]:
        print(f"  cause of death: {life['cause_of_death']}")
    elif life["status"] != "living" and not life["settlements"]:
        print("  no credited outcomes on record")
    return 0


# ----------------------------------------------------------------------
# audit: digest of the event log, across rotated files
# ----------------------------------------------------------------------


def read_events(log_path: Path) -> list[dict[str, Any]]:
    """All event records, oldest first, across rotated log files.

    Rotation moves full files to numeric suffixes (highest is oldest),
    so reading suffixes downward and the live file last restores append
    order. Rotated files are discovered by globbing, not by the
    writer's keep setting, so any retention config reads the same way.
    Torn or corrupt lines are skipped: an audit must survive them.
    """
    rotated: list[tuple[int, Path]] = []
    for candidate in log_path.parent.glob(f"{log_path.name}.*"):
        tail = candidate.name.rsplit(".", 1)[-1]
        if tail.isdigit():
            rotated.append((int(tail), candidate))
    records: list[dict[str, Any]] = []
    for _, path in sorted(rotated, reverse=True):
        records.extend(_read_one_log(path))
    records.extend(_read_one_log(log_path))
    return records


def _read_one_log(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    return records


def filter_events(
    events: list[dict[str, Any]], since: str | None = None, last: int | None = None
) -> list[dict[str, Any]]:
    """Window the log: ISO timestamp floor, then last N events.

    Timestamps are UTC ISO-8601 strings, so string comparison orders
    them. Records written before timestamps existed have none and fall
    outside any --since window.
    """
    if since:
        events = [
            e for e in events if isinstance(e.get("ts"), str) and e["ts"] >= since
        ]
    if last is not None and last > 0:
        events = events[-last:]
    return events


def audit_digest(
    events: list[dict[str, Any]], store: MemoryStore | None = None
) -> dict[str, Any]:
    """Digest the event window: decisions, settlements, culls, energy flow.

    Per-entry flow comes from the ``applied`` credits on settle events;
    settles logged by older versions lack them and are counted under
    ``untracked``. When a store is given, gainers and losers carry the
    entry's question and living/dead status, so a poisoned entry's rise
    and death read off one screen.
    """
    decides = silent = settles = dropped = untracked = 0
    adds = forgets = refused = ticks = merges = expired = 0
    delta_total = credited = debited = 0.0
    flow: dict[str, float] = {}
    culled: list[str] = []
    for record in events:
        event = record.get("event")
        if event == "decide":
            decides += 1
            silent += 1 if record.get("silent") else 0
        elif event == "settle":
            settles += 1
            delta_total += float(record.get("delta") or 0.0)
            applied = record.get("applied")
            if applied is None:
                untracked += 1
            else:
                for grant in applied:
                    credit = float(grant.get("credit") or 0.0)
                    entry_id = str(grant.get("entry"))
                    flow[entry_id] = flow.get(entry_id, 0.0) + credit
                    if credit >= 0:
                        credited += credit
                    else:
                        debited += -credit
            culled.extend(str(e) for e in record.get("buried") or [])
        elif event == "settle_dropped":
            dropped += 1
        elif event == "add":
            adds += 1
        elif event == "forget":
            forgets += 1
            culled.append(str(record.get("entry")))
        elif event == "forget_refused":
            refused += 1
        elif event == "tick":
            ticks += 1
            merges += int(record.get("merges") or 0)
            expired += int(record.get("expired") or 0)
            culled.extend(str(e) for e in record.get("dead_entries") or [])

    def mover(entry_id: str, net: float) -> dict[str, Any]:
        described: dict[str, Any] = {"entry": entry_id, "net": round(net, 6)}
        if store is not None:
            entry = store.get(entry_id) or store.get_dead(entry_id)
            if entry is not None:
                described["question"] = entry.question
                described["status"] = "living" if store.get(entry_id) else "dead"
        return described

    movers = sorted(flow.items(), key=lambda kv: kv[1], reverse=True)
    gainers = [(e, net) for e, net in movers if net > 0][:_TOP_MOVERS]
    losers = [(e, net) for e, net in reversed(movers) if net < 0][:_TOP_MOVERS]
    culled_once = list(dict.fromkeys(culled))
    timestamps = [r["ts"] for r in events if isinstance(r.get("ts"), str)]
    tick_marks = [r["tick"] for r in events if isinstance(r.get("tick"), int)]
    return {
        "events": len(events),
        "window": {
            "first_ts": timestamps[0] if timestamps else None,
            "last_ts": timestamps[-1] if timestamps else None,
            "first_tick": tick_marks[0] if tick_marks else None,
            "last_tick": tick_marks[-1] if tick_marks else None,
        },
        "decides": {"total": decides, "silent": silent},
        "settles": {
            "landed": settles,
            "dropped": dropped,
            "delta_total": round(delta_total, 6),
            "untracked": untracked,
        },
        "adds": adds,
        "forgets": {"buried": forgets, "refused": refused},
        "ticks": ticks,
        "merges": merges,
        "expired": expired,
        "energy": {
            "credited": round(credited, 6),
            "debited": round(debited, 6),
            "net": round(credited - debited, 6),
        },
        "culled": {"count": len(culled_once), "entries": culled_once},
        "top_gainers": [mover(e, net) for e, net in gainers],
        "top_losers": [mover(e, net) for e, net in losers],
    }


def timeline(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per tick record, with settled deltas bucketed by tick.

    Rows carry whatever tick records the log still holds; a rotated log
    leaves a gap in the tick numbers, which callers plot on a numeric
    axis so the gap shows as a gap rather than an interpolated line.
    """
    delta_by_tick: dict[int, float] = {}
    for record in events:
        if record.get("event") == "settle" and isinstance(record.get("tick"), int):
            tick = int(record["tick"]) + 1
            delta_by_tick[tick] = delta_by_tick.get(tick, 0.0) + float(
                record.get("delta") or 0.0
            )
    rows: list[dict[str, Any]] = []
    for record in events:
        if record.get("event") != "tick":
            continue
        tick = int(record.get("tick") or 0)
        rows.append(
            {
                "tick": tick,
                "population": int(record.get("population") or 0),
                "total_energy": float(record.get("total_energy") or 0.0),
                "deaths": int(record.get("deaths") or 0),
                "merges": int(record.get("merges") or 0),
                "pending": int(record.get("pending") or 0),
                "delta": round(delta_by_tick.get(tick, 0.0), 6),
            }
        )
    return rows


def economics(events: list[dict[str, Any]], store: MemoryStore) -> dict[str, Any]:
    """Two currencies, reported separately and never summed.

    The **resource** ledger is the real case: settled deltas in world
    units (bytes, passing tests, dollars), with decide and silence
    counts so coverage is visible — the same delta over three decisions
    and over three hundred are not the same claim. The **energy** ledger
    is the internal, dimensionless mechanism. Adding one to the other
    would be adding bytes to tanh output.

    Upkeep is estimated as population x upkeep. Every alive entry pays
    each tick (``MemoryStore.charge_upkeep``: ``protect`` and ``pinned``
    change burial and flooring, not the charge), so the estimate is
    exact except that a pinned entry sitting at zero has its charge
    forgiven by the floor.
    """
    digest = audit_digest(events, store=store)
    rows = timeline(events)
    upkeep_paid = round(sum(r["population"] for r in rows) * store.upkeep, 6)
    pinned = sum(1 for entry in store.alive() if entry.pinned)
    caveat = (
        f"estimated as population x upkeep; {pinned} pinned "
        "entries may have had a charge forgiven at the zero floor"
        if pinned
        else ""
    )
    return {
        "resource": {
            "delta_total": digest["settles"]["delta_total"],
            "decides": digest["decides"]["total"],
            "silent": digest["decides"]["silent"],
            "settles": digest["settles"]["landed"],
        },
        "energy": {
            "credited": digest["energy"]["credited"],
            "debited": digest["energy"]["debited"],
            "net": digest["energy"]["net"],
            "upkeep_paid": upkeep_paid,
            "upkeep_exact": False,
            "upkeep_caveat": caveat,
        },
        "population": {"alive": len(store), "dead": len(store.graveyard())},
    }


def cmd_audit(args: argparse.Namespace) -> int:
    ledger = _load_ledger(args.memory)
    if ledger is None:
        return 1
    log = Path(args.memory).expanduser().with_suffix(".events.jsonl")
    events = filter_events(read_events(log), since=args.since, last=args.last)
    digest = audit_digest(events, store=ledger.store)
    if args.json:
        print(json.dumps(digest))
        return 0

    window = digest["window"]
    print(
        f"events: {digest['events']}  "
        f"window: {window['first_ts'] or 'unknown'} .. "
        f"{window['last_ts'] or 'unknown'} "
        f"(ticks {window['first_tick']}..{window['last_tick']})"
    )
    decides, settles = digest["decides"], digest["settles"]
    print(
        f"decides: {decides['total']} ({decides['silent']} silent)  "
        f"settles: {settles['landed']} landed, {settles['dropped']} dropped, "
        f"delta total {settles['delta_total']:+g}"
    )
    print(
        f"adds: {digest['adds']}  forgets: {digest['forgets']['buried']}  "
        f"ticks: {digest['ticks']}  merges: {digest['merges']}  "
        f"culled: {digest['culled']['count']}"
    )
    energy = digest["energy"]
    print(
        f"energy flow: +{energy['credited']:.3f} / -{energy['debited']:.3f} "
        f"(net {energy['net']:+.3f})"
    )
    for label, movers in (
        ("top gainers", digest["top_gainers"]),
        ("top losers", digest["top_losers"]),
    ):
        if movers:
            print(f"{label}:")
            for moved in movers:
                question = str(moved.get("question", ""))[:48]
                status = moved.get("status", "unknown")
                print(f"  {moved['net']:+.3f}  {moved['entry']} [{status}] {question}")
    if digest["culled"]["entries"]:
        print("culled: " + ", ".join(digest["culled"]["entries"]))
    return 0


# ----------------------------------------------------------------------


def _load_ledger(memory: str) -> Ledger | None:
    """Read-only load; commands here never save or append to the log."""
    path = Path(memory).expanduser()
    if not path.exists():
        print(f"error: {memory} not found", file=sys.stderr)
        return None
    return Ledger.load(path)


def register_observe_commands(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Attach top/why/audit, so cli.py stays one import plus one call."""
    top = sub.add_parser("top", help="living entries ranked by balance")
    top.add_argument("memory")
    top.add_argument("--limit", type=int, default=10, help="entries shown (default 10)")
    top.add_argument("--json", action="store_true", help="machine-readable output")
    top.set_defaults(fn=cmd_top)

    why = sub.add_parser("why", help="one entry's full life story, dead or alive")
    why.add_argument("memory")
    why.add_argument("entry_id")
    why.add_argument("--json", action="store_true", help="machine-readable output")
    why.set_defaults(fn=cmd_why)

    audit = sub.add_parser("audit", help="event-log digest: the audit trail")
    audit.add_argument("memory")
    audit.add_argument(
        "--since", default=None, help="ISO-8601 UTC timestamp floor (string compare)"
    )
    audit.add_argument("--last", type=int, default=None, help="only the last N events")
    audit.add_argument("--json", action="store_true", help="machine-readable output")
    audit.set_defaults(fn=cmd_audit)
