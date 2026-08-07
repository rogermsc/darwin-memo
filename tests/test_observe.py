"""Observability: top, why, audit, and event-log rotation."""

import json

import pytest

from darwin_memo import Ledger, MemoryEntry, MemoryStore
from darwin_memo.cli import main as cli_main
from darwin_memo.diagnose import Finding, selection_findings
from darwin_memo.observe import (
    audit_digest,
    economics,
    filter_events,
    read_events,
    timeline,
)


def seeded_ledger(tmp_path, upkeep=0.05):
    """A two-entry ledger writing the CLI's event-log sibling file."""
    memory = tmp_path / "memory.json"
    store = MemoryStore(upkeep=upkeep)
    store.add(
        MemoryEntry(
            question="Is the schema helper load-bearing?",
            answer="The schema helper is load-bearing and must be kept.",
            sources=["runbook"],
        )
    )
    store.add(
        MemoryEntry(
            question="What about stale feature flags?",
            answer="Stale feature flags are redundant and safe to remove.",
            sources=["forum-post"],
        )
    )
    ledger = Ledger(
        store, resource_scale=1.0, event_log=memory.with_suffix(".events.jsonl")
    )
    return memory, ledger


def _json_out(capsys, argv):
    assert cli_main(argv) == 0
    return json.loads(capsys.readouterr().out)


def test_top_ranks_by_balance_with_json_shape(tmp_path, capsys):
    memory, ledger = seeded_ledger(tmp_path)
    ticket = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=5.0, detail="cleanup went fine")
    ledger.tick()
    ledger.save(memory)

    payload = _json_out(capsys, ["top", str(memory), "--json"])
    balances = [e["balance"] for e in payload["entries"]]
    assert balances == sorted(balances, reverse=True)
    first = payload["entries"][0]
    assert first["id"] == ticket.deciding_entry, "the credited entry leads"
    assert {
        "id",
        "balance",
        "kind",
        "sources",
        "age_ticks",
        "last_settled_tick",
        "uses",
        "question",
    } <= set(first)
    assert first["last_settled_tick"] == 0 and first["age_ticks"] == 1

    # The human table carries the same leader, and --limit truncates.
    assert cli_main(["top", str(memory), "--limit", "1"]) == 0
    table = capsys.readouterr().out
    assert first["id"] in table
    assert payload["entries"][1]["id"] not in table


def test_top_missing_file_errors(tmp_path, capsys):
    assert cli_main(["top", str(tmp_path / "nope.json")]) == 1
    assert "not found" in capsys.readouterr().err


def test_why_living_entry_tells_the_full_story(tmp_path, capsys):
    memory, ledger = seeded_ledger(tmp_path)
    entry = ledger.add(
        "Is the bridge safe?", "The bridge is safe to use.", source="patrol"
    )
    ticket = ledger.decide("is the bridge safe to use?")
    ledger.settle(ticket.id, delta=2.0, detail="crossed fine")
    ledger.save(memory)

    life = _json_out(capsys, ["why", str(memory), entry.id, "--json"])
    assert life["status"] == "living" and life["cause_of_death"] is None
    assert life["birth"]["source"] == "patrol" and life["birth"]["stake"] == 1.0
    (settlement,) = life["settlements"]
    assert settlement["delta"] == 2.0 and settlement["detail"] == "crossed fine"
    assert settlement["credit"] > 0 and settlement["ticket"] == ticket.id

    assert cli_main(["why", str(memory), entry.id]) == 0
    text = capsys.readouterr().out
    assert "credit" in text and "crossed fine" in text and "born at tick" in text


def test_why_culled_entry_reads_from_the_graveyard(tmp_path, capsys):
    memory, ledger = seeded_ledger(tmp_path, upkeep=1.0)
    ticket = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=-10.0, detail="deleting flags broke prod")
    ledger.tick()
    ledger.save(memory)
    assert ticket.deciding_entry is not None
    assert ledger.store.get(ticket.deciding_entry) is None, "the verdict killed it"

    life = _json_out(capsys, ["why", str(memory), ticket.deciding_entry, "--json"])
    assert life["status"] == "dead"
    assert life["cause_of_death"] == "executed"
    assert life["settlements"][0]["delta"] == -10.0
    assert life["balance"] is not None and life["balance"] <= 0

    assert cli_main(["why", str(memory), ticket.deciding_entry]) == 0
    assert "cause of death: executed" in capsys.readouterr().out


