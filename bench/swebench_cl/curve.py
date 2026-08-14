"""Score the matrix: does memory produce a learning curve on real tasks?

The pre-registered claim is not "memory_on resolves more than
memory_off". Beating an arm with no lessons at all could be a
token-budget effect, so the claim is the *curve*: memory_on improves
from the first half of a sequence to the second half by more than
``random_matched`` does, which spends the same token budget on lessons
chosen without regard to outcome (\\S sec:swebench).

Everything here is per-seed and paired. Each (sequence, seed) is one
world, so arms are compared inside it and the differences are what the
permutation test consumes -- the same treatment ``bench/stats.py``
gives every other suite in the paper.

``time_to_extinction`` is deliberately absent. It needs to know *which*
entries died and when, and the run records carry death counts rather
than ids; it is also undefined on this matrix, which is unpoisoned. It
belongs with the poisoned leg, together with the runner change that
would record dying entry ids.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from statistics import mean
from typing import Any

from bench.manifest import MANIFEST_NAME
from bench.stats import bootstrap_ci, paired_permutation_pvalue

Run = dict[str, Any]
Cell = tuple[str, int]  # (sequence, seed)


def load_runs(path: Path) -> list[Run]:
    """Read one cell's records, tolerating either committed shape."""
    payload = json.loads(path.read_text())
    runs = payload["runs"] if isinstance(payload, dict) else payload
    if not isinstance(runs, list):
        raise ValueError(f"{path}: expected a list of run records")
    return runs


def load_dir(directory: Path) -> list[Run]:
    """Every cell in a results directory, concatenated.

    The sibling manifest lives in the same directory and is not a cell;
    each docker cell binds itself there as it lands, so it is always
    present once anything has run.
    """
    files = sorted(
        path for path in directory.glob("*.json") if path.name != MANIFEST_NAME
    )
    if not files:
        raise ValueError(f"{directory}: no result files")
    return [run for path in files for run in load_runs(path)]


def _ordered(runs: Sequence[Run]) -> list[Run]:
    return sorted(runs, key=lambda r: r["order"])


def resolve_rate(runs: Sequence[Run]) -> float:
    """Fraction of tasks whose evaluation resolved the issue."""
    if not runs:
        raise ValueError("resolve_rate needs at least one run")
    return sum(1 for r in runs if r["metrics"]["resolved"]) / len(runs)


def harm_integral(runs: Sequence[Run]) -> float:
    """Total measured damage: the sum of the negative settlement deltas.

    Positive deltas are capability and are reported separately by the
    resolve rate; this is the cost side alone, in the environment's own
    units, so an arm that learns fast *and* breaks a lot is not flattered
    by a net figure that cancels the two.
    """
    return sum(float(r["metrics"]["delta"]) for r in runs if r["metrics"]["delta"] < 0)


def positional_resolved(runs: Sequence[Run]) -> dict[int, float]:
    """Resolve rate at each curriculum position, averaged over seeds."""
    by_order: dict[int, list[float]] = {}
    for r in runs:
        by_order.setdefault(int(r["order"]), []).append(
            1.0 if r["metrics"]["resolved"] else 0.0
        )
    return {order: mean(vals) for order, vals in sorted(by_order.items())}


def learning_delta(runs: Sequence[Run]) -> float:
    """Second-half resolve rate minus first-half, within one cell.

    An odd number of tasks drops the middle one so the halves are the
    same size; an unequal split would let a single task's outcome move
    the statistic differently depending on which side it landed on.

    This number is NOT interpretable on its own. SWE-Bench-CL sequences
    are curricula ordered by increasing difficulty, so the second half is
    harder by construction and every arm posts a negative delta whether
    or not it learned anything. Only the arm-minus-control difference
    means something, because both arms walk the same ordering and the
    difficulty gradient cancels. That is what ``compare`` returns and
    what the claim is pre-registered on.
    """
    ordered = _ordered(runs)
    half = len(ordered) // 2
    if half == 0:
        raise ValueError("learning_delta needs at least two runs")
    return resolve_rate(ordered[-half:]) - resolve_rate(ordered[:half])


