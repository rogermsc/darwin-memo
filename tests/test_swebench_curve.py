"""Scoring the matrix, where a silent arithmetic error would survive review.

The run records are cheap to fabricate and the metrics are small, so
every rule that could quietly change a published number gets a case:
which half a task lands in, which deltas count as harm, and which
worlds are allowed to enter a paired test.
"""

from __future__ import annotations

from typing import Any

import pytest

from bench.swebench_cl.curve import (
    arm_summary,
    compare,
    harm_integral,
    learning_delta,
    paired_learning,
    positional_resolved,
    resolve_rate,
)


def make_run(
    arm: str = "memory_on",
    seed: int = 0,
    sequence: str = "pytest",
    order: int = 1,
    resolved: bool = False,
    delta: float = 0.0,
    population: int = 3,
) -> dict[str, Any]:
    return {
        "arm": arm,
        "seed": seed,
        "sequence": sequence,
        "order": order,
        "instance_id": f"{sequence}__{order}",
        "metrics": {"resolved": resolved, "delta": delta},
        "store": {"population": population},
    }


def cell(
    arm: str, seed: int, resolved: list[bool], sequence: str = "pytest"
) -> list[dict[str, Any]]:
    """One world's runs, in curriculum order."""
    return [
        make_run(arm=arm, seed=seed, sequence=sequence, order=i, resolved=r)
        for i, r in enumerate(resolved, start=1)
    ]


def test_resolve_rate_counts_resolutions():
    assert resolve_rate(cell("memory_on", 0, [True, False, True, False])) == 0.5


def test_resolve_rate_rejects_empty():
    # Returning 0.0 for "no data" would read as a real measurement of
    # total failure in any table it landed in.
    with pytest.raises(ValueError):
        resolve_rate([])


def test_learning_delta_splits_into_equal_halves():
    # First half all failures, second half all resolutions: +1.0.
    assert learning_delta(cell("memory_on", 0, [False, False, True, True])) == 1.0


def test_learning_delta_drops_the_middle_task_when_odd():
    # Five tasks: halves are tasks 1-2 and 4-5; task 3 belongs to
    # neither, so flipping it must not move the statistic.
    without = learning_delta(cell("memory_on", 0, [False, False, False, True, True]))
    with_middle = learning_delta(cell("memory_on", 0, [False, False, True, True, True]))
    assert without == with_middle == 1.0


def test_learning_delta_is_order_not_file_order():
    runs = cell("memory_on", 0, [False, False, True, True])
    assert learning_delta(list(reversed(runs))) == learning_delta(runs)


def test_learning_delta_needs_two_runs():
    with pytest.raises(ValueError):
        learning_delta(cell("memory_on", 0, [True]))


def test_harm_integral_sums_only_negative_deltas():
    runs = [
        make_run(order=1, delta=-3.0),
        make_run(order=2, delta=5.0),
        make_run(order=3, delta=-1.5),
    ]
    # Not +0.5: capability must not cancel damage.
    assert harm_integral(runs) == -4.5


def test_harm_integral_is_zero_without_damage():
    assert harm_integral([make_run(order=1, delta=2.0)]) == 0.0


def test_positional_resolved_averages_across_seeds():
    runs = cell("memory_on", 0, [True, False]) + cell("memory_on", 1, [False, False])
    assert positional_resolved(runs) == {1: 0.5, 2: 0.0}


def test_paired_learning_drops_worlds_missing_an_arm():
    runs = (
        cell("memory_on", 0, [False, False, True, True])
        + cell("random_matched", 0, [False, False, False, False])
        # seed 1 ran only the treated arm: an unpaired world.
        + cell("memory_on", 1, [True, True, True, True])
    )
    diffs, worlds = paired_learning(runs, "memory_on", "random_matched")
    assert worlds == [("pytest", 0)]
    assert diffs == [1.0]


def test_paired_learning_pairs_within_a_world_not_across_sequences():
    runs = (
        cell("memory_on", 0, [False, False, True, True], sequence="pytest")
        + cell("random_matched", 0, [True, True, False, False], sequence="pytest")
        + cell("memory_on", 0, [False, False, True, True], sequence="astropy")
        + cell("random_matched", 0, [False, False, True, True], sequence="astropy")
    )
    diffs, worlds = paired_learning(runs, "memory_on", "random_matched")
    assert worlds == [("astropy", 0), ("pytest", 0)]
    assert diffs == [0.0, 2.0]


def test_compare_refuses_when_no_world_ran_both_arms():
    runs = cell("memory_on", 0, [False, True]) + cell(
        "random_matched", 1, [False, True]
    )
    with pytest.raises(ValueError, match="no \\(sequence, seed\\) world"):
        compare(runs, "memory_on", "random_matched")


def test_compare_reports_the_pairing_it_used():
    runs = (
        cell("memory_on", 0, [False, False, True, True])
        + cell("random_matched", 0, [False, False, False, False])
        + cell("memory_on", 1, [False, False, True, True])
        + cell("random_matched", 1, [False, False, False, False])
    )
    result = compare(runs, "memory_on", "random_matched")
    assert result["pairs"] == 2
    assert result["mean_diff"] == 1.0
    assert 0.0 < result["p_value"] <= 1.0


def test_arm_summary_reports_final_population_not_first():
    runs = [
        make_run(order=1, population=10),
        make_run(order=2, population=4),
    ]
    (row,) = arm_summary(runs)
    assert row["final_population"] == 4
    assert row["tasks"] == 2
    assert row["cells"] == 1


def test_load_dir_ignores_the_sibling_manifest(tmp_path):
    # Docker cells bind themselves to MANIFEST.json in the same directory,
    # so it is always present once anything has run; it is not a cell and
    # has no "runs" key to read.
    import json

    from bench.swebench_cl.curve import load_dir

    (tmp_path / "MANIFEST.json").write_text(
        json.dumps({"schema_version": 1, "files": {}})
    )
    (tmp_path / "memory_on-seq-seed0.json").write_text(
        json.dumps({"runs": cell("memory_on", 0, [True, False])})
    )
    runs = load_dir(tmp_path)
    assert len(runs) == 2
    assert {r["arm"] for r in runs} == {"memory_on"}


def test_load_dir_refuses_an_empty_directory(tmp_path):
    from bench.swebench_cl.curve import load_dir

    with pytest.raises(ValueError, match="no result files"):
        load_dir(tmp_path)