def test_why_unknown_entry_errors(tmp_path, capsys):
    memory, ledger = seeded_ledger(tmp_path)
    ledger.save(memory)
    assert cli_main(["why", str(memory), "nonexistent"]) == 1
    assert "unknown" in capsys.readouterr().err


def test_why_renders_legacy_string_history_as_unknown(tmp_path, capsys):
    """Files saved before structured notes must not crash the life view."""
    memory, ledger = seeded_ledger(tmp_path)
    entry_id = ledger.store.alive()[0].id
    ledger.save(memory)
    payload = json.loads(memory.read_text())
    payload["ledger"]["history"] = {
        entry_id: ["tick 1: credit +0.300 (measured delta +2)"]
    }
    memory.write_text(json.dumps(payload))

    life = _json_out(capsys, ["why", str(memory), entry_id, "--json"])
    assert life["settlements"] == [], "legacy text carries no structured settlement"
    assert life["birth"]["stake"] is None, "unknown, not invented"
    assert life["events"] == [{"text": "tick 1: credit +0.300 (measured delta +2)"}]

    assert cli_main(["why", str(memory), entry_id]) == 0
    out = capsys.readouterr().out
    assert "stake unknown" in out and "credit +0.300" in out


def test_audit_digest_math_on_synthetic_events():
    ts = "2026-06-01T00:00:00+00:00"
    events = [
        {"event": "add", "tick": 0, "ts": ts, "entry": "aaa"},
        {"event": "decide", "tick": 0, "ts": ts, "silent": False},
        {"event": "decide", "tick": 0, "ts": ts, "silent": True},
        {
            "event": "settle",
            "tick": 0,
            "ts": ts,
            "ticket": "t1",
            "delta": 4.0,
            "applied": [
                {"entry": "aaa", "credit": 0.5},
                {"entry": "bbb", "credit": 0.125},
            ],
            "buried": [],
        },
        {
            "event": "settle",
            "tick": 1,
            "ts": ts,
            "ticket": "t2",
            "delta": -8.0,
            "applied": [{"entry": "bbb", "credit": -0.6}],
            "buried": ["bbb"],
        },
        {"event": "settle", "tick": 1, "ticket": "t0", "delta": 1.0},  # legacy shape
        {"event": "settle_dropped", "tick": 1, "ts": ts, "ticket": "t1", "delta": 4.0},
        {"event": "forget", "tick": 1, "ts": ts, "entry": "ccc"},
        {
            "event": "tick",
            "tick": 2,
            "ts": "2026-06-02T00:00:00+00:00",
            "deaths": 1,
            "merges": 2,
            "expired": 1,
            "dead_entries": ["ddd"],
        },
    ]
    digest = audit_digest(events)

    assert digest["events"] == 9
    assert digest["decides"] == {"total": 2, "silent": 1}
    assert digest["settles"]["landed"] == 3 and digest["settles"]["dropped"] == 1
    assert digest["settles"]["untracked"] == 1, "legacy settle has no applied credits"
    assert digest["settles"]["delta_total"] == pytest.approx(-3.0)
    assert digest["energy"]["credited"] == pytest.approx(0.625)
    assert digest["energy"]["debited"] == pytest.approx(0.6)
    assert digest["energy"]["net"] == pytest.approx(0.025)
    assert digest["merges"] == 2 and digest["expired"] == 1
    assert digest["culled"]["entries"] == ["bbb", "ccc", "ddd"]
    assert [g["entry"] for g in digest["top_gainers"]] == ["aaa"]
    # The poisoned entry's rise and death in one place: bbb earned, then
    # drained negative and was buried on settle.
    assert [(lo["entry"], lo["net"]) for lo in digest["top_losers"]] == [
        ("bbb", pytest.approx(-0.475))
    ]
    assert digest["window"]["first_ts"] == ts
    assert digest["window"]["last_ts"] == "2026-06-02T00:00:00+00:00"
    assert digest["window"]["last_tick"] == 2


def test_filter_events_since_and_last():
    events = [
        {"event": "tick", "tick": i, "ts": f"2026-06-0{i}T00:00:00+00:00"}
        for i in range(1, 5)
    ] + [{"event": "tick", "tick": 9}]  # legacy record without a timestamp

    since = filter_events(events, since="2026-06-03T00:00:00+00:00")
    assert [e["tick"] for e in since] == [3, 4], "no ts means outside any window"
    assert [e["tick"] for e in filter_events(events, last=2)] == [4, 9]
    assert filter_events(events) == events