def by_cell(runs: Sequence[Run], arm: str) -> dict[Cell, list[Run]]:
    """One arm's runs, grouped into the (sequence, seed) worlds."""
    cells: dict[Cell, list[Run]] = {}
    for r in runs:
        if r["arm"] == arm:
            cells.setdefault((r["sequence"], int(r["seed"])), []).append(r)
    return cells


def paired_learning(
    runs: Sequence[Run], arm: str, control: str
) -> tuple[list[float], list[Cell]]:
    """Per-world learning-delta differences, arm minus control.

    Only worlds where both arms ran are paired. A missing cell is
    dropped and returned in neither list, because filling it with a zero
    would quietly count an unrun combination as a tie.
    """
    treated = by_cell(runs, arm)
    control_cells = by_cell(runs, control)
    shared = sorted(set(treated) & set(control_cells))
    diffs = [
        learning_delta(treated[cell]) - learning_delta(control_cells[cell])
        for cell in shared
    ]
    return diffs, shared


def compare(runs: Sequence[Run], arm: str, control: str) -> dict[str, Any]:
    """The headline test: is the curve difference distinguishable from zero?"""
    diffs, shared = paired_learning(runs, arm, control)
    if not diffs:
        raise ValueError(f"no (sequence, seed) world ran both {arm} and {control}")
    low, high = bootstrap_ci(diffs)
    return {
        "arm": arm,
        "control": control,
        "pairs": len(diffs),
        "worlds": [f"{seq}:seed{seed}" for seq, seed in shared],
        "mean_diff": mean(diffs),
        "ci95": (low, high),
        "p_value": paired_permutation_pvalue(diffs),
    }


def arm_summary(runs: Sequence[Run]) -> list[dict[str, Any]]:
    """One row per arm: what it resolved, what it broke, how it moved."""
    rows = []
    for arm in sorted({r["arm"] for r in runs}):
        cells = by_cell(runs, arm)
        arm_runs = [r for cell in cells.values() for r in cell]
        rows.append(
            {
                "arm": arm,
                "cells": len(cells),
                "tasks": len(arm_runs),
                "resolve_rate": resolve_rate(arm_runs),
                "learning_delta": mean(learning_delta(c) for c in cells.values()),
                "harm_integral": harm_integral(arm_runs),
                "final_population": mean(
                    _ordered(c)[-1]["store"]["population"] for c in cells.values()
                ),
            }
        )
    return rows


def render(runs: Sequence[Run], arm: str, control: str) -> str:
    """A markdown report, in the shape ``docs/benchmarks.md`` uses."""
    lines = [
        "| arm | cells | tasks | resolve | 2nd-1st | harm | pop |",
        "|---|" + "---|" * 6,
    ]
    for row in arm_summary(runs):
        lines.append(
            f"| {row['arm']} | {row['cells']} | {row['tasks']} | "
            f"{row['resolve_rate']:.3f} | {row['learning_delta']:+.3f} | "
            f"{row['harm_integral']:.1f} | {row['final_population']:.1f} |"
        )
    result = compare(runs, arm, control)
    low, high = result["ci95"]
    lines += [
        "",
        f"**{arm} vs {control}** (paired on {result['pairs']} worlds): "
        f"mean curve difference {result['mean_diff']:+.3f} "
        f"[{low:+.3f}, {high:+.3f}], permutation p = {result['p_value']:.4f}",
    ]
    curve = positional_resolved([r for r in runs if r["arm"] == arm])
    lines += ["", f"{arm} by position: " + " ".join(f"{v:.2f}" for v in curve.values())]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m bench.swebench_cl.curve",
        description="score the SWE-Bench-CL matrix",
    )
    p.add_argument(
        "results",
        type=Path,
        nargs="?",
        default=Path("bench/results/swebench_cl"),
        help="directory of per-cell result files",
    )
    p.add_argument("--arm", default="memory_on")
    p.add_argument("--control", default="random_matched")
    args = p.parse_args(argv)
    runs = load_dir(args.results)
    print(render(runs, args.arm, args.control))
    return 0


if __name__ == "__main__":
    sys.exit(main())
