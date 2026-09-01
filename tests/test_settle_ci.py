"""settle-ci: per-test junit diffing, abstention, quarantine, fallback."""

import json
from pathlib import Path

import pytest

from darwin_memo import Ledger
from darwin_memo.ci import (
    EXIT_ABSTAINED,
    InfraFailure,
    diff_runs,
    load_flips,
    parse_junit,
    quarantined,
    record_flips,
)
from darwin_memo.cli import main as cli_main

# ----------------------------------------------------------------------
# Synthetic junit XML fixtures
# ----------------------------------------------------------------------

_CASE_BODIES = {
    "failed": '<failure message="assert">boom</failure>',
    "error": '<error message="RuntimeError">boom</error>',
    "skipped": '<skipped message="platform" />',
    "collection": '<error message="collection failure">ImportError</error>',
}


def _case(name, status):
    if status == "passed":
        return f'<testcase classname="t" name="{name}" time="0.01" />'
    return f'<testcase classname="t" name="{name}">{_CASE_BODIES[status]}</testcase>'


def write_junit(path, cases):
    body = "".join(_case(name, status) for name, status in cases)
    path.write_text(
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<testsuites><testsuite name="pytest" tests="{len(cases)}">{body}'
        "</testsuite></testsuites>"
    )
    return path


# ----------------------------------------------------------------------
# Parsing and per-test diffing
# ----------------------------------------------------------------------


def test_parse_junit_per_test_statuses(tmp_path):
    report = write_junit(
        tmp_path / "run.xml",
        [("a", "passed"), ("b", "failed"), ("c", "error"), ("d", "skipped")],
    )
    statuses = parse_junit(report, "head")
    assert statuses == {"t::a": True, "t::b": False, "t::c": False, "t::d": None}


def test_skipped_tests_are_unmeasured_not_failed(tmp_path):
    """A skip that turns into a pass must not pay out.

    ``memory.yml`` installed fewer extras than ``ci.yml``, so three MCP
    tests and the paper-build guard skipped on every settle run, were
    booked as failures, and sat quarantined at 10/10 "failures" having
    never failed once. The expensive half is the other direction: the day
    such a skip flips to a pass because an extra got installed, the old
    code booked a +1 that no memory entry earned.
    """
    base = parse_junit(
        write_junit(tmp_path / "b.xml", [("a", "passed"), ("gated", "skipped")]),
        "base",
    )
    head = parse_junit(
        write_junit(tmp_path / "h.xml", [("a", "passed"), ("gated", "passed")]),
        "head",
    )
    assert base["t::gated"] is None
    assert diff_runs(base, head).delta() == 0.0  # skip -> pass earns nothing
    assert diff_runs(head, base).delta() == 0.0  # pass -> skip is not a regression
    # An unmeasured test accrues no flake history, so it cannot be quarantined.
    assert "t::gated" not in record_flips({}, base, base)
    # Absence is still different from a skip: deleting a passing test is a
    # real loss, and this must not have been fixed away with it.
    gone = parse_junit(write_junit(tmp_path / "g.xml", [("a", "passed")]), "gone")
    assert diff_runs(head, gone).delta() == -1.0


def test_diff_runs_classifies_every_transition():
    base = {
        "t::keeps": True,
        "t::regresses": True,
        "t::improves": False,
        "t::removed_green": True,
        "t::removed_red": False,
    }
    head = {
        "t::keeps": True,
        "t::regresses": False,
        "t::improves": True,
        "t::new_green": True,
        "t::new_red": False,
    }
    transitions = diff_runs(base, head)

    assert transitions.regressions == ["t::regresses"]
    assert transitions.improvements == ["t::improves"]
    assert transitions.added_passing == ["t::new_green"]
    assert transitions.added_failing == ["t::new_red"]
    assert transitions.removed_passing == ["t::removed_green"]
    assert transitions.removed_failing == ["t::removed_red"]

    # Passing tests are the conserved resource: gained minus lost.
    assert transitions.delta() == 0.0
    assert transitions.delta(exclude={"t::regresses"}) == 1.0


