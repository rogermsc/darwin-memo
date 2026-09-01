"""settle-ci: settle a CI lesson store from test results, per test id.

The CI lesson-store integration (docs/integrations/ci-lesson-store.md)
settles every ticket with the change in passing tests. The first
generation of that wiring diffed raw pass counts in shell, and the doc
already named the failure modes: a run that produced no count silently
became zero (the ``|| echo 0`` fake delta), suites that evolve shift
the baseline, and flaky tests poison the signal. This module is those
hardenings as one subcommand.

Primary mode diffs junit XML per test id. Two reports go in, one from
the base commit run and one from the head or merge commit run, and the
delta is computed from per-test transitions: a pass that became a fail
is a regression, a fail that became a pass is an improvement, added
and removed tests are attributed as suite changes instead of smearing
into the count. With nothing excluded the per-id delta equals the raw
pass-count delta; the per-id form is what makes attribution and
quarantine possible at all.

Infra failures abstain. A run with no parseable junit XML, zero
collected tests, or a collection error measured nothing, so settling
it (at zero or anything else) would be a lie. The command leaves the
store untouched, says why on stderr, and exits ``EXIT_ABSTAINED`` so
CI can surface the broken measurement instead of burying it.

Flaky tests quarantine themselves. A sidecar state file next to the
store records each test's recent pass/fail observations; a test whose
history flips direction ``--flip-threshold`` times inside the sliding
``--window`` is excluded from settlement deltas until the flips slide
out of the window. Quarantined tests are reported, never settled.

Fallback mode (``--passes-before``/``--passes-after``) diffs raw pass
counts for ecosystems without junit XML. It is the degraded path: no
per-test attribution, no quarantine, no infra detection beyond
requiring both counts explicitly. Never default a missing count to
zero; if the run produced no count, skip settlement entirely.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

from .ledger import Ledger
from .store import MemoryStore, write_json_atomic

EXIT_ABSTAINED = 3
TICKET_RE = re.compile(r"darwin-memo-ticket:\s*([0-9a-f]{12})")
FLAKY_WINDOW = 10
FLAKY_FLIPS = 3


class InfraFailure(Exception):
    """A run that measured nothing. Settling it at zero would be a lie."""


def parse_junit(path: str | Path, label: str) -> dict[str, bool | None]:
    """Per-test pass map from one junit XML report.

    Returns ``{test id: passed}`` where the id is ``classname::name``
    and ``None`` means the run measured nothing for that test.
    Errored tests count as not passing. Skipped ones do not count as
    either: a skip is an absence of evidence, and booking it as a
    failure makes the store lie twice --- the test sits quarantined
    having never failed, and the day the skip turns into a pass
    (an extra installed, a GPU present) the suite books a +1 that no
    memory entry earned. This is the run-level rule of this module
    ("a run that produced no count measured nothing") applied per
    test. Raises :class:`InfraFailure` when
    the run measured nothing: missing file, unparseable XML, zero
    collected tests, or a collection error (pytest reports those as
    testcases erroring with ``collection failure``, meaning the suite
    definition itself never loaded).
    """
    report = Path(path)
    if not report.exists():
        raise InfraFailure(f"{label} run produced no junit XML at {report}")
    try:
        root = ET.parse(report).getroot()
    except ET.ParseError as exc:
        raise InfraFailure(
            f"{label} junit XML at {report} is unparseable: {exc}"
        ) from exc
    passed_by_id: dict[str, bool | None] = {}
    for case in root.iter("testcase"):
        name = case.get("name", "")
        classname = case.get("classname", "")
        test_id = f"{classname}::{name}" if classname else name
        passed: bool | None = True
        for child in case:
            message = child.get("message", "").lower()
            if child.tag == "error" and "collection" in message:
                raise InfraFailure(
                    f"{label} run hit a collection error ({test_id}): "
                    "the suite never loaded"
                )
            if child.tag in ("error", "failure"):
                passed = False
            elif child.tag == "skipped" and passed is not False:
                passed = None
        # Rerun plugins emit duplicate ids. A recorded failure still wins
        # over everything, and a real result wins over a skip, so only an
        # id that was skipped every time it appeared stays unmeasured.
        if test_id in passed_by_id:
            seen = passed_by_id[test_id]
            if seen is False or passed is False:
                passed = False
            elif seen is True or passed is True:
                passed = True
            else:
                passed = None
        passed_by_id[test_id] = passed
    if not passed_by_id:
        raise InfraFailure(f"{label} run collected zero tests")
    return passed_by_id


@dataclass
class Transitions:
    """Per-test differences between the base run and the head run."""

    regressions: list[str] = field(default_factory=list)  # pass -> fail
    improvements: list[str] = field(default_factory=list)  # fail -> pass
    added_passing: list[str] = field(default_factory=list)
    added_failing: list[str] = field(default_factory=list)
    removed_passing: list[str] = field(default_factory=list)
    removed_failing: list[str] = field(default_factory=list)

    def delta(self, exclude: set[str] | None = None) -> float:
        """Change in passing tests, computed per test id.

        Passing tests are the conserved resource, so the delta is the
        passing tests gained minus the passing tests lost. With nothing
        excluded this equals the raw pass-count delta; ``exclude`` is
        how quarantined flakes stay out of the measurement.
        """
        skip = exclude or set()
        gained = [t for t in self.improvements + self.added_passing if t not in skip]
        lost = [t for t in self.regressions + self.removed_passing if t not in skip]
        return float(len(gained) - len(lost))


def diff_runs(
    base: Mapping[str, bool | None], head: Mapping[str, bool | None]
) -> Transitions:
    """Classify every test id seen in either run.

    A test the other side never measured (``None``, i.e. skipped) is
    not a transition in either direction. Absence is different and
    still counts: a passing test deleted from the suite is a real
    loss, which is why this checks for ``None`` rather than reusing
    the membership tests below.
    """
    transitions = Transitions()
    for test_id in sorted(set(base) | set(head)):
        if base.get(test_id, False) is None or head.get(test_id, False) is None:
            continue
        if test_id not in head:
            bucket = (
                transitions.removed_passing
                if base[test_id]
                else transitions.removed_failing
            )
        elif test_id not in base:
            bucket = (
                transitions.added_passing
                if head[test_id]
                else transitions.added_failing
            )
        elif base[test_id] and not head[test_id]:
            bucket = transitions.regressions
        elif not base[test_id] and head[test_id]:
            bucket = transitions.improvements
        else:
            continue
        bucket.append(test_id)
    return transitions


# ----------------------------------------------------------------------
# Flaky-test quarantine: per-test flip history in a sidecar state file
# ----------------------------------------------------------------------


def load_flips(path: str | Path) -> dict[str, list[bool]]:
    """Read the sidecar flip history; a missing file is empty history."""
    state = Path(path)
    if not state.exists():
        return {}
    payload = json.loads(state.read_text())
    return {
        test_id: [bool(v) for v in observed]
        for test_id, observed in payload.get("tests", {}).items()
    }


def record_flips(
    history: Mapping[str, list[bool]],
    base: Mapping[str, bool | None],
    head: Mapping[str, bool | None],
    window: int = FLAKY_WINDOW,
) -> dict[str, list[bool]]:
    """Append this run's observations, newest last, capped to the window.

    Both runs are recorded: the base run usually re-executes the
    previous head commit, so a result that disagrees with the recorded
    history is flake evidence in itself. Tests absent from both runs
    left the suite and their history is dropped with them, and so is
    a test both runs only skipped: an unmeasured test is not flaky,
    and recording skips as failures is what pinned four never-failing
    tests in this repo's own quarantine.
    """
    updated: dict[str, list[bool]] = {}
    for test_id in sorted(set(base) | set(head)):
        observed = list(history.get(test_id, []))
        for run in (base, head):
            result = run.get(test_id)
            if result is not None:
                observed.append(result)
        if observed:
            updated[test_id] = observed[-window:]
    return updated


def quarantined(
    history: dict[str, list[bool]], flip_threshold: int = FLAKY_FLIPS
) -> set[str]:
    """Tests whose recent history flips direction too often to trust.

    A flip is an adjacent pair of observations that disagree. A test at
    or past the threshold is excluded from settlement deltas until its
    flips slide out of the window, which is the only exit: stabilizing
    is what releases it, on either the passing or the failing side.
    """
    return {
        test_id
        for test_id, observed in history.items()
        if sum(1 for a, b in pairwise(observed) if a != b) >= flip_threshold
    }


def save_flips(path: str | Path, history: dict[str, list[bool]]) -> None:
    write_json_atomic(path, {"tests": dict(sorted(history.items()))})


# ----------------------------------------------------------------------
# The subcommand
# ----------------------------------------------------------------------


def cmd_settle_ci(args: argparse.Namespace) -> int:
    """Settle the lesson store from CI results, one JSON object on stdout.

    Same persistence conventions as ``darwin-memo ledger``: the store
    auto-creates on first use, every mutating run saves before
    printing, and events append to the shared ``.events.jsonl`` log.
    On abstention nothing is loaded, settled, ticked, or saved.
    """
    junit_mode = bool(args.base_xml or args.head_xml)
    counts_mode = args.passes_before is not None or args.passes_after is not None
    if junit_mode == counts_mode:
        print(
            "error: settle-ci takes either --base-xml/--head-xml (per-test "
            "diff) or --passes-before/--passes-after (degraded fallback)",
            file=sys.stderr,
        )
        return 1
    if junit_mode and not (args.base_xml and args.head_xml):
        print("error: junit mode needs both --base-xml and --head-xml", file=sys.stderr)
        return 1
    if counts_mode and (args.passes_before is None or args.passes_after is None):
        print(
            "error: fallback mode needs both --passes-before and --passes-after; "
            "never default a missing count to zero",
            file=sys.stderr,
        )
        return 1

    path = Path(args.memory).expanduser()
    state_path = Path(args.state) if args.state else path.parent / "flaky.json"
    out: dict[str, object]
    flips: dict[str, list[bool]] | None = None

    if junit_mode:
        try:
            base = parse_junit(args.base_xml, "base")
            head = parse_junit(args.head_xml, "head")
        except InfraFailure as exc:
            print(json.dumps({"abstained": True, "reason": str(exc)}))
            print(f"abstained, store untouched: {exc}", file=sys.stderr)
            return EXIT_ABSTAINED
        flips = record_flips(load_flips(state_path), base, head, window=args.window)
        quarantine = quarantined(flips, flip_threshold=args.flip_threshold)
        transitions = diff_runs(base, head)
        delta = transitions.delta(exclude=quarantine)
        out = {
            "mode": "junit",
            "delta": delta,
            "regressions": transitions.regressions,
            "improvements": transitions.improvements,
            "added": {
                "passing": transitions.added_passing,
                "failing": transitions.added_failing,
            },
            "removed": {
                "passing": transitions.removed_passing,
                "failing": transitions.removed_failing,
            },
            "quarantined": sorted(quarantine),
        }
    else:
        delta = float(args.passes_after - args.passes_before)
        out = {"mode": "pass-counts", "delta": delta}

    path.parent.mkdir(parents=True, exist_ok=True)
    event_log = path.with_suffix(".events.jsonl")
    if path.exists():
        ledger = Ledger.load(path, resource_scale=args.scale, event_log=event_log)
    else:
        ledger = Ledger(MemoryStore(), resource_scale=args.scale, event_log=event_log)

    body = args.pr_body if args.pr_body is not None else os.environ.get("PR_BODY", "")
    tickets = list(dict.fromkeys(TICKET_RE.findall(body)))
    out["settled"] = {
        ticket_id: ledger.settle(ticket_id, delta, detail=args.detail)
        for ticket_id in tickets
    }
    # The clock is driven by evidence, not by merges. A tick charges
    # every alive entry upkeep, so ticking on a merge that carried no
    # ticket bills the store for time in which it was never given a
    # chance to earn -- and credit is capped at max_energy, so no
    # entry outlives spawn/upkeep such ticks however valuable it is.
    # This repo's own store died that way: 49 consecutive settlement-
    # free ticks, one per merged PR. A dropped settle (unknown id, or
    # a silent decide that never opened a ticket) still counts as the
    # caller reporting on the world; requiring credit instead would
    # make a store whose retrieval went mute immortal. The cost is
    # that expiry and consolidation now advance in settled ticks
    # rather than merges, which is the cadence the economy assumes.
    out["tick"] = (
        ledger.tick(expire_after=args.expire_after) if out["settled"] else None
    )
    ledger.save(path)
    if flips is not None:
        save_flips(state_path, flips)
    print(json.dumps(out))
    return 0


def add_settle_ci_parser(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the settle-ci subcommand on the main CLI's subparsers."""
    settle_ci = sub.add_parser(
        "settle-ci",
        help="settle a lesson store from CI results (per-test junit XML diff)",
        description=(
            "Settle lesson-store tickets from CI test results. Primary mode "
            "diffs junit XML per test id (pytest --junitxml at the base and "
            "head commits); a run with no parseable XML, zero collected "
            f"tests, or a collection error abstains with exit code "
            f"{EXIT_ABSTAINED} and leaves the store untouched. Tests that "
            "flip direction repeatedly are quarantined out of the delta via "
            "a sidecar state file next to the store. Tickets are read as "
            "darwin-memo-ticket lines from --pr-body or the PR_BODY "
            "environment variable; after settling, one tick runs and the "
            "store is saved."
        ),
    )
    settle_ci.add_argument("memory", help="ledger file; created on first use")
    settle_ci.add_argument("--base-xml", help="junit XML from the base commit run")
    settle_ci.add_argument(
        "--head-xml", help="junit XML from the head or merge commit run"
    )
    settle_ci.add_argument(
        "--passes-before",
        type=int,
        default=None,
        help="degraded fallback for ecosystems without junit XML: raw "
        "passing count at the base commit (no per-test attribution, no "
        "quarantine, no infra detection)",
    )
    settle_ci.add_argument(
        "--passes-after",
        type=int,
        default=None,
        help="degraded fallback: raw passing count at the head commit",
    )
    settle_ci.add_argument(
        "--pr-body",
        default=None,
        help="text carrying darwin-memo-ticket lines (default: the PR_BODY "
        "environment variable)",
    )
    settle_ci.add_argument(
        "--detail", default="", help="settlement detail, e.g. the CI run URL"
    )
    settle_ci.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="resource_scale for settle deltas (default 1.0)",
    )
    settle_ci.add_argument(
        "--state",
        default=None,
        help="flaky-test state file (default: flaky.json next to the store)",
    )
    settle_ci.add_argument(
        "--window",
        type=int,
        default=FLAKY_WINDOW,
        help=f"observations of flip history kept per test (default {FLAKY_WINDOW})",
    )
    settle_ci.add_argument(
        "--flip-threshold",
        type=int,
        default=FLAKY_FLIPS,
        help="direction changes within the window that quarantine a test "
        f"(default {FLAKY_FLIPS})",
    )
    settle_ci.add_argument(
        "--expire-after",
        type=int,
        default=50,
        help="ticks before unsettled tickets expire at delta zero (default 50)",
    )
    settle_ci.set_defaults(fn=cmd_settle_ci)