def test_read_events_spans_rotated_files_oldest_first(tmp_path):
    log = tmp_path / "m.events.jsonl"
    (tmp_path / "m.events.jsonl.2").write_text('{"event": "tick", "tick": 1}\n')
    (tmp_path / "m.events.jsonl.1").write_text(
        '{"event": "tick", "tick": 2}\nnot json, a torn write\n'
    )
    log.write_text('{"event": "tick", "tick": 3}\n')

    assert [e["tick"] for e in read_events(log)] == [1, 2, 3]


def test_event_log_rotation_keeps_bounded_files_audit_reads_all(tmp_path, capsys):
    memory = tmp_path / "memory.json"
    log = memory.with_suffix(".events.jsonl")
    store = MemoryStore()
    store.add(MemoryEntry(question="Is X safe?", answer="X is safe.", sources=["doc"]))
    ledger = Ledger(
        store,
        resource_scale=1.0,
        event_log=log,
        event_log_max_bytes=400,
        event_log_keep=2,
    )
    for _ in range(20):
        ticket = ledger.decide("is X safe?")
        ledger.settle(ticket.id, delta=1.0)
    ledger.save(memory)

    assert log.with_name(log.name + ".1").exists(), "rotation happened"
    assert log.with_name(log.name + ".2").exists(), "older file retained"
    assert not log.with_name(log.name + ".3").exists(), "keep=2 bounds retention"
    assert log.stat().st_size < 800, "the live file rotated instead of growing"

    events = read_events(log)
    live_lines = len(log.read_text().splitlines())
    assert len(events) > live_lines, "the audit reads across rotated files"

    digest = _json_out(capsys, ["audit", str(memory), "--json"])
    assert digest["events"] == len(events)
    assert digest["settles"]["landed"] >= 1
    assert digest["top_gainers"][0]["status"] == "living"
    assert cli_main(["audit", str(memory)]) == 0, "human digest renders"
    assert "energy flow" in capsys.readouterr().out


def test_audit_last_window(tmp_path, capsys):
    memory, ledger = seeded_ledger(tmp_path)
    ticket = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=2.0)
    ledger.tick()
    ledger.save(memory)

    digest = _json_out(capsys, ["audit", str(memory), "--json", "--last", "1"])
    assert digest["events"] == 1 and digest["ticks"] == 1, "only the tick remains"


def test_timeline_rows_track_ticks_and_bucket_settled_deltas(tmp_path):
    memory, ledger = seeded_ledger(tmp_path)
    ticket = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
    ledger.tick()
    ledger.tick()
    ledger.save(memory)

    rows = timeline(read_events(memory.with_suffix(".events.jsonl")))
    assert [r["tick"] for r in rows] == [1, 2]
    assert rows[0]["delta"] == 7.0, "settled before the first tick closed"
    assert rows[1]["delta"] == 0.0
    assert set(rows[0]) == {
        "tick",
        "population",
        "total_energy",
        "deaths",
        "merges",
        "pending",
        "delta",
    }


def test_timeline_buckets_by_write_order_not_by_tick_stamp():
    """An expiry settle shares its tick's stamp but precedes its record."""
    events = [
        {"event": "settle", "tick": 0, "delta": 5.0},
        {"event": "tick", "tick": 1, "population": 2, "total_energy": 2.0},
        {"event": "settle", "tick": 2, "delta": 3.0},
        {"event": "tick", "tick": 2, "population": 2, "total_energy": 1.9},
    ]
    rows = timeline(events)
    assert [r["tick"] for r in rows] == [1, 2]
    assert rows[0]["delta"] == 5.0
    assert rows[1]["delta"] == 3.0, (
        "an expiry settlement carries the tick it happened inside, so it "
        "belongs to that row; a +1 shift would push it to a row that may "
        "not exist"
    )


def test_economics_separates_resource_from_energy(tmp_path):
    memory, ledger = seeded_ledger(tmp_path)
    ticket = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
    ledger.tick()
    ledger.save(memory)

    report = economics(read_events(memory.with_suffix(".events.jsonl")), ledger.store)
    assert report["resource"]["delta_total"] == 7.0, "world units, never energy"
    assert report["resource"]["decides"] == 1
    assert report["energy"]["credited"] > 0
    assert report["energy"]["upkeep_paid"] == pytest.approx(
        report["population"]["alive"] * 0.05
    ), "one tick of upkeep for the surviving population"
    assert report["energy"]["upkeep_exact"] is False
    assert report["energy"]["upkeep_caveat"] == "", "no pinned entries in this store"