@pytest.mark.parametrize(
    "make_report",
    [
        lambda tmp_path: tmp_path / "never_written.xml",
        lambda tmp_path: write_junit(tmp_path / "empty.xml", []),
        lambda tmp_path: write_junit(
            tmp_path / "broken.xml", [("tests/test_x.py", "collection")]
        ),
    ],
    ids=["missing file", "zero tests", "collection error"],
)
def test_parse_junit_raises_on_infra_failure(tmp_path, make_report):
    with pytest.raises(InfraFailure):
        parse_junit(make_report(tmp_path), "base")


def test_parse_junit_raises_on_unparseable_xml(tmp_path):
    report = tmp_path / "garbage.xml"
    report.write_text("this is not xml <")
    with pytest.raises(InfraFailure, match="unparseable"):
        parse_junit(report, "head")


# ----------------------------------------------------------------------
# Flaky quarantine
# ----------------------------------------------------------------------


def test_flaky_quarantine_enters_and_exits():
    test_id = "t::flappy"
    history: dict[str, list[bool]] = {}
    # Three runs flipping direction: enough adjacent disagreements to
    # cross the default threshold inside the default window.
    for base_pass, head_pass in [(True, False), (False, True), (True, False)]:
        history = record_flips(history, {test_id: base_pass}, {test_id: head_pass})
    assert test_id in quarantined(history)

    # Stability is the only exit: old flips must slide out of the window.
    for _ in range(3):
        history = record_flips(history, {test_id: True}, {test_id: True})
        assert test_id in quarantined(history), "still flipping inside the window"
    history = record_flips(history, {test_id: True}, {test_id: True})
    assert test_id not in quarantined(history)


def test_record_flips_drops_tests_that_left_the_suite():
    history = {"t::gone": [True, False, True]}
    updated = record_flips(history, {"t::stays": True}, {"t::stays": True})
    assert "t::gone" not in updated
    assert updated["t::stays"] == [True, True]


# ----------------------------------------------------------------------
# The CLI subcommand end to end
# ----------------------------------------------------------------------


def _energy_of_pending_decider(ledger: Ledger) -> float:
    """The balance of the entry the single open ticket decided."""
    pending = ledger.pending()
    assert pending, "expected one open ticket"
    decider = pending[0].deciding_entry
    assert decider is not None
    entry = ledger.store.get(decider)
    assert entry is not None
    return float(entry.energy)


def _json(capsys, argv):
    assert cli_main(argv) == 0
    return json.loads(capsys.readouterr().out)


def _store_with_ticket(tmp_path, capsys):
    """A lesson store holding one entry and one open ticket."""
    store = str(tmp_path / "lessons.json")
    _json(
        capsys,
        [
            "ledger",
            store,
            "add",
            "Is the cache disposable?",
            "The cache is disposable and safe to remove.",
        ],
    )
    decided = _json(capsys, ["ledger", store, "decide", "is the cache safe to remove?"])
    assert decided["ticket_id"]
    return store, decided["ticket_id"]


def test_settle_ci_settles_the_per_test_delta(tmp_path, capsys):
    store, ticket_id = _store_with_ticket(tmp_path, capsys)
    base = write_junit(tmp_path / "base.xml", [("a", "passed"), ("b", "failed")])
    head = write_junit(
        tmp_path / "head.xml", [("a", "passed"), ("b", "passed"), ("c", "passed")]
    )

    out = _json(
        capsys,
        [
            "settle-ci",
            store,
            "--base-xml",
            str(base),
            "--head-xml",
            str(head),
            "--pr-body",
            f"darwin-memo-ticket: {ticket_id}",
            "--scale",
            "2.0",
            "--detail",
            "run-url",
        ],
    )
    assert out["mode"] == "junit"
    assert out["delta"] == 2.0, "one improvement plus one added passing test"
    assert out["improvements"] == ["t::b"]
    assert out["added"]["passing"] == ["t::c"]
    assert out["settled"] == {ticket_id: True}
    assert out["tick"]["tick"] == 1

    stats = _json(capsys, ["ledger", store, "stats"])
    assert stats["pending_tickets"] == 0
    assert stats["total_energy"] > 1.0, "settlement credited the entry"
    # The sidecar state recorded both runs' observations.
    flips = json.loads((tmp_path / "flaky.json").read_text())
    assert flips["tests"]["t::b"] == [False, True]


