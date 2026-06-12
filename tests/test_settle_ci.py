"""settle-ci: per-test junit diffing, abstention, quarantine, fallback."""

import json

import pytest

from darwin_memo.ci import (
    EXIT_ABSTAINED,
    InfraFailure,
    diff_runs,
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
    assert statuses == {"t::a": True, "t::b": False, "t::c": False, "t::d": False}


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