def test_mcp_memory_audit_matches_cli_digest(tmp_path, capsys):
    pytest.importorskip("mcp.server.fastmcp")
    import asyncio

    from darwin_memo.mcp_server import build_server

    path = tmp_path / "memory.json"
    server = build_server(path, resource_scale=2.0)

    async def scenario():
        tools = {t.name for t in await server.list_tools()}
        assert "memory_audit" in tools

        await server.call_tool(
            "memory_add",
            {"question": "Is X safe?", "answer": "X is safe.", "source": "doc"},
        )
        blocks, _ = await server.call_tool("memory_query", {"query": "is X safe?"})
        payload = json.loads(blocks[0].text)
        await server.call_tool(
            "memory_settle", {"ticket_id": payload["ticket_id"], "delta": 3.0}
        )
        blocks, _ = await server.call_tool("memory_audit", {})
        return json.loads(blocks[0].text)

    digest = asyncio.run(scenario())
    assert digest["decides"]["total"] == 1
    assert digest["settles"]["landed"] == 1
    assert digest["energy"]["credited"] > 0

    # Same digest shape and numbers as the CLI command over the same file.
    cli_digest = _json_out(capsys, ["audit", str(path), "--json"])
    assert cli_digest == digest


def test_silent_majority_fires_and_suppresses_the_never_paid_rule():
    findings = selection_findings(
        decides=100, silent=95, nonzero_outcomes=0, settles=100
    )
    assert [f.code for f in findings] == ["silent_majority"], (
        "silence is the actionable diagnosis; a silent store obviously "
        "never earned, and reporting both buries the useful one"
    )
    assert findings[0].severity == "error"


def test_never_paid_reads_gross_movement_not_net():
    # Payouts that exactly cancel DID pay out: the environment works.
    findings = selection_findings(
        decides=100, silent=0, nonzero_outcomes=6, settles=100
    )
    assert findings == []
    findings = selection_findings(
        decides=100, silent=0, nonzero_outcomes=0, settles=100
    )
    assert [f.code for f in findings] == ["env_never_paid"]


def test_small_runs_are_not_declared_broken():
    assert selection_findings(decides=3, silent=3, nonzero_outcomes=0, settles=3) == []


def test_finding_serializes_to_flat_strings():
    finding = Finding("c", "warn", "s", "e", "f")
    assert finding.as_dict() == {
        "code": "c",
        "severity": "warn",
        "summary": "s",
        "evidence": "e",
        "fix": "f",
    }


def test_health_warning_speaks_through_the_shared_rules():
    """The batch report must not drift from the shared predicates."""
    from darwin_memo.survival import SurvivalReport
    from darwin_memo.types import CycleStats

    quiet = SurvivalReport(
        stats=[
            CycleStats(
                cycle=c,
                population=5,
                births=0,
                deaths=0,
                merges=0,
                total_energy=5.0,
                resource_delta=0.0,
                tasks=10,
                silent=10,
                nonzero_outcomes=0,
            )
            for c in range(3)
        ]
    )
    findings = selection_findings(decides=30, silent=30, nonzero_outcomes=0, settles=30)
    assert quiet.health_warning() == (
        "\n\nWARNING: " + f"{findings[0].summary}: {findings[0].fix}"
    )

    small = SurvivalReport(
        stats=[
            CycleStats(
                cycle=c,
                population=5,
                births=0,
                deaths=0,
                merges=0,
                total_energy=5.0,
                resource_delta=1.0,
                tasks=3,
                silent=3,
                # A nonzero outcome keeps this isolated to the MIN_DECIDES
                # floor: at 9 settles (>= MIN_SETTLES=5) an all-zero
                # outcome sum would trip env_never_paid instead, which
                # isn't the floor this case is meant to exercise.
                nonzero_outcomes=1,
            )
            for c in range(3)
        ]
    )
    # Below MIN_DECIDES: the old hand-rolled rule warned here, the
    # shared rule must not.
    assert small.health_warning() == ""

    healthy = SurvivalReport(
        stats=[
            CycleStats(
                cycle=c,
                population=5,
                births=0,
                deaths=0,
                merges=0,
                total_energy=5.0,
                resource_delta=12.0,
                tasks=10,
                silent=1,
                nonzero_outcomes=9,
            )
            for c in range(3)
        ]
    )
    assert healthy.health_warning() == ""