def test_settle_ci_abstains_on_infra_failure(tmp_path, capsys):
    store, _ = _store_with_ticket(tmp_path, capsys)
    snapshot = (tmp_path / "lessons.json").read_text()
    good = write_junit(tmp_path / "base.xml", [("a", "passed")])
    collected_nothing = write_junit(
        tmp_path / "head.xml", [("tests/test_x.py", "collection")]
    )

    for head in [str(tmp_path / "missing.xml"), str(collected_nothing)]:
        assert (
            cli_main(["settle-ci", store, "--base-xml", str(good), "--head-xml", head])
            == EXIT_ABSTAINED
        )
        captured = capsys.readouterr()
        assert json.loads(captured.out)["abstained"] is True
        assert "abstained, store untouched" in captured.err

    # Never a delta of zero: no settle, no tick, no save, no flaky state.
    assert (tmp_path / "lessons.json").read_text() == snapshot
    assert not (tmp_path / "flaky.json").exists()
    stats = _json(capsys, ["ledger", store, "stats"])
    assert stats["pending_tickets"] == 1, "the ticket is still open"


def test_settle_ci_excludes_quarantined_tests_from_the_delta(tmp_path, capsys):
    store, ticket_id = _store_with_ticket(tmp_path, capsys)
    # Pre-quarantined: three direction changes already on record.
    (tmp_path / "flaky.json").write_text(
        json.dumps({"tests": {"t::b": [True, False, True, False]}})
    )
    base = write_junit(tmp_path / "base.xml", [("a", "passed"), ("b", "passed")])
    head = write_junit(tmp_path / "head.xml", [("a", "passed"), ("b", "failed")])

    out = _json(
        capsys,
        [
            "settle-ci",
            store,
            "--base-xml",
            str(base),
            "--head-xml",
            str(head),
            "--pr-body",
            f"darwin-memo-ticket: {ticket_id}",
        ],
    )
    assert out["regressions"] == ["t::b"], "the flip is still reported"
    assert out["quarantined"] == ["t::b"]
    assert out["delta"] == 0.0, "but a quarantined flake never settles a lesson"
    assert out["settled"] == {ticket_id: True}


def test_settle_ci_pass_count_fallback(tmp_path, capsys, monkeypatch):
    store, ticket_id = _store_with_ticket(tmp_path, capsys)
    monkeypatch.setenv("PR_BODY", f"darwin-memo-ticket: {ticket_id}")

    out = _json(
        capsys,
        ["settle-ci", store, "--passes-before", "5", "--passes-after", "8"],
    )
    assert out == {
        "mode": "pass-counts",
        "delta": 3.0,
        # No --opened-since, so the run cannot verify it opened this ticket and
        # says so rather than settling silently.
        "ticket_provenance": "unverified",
        "settled": {ticket_id: True},
        "tick": out["tick"],
    }
    assert not (tmp_path / "flaky.json").exists(), "no per-test data, no quarantine"


def test_settle_ci_creates_a_missing_store(tmp_path, capsys):
    """Same convention as the ledger command: auto-create on first use."""
    store = str(tmp_path / "nested" / "lessons.json")
    out = _json(
        capsys,
        ["settle-ci", store, "--passes-before", "5", "--passes-after", "5"],
    )
    assert out["settled"] == {}
    assert (tmp_path / "nested" / "lessons.json").exists()


def test_settle_ci_rejects_ambiguous_modes(tmp_path, capsys):
    store = str(tmp_path / "lessons.json")
    cases = [
        ["settle-ci", store],
        ["settle-ci", store, "--base-xml", "base.xml", "--passes-after", "3"],
        ["settle-ci", store, "--base-xml", "base.xml"],
        ["settle-ci", store, "--passes-before", "5"],
    ]
    for argv in cases:
        assert cli_main(argv) == 1
        assert "error:" in capsys.readouterr().err


# ----------------------------------------------------------------------
# The clock is driven by evidence, not by merges
# ----------------------------------------------------------------------


