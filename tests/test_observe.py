"""Observability: top, why, audit, and event-log rotation."""

import json

import pytest

from darwin_memo import Ledger, MemoryEntry, MemoryStore
from darwin_memo.cli import main as cli_main
from darwin_memo.diagnose import MIN_DEATHS, STARVED_SHARE, Finding, selection_findings
from darwin_memo.observe import (
    _starved_unused,
    audit_digest,
    doctor,
    economics,
    entry_life,
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


def test_one_definition_across_cli_and_api(tmp_path, capsys):
    """top, why and /api/state must not be able to disagree."""
    memory, ledger = seeded_ledger(tmp_path)
    ledger.save(memory)
    entry = ledger.store.alive()[0]
    expected = ledger.store.ticks_to_starvation(entry)

    top = _json_out(capsys, ["top", str(memory), "--json"])
    row = next(r for r in top["entries"] if r["id"] == entry.id)
    assert row["ticks_to_starvation"] == expected

    life = entry_life(ledger, entry.id)
    assert life is not None
    assert life["ticks_to_starvation"] == expected


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


def test_timeline_carries_a_trailing_settle_as_an_open_row(tmp_path):
    """I-3: a settlement after the last tick record must not be dropped
    -- it gets its own trailing, explicitly-labelled open-interval row
    instead of silently vanishing or being folded into a closed tick's
    bucket (which would misattribute it to a tick it did not happen
    inside)."""
    memory, ledger = seeded_ledger(tmp_path)
    ticket = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
    ledger.tick()
    trailing = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(trailing.id, delta=9999.0, detail="late settle, no tick yet")
    ledger.save(memory)

    events = _events(memory)
    rows = timeline(events)
    assert [r["tick"] for r in rows] == [1, 2], "the open row is numbered one past 1"
    assert rows[0]["delta"] == 7.0, "unaffected: this row already closed"
    assert rows[-1] == {
        "tick": 2,
        "population": None,
        "total_energy": None,
        "deaths": None,
        "merges": None,
        "pending": None,
        "delta": 9999.0,
        "open": True,
    }

    report = economics(events, ledger.store)
    assert sum(r["delta"] for r in rows) == report["resource"]["delta_total"], (
        "the Timeline data and the Economics headline must agree on the "
        "same window: dropping the trailing settle used to make them "
        "disagree by exactly its amount"
    )


def test_timeline_without_a_trailing_settle_has_no_open_row(tmp_path):
    """Negative direction for I-3: nothing to carry forward means no
    synthetic row -- the fix must not manufacture rows that were never
    dropped in the first place."""
    memory, ledger = seeded_ledger(tmp_path)
    ticket = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
    ledger.tick()
    ledger.save(memory)

    rows = timeline(_events(memory))
    assert all("open" not in row for row in rows)


def test_economics_upkeep_paid_ignores_the_open_trailing_row(tmp_path):
    """The open row has no population (nothing has been measured for it
    yet); it must not crash or silently count as zero-population upkeep
    for a tick that has not happened."""
    memory, ledger = seeded_ledger(tmp_path)
    ticket = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
    ledger.tick()
    trailing = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(trailing.id, delta=3.0, detail="late")
    ledger.save(memory)

    events = _events(memory)
    report = economics(events, ledger.store)
    assert report["energy"]["upkeep_paid"] == pytest.approx(
        report["population"]["alive"] * 0.05
    ), "one closed tick of upkeep, same as with no trailing settle at all"


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
    assert report["energy"]["upkeep_exact"] is True, (
        "a fresh log carries upkeep_charged on every tick record"
    )
    assert report["energy"]["upkeep_caveat"] == "", "no pinned entries in this store"


def _events(memory):
    return read_events(memory.with_suffix(".events.jsonl"))


def test_economics_prefers_the_logged_figure(tmp_path):
    memory, ledger = seeded_ledger(tmp_path)
    ledger.tick()
    ledger.save(memory)
    report = economics(read_events(memory.with_suffix(".events.jsonl")), ledger.store)
    assert report["energy"]["upkeep_exact"] is True
    assert report["energy"]["upkeep_caveat"] == ""


def test_economics_falls_back_on_a_legacy_log(tmp_path):
    """A log written before this release must still report the old number."""
    memory, ledger = seeded_ledger(tmp_path)
    ledger.tick()
    ledger.save(memory)
    log = memory.with_suffix(".events.jsonl")
    stripped = []
    for record in read_events(log):
        record.pop("upkeep_charged", None)
        stripped.append(record)
    log.write_text("\n".join(json.dumps(r) for r in stripped) + "\n")

    report = economics(read_events(log), ledger.store)
    assert report["energy"]["upkeep_exact"] is False
    assert report["energy"]["upkeep_paid"] == pytest.approx(
        len(ledger.store) * ledger.store.upkeep
    )


def test_doctor_is_clean_on_a_healthy_store(tmp_path):
    memory, ledger = seeded_ledger(tmp_path)
    for _ in range(6):
        ticket = ledger.decide("are stale feature flags safe to remove?")
        ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
        ledger.tick()
    ledger.save(memory)
    assert doctor(ledger, _events(memory)) == []


def test_doctor_names_an_environment_that_never_paid(tmp_path):
    memory, ledger = seeded_ledger(tmp_path)
    for _ in range(6):
        ticket = ledger.decide("are stale feature flags safe to remove?")
        ledger.settle(ticket.id, delta=0.0, detail="nothing happened")
        ledger.tick()
    ledger.save(memory)
    codes = [f.code for f in doctor(ledger, _events(memory))]
    assert "env_never_paid" in codes
    assert "silent_majority" not in codes, "memory answered; it just never earned"


def test_doctor_flags_a_stale_ticket(tmp_path):
    memory, ledger = seeded_ledger(tmp_path)
    ledger.decide("are stale feature flags safe to remove?")
    ledger.tick_count = 500  # far past STALE_TICKET_TICKS
    ledger.save(memory)
    findings = {f.code: f for f in doctor(ledger, _events(memory))}
    assert findings["tickets_stale"].severity == "warn"


def test_doctor_cli_exits_nonzero_on_an_error_finding(tmp_path, capsys):
    memory, ledger = seeded_ledger(tmp_path)
    for _ in range(6):
        ticket = ledger.decide("are stale feature flags safe to remove?")
        ledger.settle(ticket.id, delta=0.0, detail="nothing happened")
        ledger.tick()
    ledger.save(memory)

    assert cli_main(["doctor", str(memory)]) == 1
    assert "env_never_paid" in capsys.readouterr().out

    assert cli_main(["doctor", str(memory), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["findings"][0]["code"] == "env_never_paid"


def test_doctor_cli_exits_zero_on_warnings_only(tmp_path, capsys):
    """Deferred in the final review's triage (T3): warnings alone (no
    error-severity finding) must not fail the run."""
    memory, ledger = seeded_ledger(tmp_path)
    ledger.decide("are stale feature flags safe to remove?")
    ledger.tick_count = 500  # far past STALE_TICKET_TICKS
    ledger.save(memory)

    assert cli_main(["doctor", str(memory)]) == 0
    assert "WARN [tickets_stale]" in capsys.readouterr().out


def test_doctor_does_not_call_a_cancelling_environment_dead(tmp_path):
    """Gross movement, not net: payouts that cancel still paid out."""
    memory, ledger = seeded_ledger(tmp_path)
    for delta in (7.0, -7.0, 7.0, -7.0, 7.0, -7.0):
        ticket = ledger.decide("are stale feature flags safe to remove?")
        ledger.settle(ticket.id, delta=delta, detail="measured")
        ledger.tick()
    ledger.save(memory)
    codes = [f.code for f in doctor(ledger, _events(memory))]
    assert "env_never_paid" not in codes, (
        "six settlements each moved the world; that their sum happens to "
        "be zero is not evidence the environment never paid out"
    )


_TRIVIA = [
    (
        "What color is the cafeteria wall?",
        "The cafeteria wall is painted eggshell blue.",
    ),
    (
        "Who won the office ping pong tournament?",
        "Priya won the office ping pong tournament.",
    ),
    (
        "What time does the vending machine restock?",
        "The vending machine restocks at nine each morning.",
    ),
    (
        "Where is the spare umbrella kept?",
        "The spare umbrella is kept behind the front desk.",
    ),
]


def test_starvation_cliff_does_not_fire_on_a_healthy_earning_run(tmp_path):
    """Starved trivia is a healthy death mode; a window that earned is not dead."""
    memory, ledger = seeded_ledger(tmp_path)
    for question, answer in _TRIVIA:
        ledger.add(question, answer, source="cafeteria")
    for _ in range(25):
        ticket = ledger.decide("are stale feature flags safe to remove?")
        ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
        ledger.tick()
    ledger.save(memory)

    # The trivia entries starved unused (never queried, never credited);
    # confirm this fixture actually exercises that path before trusting
    # the negative assertion below.
    starved, dead = _starved_unused(ledger)
    assert dead >= MIN_DEATHS and starved / dead >= STARVED_SHARE

    codes = [f.code for f in doctor(ledger, _events(memory))]
    assert "starvation_cliff" not in codes, (
        "the queried entry earned in this window; starved trivia in the "
        "graveyard is the mechanism working, not env_never_paid's sibling"
    )


def test_starvation_cliff_fires_when_nothing_was_ever_credited(tmp_path):
    """A population that starved AND never earned is the real failure."""
    memory, ledger = seeded_ledger(tmp_path)
    for question, answer in _TRIVIA[:2]:
        ledger.add(question, answer, source="cafeteria")
    for _ in range(25):
        ledger.tick()  # no decide/settle ever: nothing can be credited
    ledger.save(memory)

    findings = {f.code: f for f in doctor(ledger, _events(memory))}
    assert findings["starvation_cliff"].severity == "error"


def _healthy_earning_ledger(tmp_path):
    """A store that both starves trivia unused AND genuinely earns --
    the exact shape the final review reproduced C-1's four false
    positives against (a healthy 30-cycle flagship demo has the same
    two ingredients: a queried, credited population and unconsulted
    trivia that starves)."""
    memory, ledger = seeded_ledger(tmp_path)
    for question, answer in _TRIVIA:
        ledger.add(question, answer, source="cafeteria")
    for _ in range(25):
        ticket = ledger.decide("are stale feature flags safe to remove?")
        ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
        ledger.tick()
    ledger.save(memory)
    return memory, ledger


def test_doctor_stays_clean_when_the_sidecar_log_is_missing(tmp_path):
    """C-1: a store copied without its .events.jsonl must not read as
    broken. The window (an empty events list, exactly what a missing
    sidecar looks like to doctor()) is thin; the store's own persisted
    settlement history is not."""
    _memory, ledger = _healthy_earning_ledger(tmp_path)
    assert doctor(ledger, []) == [], (
        "the graveyard and its starved trivia are still visible with no "
        "event log at all, but the store genuinely earned, so nothing "
        "here is a fault"
    )


def test_doctor_stays_clean_on_a_quiet_rotated_window(tmp_path):
    """C-1: a rotated log can leave a window of ticks with no settles in
    it, even though the store earned plenty outside the window."""
    memory, ledger = _healthy_earning_ledger(tmp_path)
    events = _events(memory)
    quiet = [e for e in events if e.get("event") != "settle"]
    assert any(e.get("event") == "settle" for e in events), "fixture sanity"
    assert not any(e.get("event") == "settle" for e in quiet), "fixture sanity"
    assert doctor(ledger, quiet) == []


def test_doctor_does_not_contradict_credit_untracked_on_a_legacy_log(tmp_path):
    """C-1: a log written before settle events carried an 'applied' list
    zeroes the window's attributable credit -- credit_untracked already
    says that figure is unattributable, so starvation_cliff must not
    then read that same unattributable-and-therefore-zero figure as
    proof nothing ever earned (the review's self-contradicting screen)."""
    memory, ledger = _healthy_earning_ledger(tmp_path)
    legacy = []
    for record in _events(memory):
        if record.get("event") == "settle":
            record = {k: v for k, v in record.items() if k != "applied"}
        legacy.append(record)

    findings = {f.code: f for f in doctor(ledger, legacy)}
    assert findings["credit_untracked"].severity == "warn"
    assert "starvation_cliff" not in findings
    assert "env_never_paid" not in findings
    assert "silent_majority" not in findings
    assert all(f.severity == "warn" for f in findings.values())


def test_doctor_stays_clean_on_a_lean_mostly_silent_but_earning_store(tmp_path):
    """C-1 / silent_majority false positive: an 86%-silent store is the
    product thesis (spec Sec 2, 'stays lean and cheap'), not a fault,
    when the minority that WAS answered earned real credit."""
    memory, ledger = seeded_ledger(tmp_path)
    for _ in range(44):
        ledger.decide("completely unrelated query about kangaroos and tax law")
    for _ in range(6):
        ticket = ledger.decide("are stale feature flags safe to remove?")
        ledger.settle(ticket.id, delta=11.0, detail="measured")
    ledger.save(memory)

    events = _events(memory)
    digest = audit_digest(events, store=ledger.store)
    decides, silent = digest["decides"]["total"], digest["decides"]["silent"]
    assert decides >= 10 and silent / decides > 0.8, "fixture sanity: silent majority"
    assert digest["energy"]["credited"] > 0, "fixture sanity: it did earn"

    assert doctor(ledger, events) == []


def test_silent_majority_still_fires_on_a_genuinely_mute_store(tmp_path):
    """Both-directions proof for the silent_majority guard: a store that
    is silent-majority AND never earns anywhere (not just in-window)
    must still trip, so the earned-guard has not blunted the rule."""
    memory, ledger = seeded_ledger(tmp_path)
    for _ in range(44):
        ledger.decide("completely unrelated query about kangaroos and tax law")
    for _ in range(6):
        ticket = ledger.decide("are stale feature flags safe to remove?")
        ledger.settle(ticket.id, delta=0.0, detail="nothing happened")
    ledger.save(memory)

    events = _events(memory)
    digest = audit_digest(events, store=ledger.store)
    decides, silent = digest["decides"]["total"], digest["decides"]["silent"]
    assert decides >= 10 and silent / decides > 0.8, "fixture sanity: silent majority"

    findings = {f.code: f for f in doctor(ledger, events)}
    assert findings["silent_majority"].severity == "error"
    assert cli_main(["doctor", str(memory)]) == 1


def test_env_never_paid_ignores_ticks_own_expiry_settlements(tmp_path):
    """I-1: Ledger.tick(expire_after=...) settles expired tickets itself
    (ledger.py tick(), via settle(id, 0.0, 'expired unsettled')). Those
    are real settle events that inflate the settle count while proving
    nothing about whether the CALLER ever paid out -- six decides here
    never get an explicit settle() call at all, only tick()'s own
    expiry, so blaming decision_polarity (env_never_paid) is the wrong
    diagnosis for an unwired settle()."""
    memory, ledger = seeded_ledger(tmp_path)
    for _ in range(6):
        ledger.decide("are stale feature flags safe to remove?")
    for _ in range(60):
        ledger.tick()  # settle() is never called by the caller
    ledger.save(memory)

    events = _events(memory)
    digest = audit_digest(events, store=ledger.store)
    assert digest["expired"] >= 6, "fixture sanity: tickets actually expired"
    assert digest["settles"]["landed"] >= 6, "fixture sanity: tick() logged settles"

    codes = [f.code for f in doctor(ledger, events)]
    assert "env_never_paid" not in codes, (
        "tick()'s own zero-delta expiry settlements are not the "
        "environment refusing to pay; nobody ever called settle() here"
    )


def test_env_never_paid_still_fires_when_the_caller_explicitly_never_pays(tmp_path):
    """Both-directions proof for I-1: real caller-made zero-delta
    settlements (not tick()'s auto-expiry) must still trip
    env_never_paid, even alongside unrelated tickets that separately
    expire via tick()."""
    memory, ledger = seeded_ledger(tmp_path)
    for _ in range(6):
        ticket = ledger.decide("are stale feature flags safe to remove?")
        ledger.settle(ticket.id, delta=0.0, detail="nothing happened")
    ledger.add("Is the bridge safe?", "The bridge is safe to use.", source="patrol")
    ledger.decide("is the bridge safe to use?")  # left pending, on purpose
    for _ in range(60):
        ledger.tick()  # this one expires unsettled; the 6 above already landed
    ledger.save(memory)

    events = _events(memory)
    digest = audit_digest(events, store=ledger.store)
    assert digest["expired"] >= 1, "fixture sanity: the stray ticket expired too"

    codes = [f.code for f in doctor(ledger, events)]
    assert "env_never_paid" in codes, (
        "6 real, caller-made zero-delta settlements are still >= "
        "MIN_SETTLES after subtracting the 1 that expired via tick()"
    )


def test_settles_dropped_only_fires_beyond_what_silence_explains(tmp_path):
    """A silent decide never opens a ticket, so settling one always drops."""
    memory, ledger = seeded_ledger(tmp_path)
    for _ in range(3):
        ticket = ledger.decide("completely unrelated query about kangaroos and tax law")
        ledger.settle(ticket.id, delta=1.0, detail="never opened")
    ledger.save(memory)
    assert "settles_dropped" not in [f.code for f in doctor(ledger, _events(memory))], (
        "3 dropped, 3 silent decides: fully explained, not a fault"
    )

    ledger.settle("totally-bogus-ticket-id", delta=1.0, detail="phantom")
    ledger.save(memory)
    codes = [f.code for f in doctor(ledger, _events(memory))]
    assert "settles_dropped" in codes, "4 dropped vs 3 silent: the excess is real"


def test_stats_reports_economics_when_an_event_log_exists(tmp_path, capsys):
    memory, ledger = seeded_ledger(tmp_path)
    ticket = ledger.decide("are stale feature flags safe to remove?")
    ledger.settle(ticket.id, delta=7.0, detail="cleanup went fine")
    ledger.tick()
    ledger.save(memory)

    assert cli_main(["stats", str(memory)]) == 0
    out = capsys.readouterr().out
    assert "resource delta: +7" in out
    assert "upkeep paid" in out


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