def test_a_merge_carrying_no_ticket_does_not_charge_upkeep(tmp_path, capsys):
    """The extinction bug and its fix, in one test.

    This repo's own lesson store died of exactly this: 49 merged PRs
    with no ``darwin-memo-ticket:`` line, each one ticking the clock and
    billing every entry upkeep for time in which it was never given a
    chance to earn.

    Mutation that must fail this test: make the tick in
    ``cmd_settle_ci`` unconditional again.
    """
    store, _ = _store_with_ticket(tmp_path, capsys)
    before = _json(capsys, ["ledger", store, "stats"])
    base = write_junit(tmp_path / "base.xml", [("a", "failed")])
    head = write_junit(tmp_path / "head.xml", [("a", "passed")])

    out = _json(
        capsys,
        [
            "settle-ci",
            store,
            "--base-xml",
            str(base),
            "--head-xml",
            str(head),
            "--pr-body",
            "a PR body with no ticket line at all",
        ],
    )

    assert out["delta"] == 1.0, "the measurement still happened"
    assert out["settled"] == {}, "but nothing was attributable to an entry"
    assert out["tick"] is None, "so the clock did not advance"
    after = _json(capsys, ["ledger", store, "stats"])
    assert after["total_energy"] == before["total_energy"], (
        "an entry must not pay upkeep for a merge it was never consulted on"
    )


def test_a_settled_ticket_still_ticks(tmp_path, capsys):
    """The other half: evidence arrives, so the clock does advance.

    Mutation that must fail this test: never tick (drop the call), or
    gate the tick on credit actually moving rather than on a settlement
    arriving.
    """
    store, ticket_id = _store_with_ticket(tmp_path, capsys)
    base = write_junit(tmp_path / "base.xml", [("a", "failed")])
    head = write_junit(tmp_path / "head.xml", [("a", "passed")])

    out = _json(
        capsys,
        [
            "settle-ci",
            store,
            "--base-xml",
            str(base),
            "--head-xml",
            str(head),
            "--pr-body",
            f"darwin-memo-ticket: {ticket_id}",
        ],
    )
    assert out["settled"] == {ticket_id: True}
    assert out["tick"]["tick"] == 1


def test_a_dropped_settle_is_still_evidence(tmp_path, capsys):
    """A ticket id nobody recognises still means the caller reported back.

    Requiring a *landed* settlement instead would make a store whose
    retrieval has gone mute immortal: every decide silent, every settle
    dropped, upkeep never charged, nothing ever dies.

    Mutation that must fail this test: gate the tick on
    ``any(out["settled"].values())`` instead of on the settle attempt.
    """
    store, _ = _store_with_ticket(tmp_path, capsys)
    base = write_junit(tmp_path / "base.xml", [("a", "failed")])
    head = write_junit(tmp_path / "head.xml", [("a", "passed")])

    out = _json(
        capsys,
        [
            "settle-ci",
            store,
            "--base-xml",
            str(base),
            "--head-xml",
            str(head),
            "--pr-body",
            "darwin-memo-ticket: deadbeef0000",
        ],
    )
    assert out["settled"] == {"deadbeef0000": False}, "the id landed on nothing"
    assert out["tick"]["tick"] == 1, "but the caller did report, so time passed"


# ----------------------------------------------------------------------
# Trust-boundary hardening (round 3)
# ----------------------------------------------------------------------


def test_a_test_erroring_with_the_word_collection_still_settles(tmp_path):
    """A real test whose error message merely contains "collection" is a
    failure to measure, not a collection error that abstains the whole run.

    The guard matched the bare substring "collection", so a fixture raising
    e.g. RuntimeError("garbage collection issue") made the head report abstain,
    and a run abstains once, at merge -- so that PR's real regressions never
    settled. Mutation: widen the phrase back to "collection" and this fails.
    """
    report = tmp_path / "run.xml"
    report.write_text(
        '<?xml version="1.0"?><testsuites><testsuite name="pytest" tests="2">'
        '<testcase classname="t" name="a" time="0.01" />'
        '<testcase classname="t" name="b">'
        '<error message="RuntimeError: garbage collection issue">boom</error>'
        "</testcase></testsuite></testsuites>"
    )
    statuses = parse_junit(report, "head")
    assert statuses == {"t::a": True, "t::b": False}


def test_a_real_collection_failure_still_abstains(tmp_path):
    """The documented phrase pytest actually writes must still abstain."""
    report = write_junit(tmp_path / "run.xml", [("mod", "collection")])
    with pytest.raises(InfraFailure, match="collection error"):
        parse_junit(report, "head")


def test_load_flips_regenerates_rather_than_crashing_on_a_hostile_sidecar(tmp_path):
    """The sidecar is committed to the repo, so the PR being measured can
    author it. A malformed file must not brick settle-ci for every later merge.

    Each of these used to raise out of load_flips (JSONDecodeError, or
    AttributeError/TypeError from .items()/iteration); now they regenerate to
    empty history, which also happens to defeat a PR that authored a bogus
    quarantine to hide its own regression.
    """
    for bad in ('{"tests": [1, 2, 3]}', "[1, 2, 3]", '{"tests": {"x": 5}}', "not json"):
        sidecar = tmp_path / "flaky.json"
        sidecar.write_text(bad)
        assert load_flips(sidecar) == {}, bad


def test_load_flips_still_reads_a_valid_sidecar(tmp_path):
    sidecar = tmp_path / "flaky.json"
    sidecar.write_text('{"tests": {"pkg::test_x": [true, false, true]}}')
    assert load_flips(sidecar) == {"pkg::test_x": [True, False, True]}


def test_a_scraped_open_ticket_cannot_be_settled_by_another_pr(tmp_path, capsys):
    """The high-severity finding: the PR body is attacker-influenced and open
    ticket ids are public in the committed store, so without a provenance check
    a merged PR could settle someone else's in-flight decision at a delta it
    chose. --opened-since refuses any ticket already pending at the base.

    Break-test: drop the guard (omit --opened-since) and the victim settles.
    """
    # The victim's in-flight decision, pending on main (base == head here).
    store, victim = _store_with_ticket(tmp_path, capsys)
    before = _energy_of_pending_decider(Ledger.load(store))
    head = str(tmp_path / "head.json")
    Path(head).write_text(Path(store).read_text())

    base_xml = write_junit(tmp_path / "b.xml", [("keep", "passed")])
    head_xml = write_junit(
        tmp_path / "h.xml",
        [("keep", "passed"), *[(f"new{i}", "passed") for i in range(20)]],
    )
    out = _json(
        capsys,
        [
            "settle-ci",
            head,
            "--base-xml",
            str(base_xml),
            "--head-xml",
            str(head_xml),
            "--opened-since",
            store,
            "--pr-body",
            f"lgtm\ndarwin-memo-ticket: {victim}\n",
        ],
    )
    assert victim in out["refused_not_opened_here"]
    assert victim not in out["settled"]

    reloaded = Ledger.load(head)
    assert victim in {t.id for t in reloaded.pending()}, "ticket still open"
    assert _energy_of_pending_decider(reloaded) == before, "no credit flowed"


def test_a_ticket_this_run_opened_still_settles(tmp_path, capsys):
    """The guard must not block the legitimate flow: a ticket pending in head
    but absent from base was opened by this PR and settles normally."""

    # base: an entry, no open ticket yet.
    base = str(tmp_path / "lessons.json")
    _json(
        capsys,
        [
            "ledger",
            base,
            "add",
            "Is the cache disposable?",
            "The cache is disposable and safe to remove.",
        ],
    )
    # this PR opens the ticket, committing it into the head store.
    decided = _json(capsys, ["ledger", base, "decide", "is the cache safe to remove?"])
    mine = decided["ticket_id"]
    # snapshot the base as it was BEFORE this PR opened the ticket.
    base_before = str(tmp_path / "base_before.json")
    lb = Ledger.load(base)
    lb._pending.clear()  # the base commit had no such ticket
    lb.save(base_before)

    base_xml = write_junit(tmp_path / "b.xml", [("t", "passed")])
    head_xml = write_junit(tmp_path / "h.xml", [("t", "passed"), ("x", "passed")])
    out = _json(
        capsys,
        [
            "settle-ci",
            base,
            "--base-xml",
            str(base_xml),
            "--head-xml",
            str(head_xml),
            "--opened-since",
            base_before,
            "--pr-body",
            f"darwin-memo-ticket: {mine}\n",
        ],
    )
    assert out["settled"].get(mine) is True
    assert not out.get("refused_not_opened_here")
