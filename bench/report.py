"""Aggregate benchmark JSON into tables, and validate runs for CI."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

_REQUIRED_METRIC_KEYS = {
    "poison_killed",
    "poison_kill_cycle",
    "damage_before_kill",
    "cum_delta",
    "cum_negative_delta",
    "tail_delta_mean",
    "final_population",
    "wall_time_s",
    "reported_cum_delta",
    "flakes_marked",
    "flakes_fired",
    "fired_false_bad",
    "fired_false_good",
    "probe_harmful_safe_rate",
    "probe_benign_correct_rate",
    "probe_silence_rate",
    "paraphrase_harmful_safe_rate",
    "paraphrase_benign_grounded_rate",
    "paraphrase_silence_rate",
}


def _is_noisy(run: dict[str, Any]) -> bool:
    return bool(run.get("config", {}).get("flake_rate", 0))


def _group_key(run: dict[str, Any]) -> str:
    label = run.get("label") or ""
    return f"{run['arm']}:{label}" if label else run["arm"]


def _mean_std(values: list[float]) -> str:
    if not values:
        return "-"
    mean = statistics.mean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return f"{mean:,.0f} ±{std:,.0f}" if abs(mean) >= 100 else f"{mean:.2f} ±{std:.2f}"


def aggregate(runs: list[dict[str, Any]]) -> list[dict[str, str]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        groups.setdefault(_group_key(run), []).append(run)

    rows: list[dict[str, str]] = []
    for key in sorted(groups):
        metric_sets = [r["metrics"] for r in groups[key]]
        kills = [m["poison_killed"] for m in metric_sets]
        kill_cycles = [
            m["poison_kill_cycle"]
            for m in metric_sets
            if m["poison_kill_cycle"] is not None
        ]
        rows.append(
            {
                "arm": key,
                "seeds": str(len(metric_sets)),
                "kill rate": f"{sum(kills) / len(kills):.2f}",
                "kill cycle (med)": (
                    f"{statistics.median(kill_cycles):.0f}" if kill_cycles else "-"
                ),
                "damage before kill": _mean_std(
                    [m["damage_before_kill"] for m in metric_sets]
                ),
                "tail delta": _mean_std([m["tail_delta_mean"] for m in metric_sets]),
                "cum delta": _mean_std([m["cum_delta"] for m in metric_sets]),
                "final pop": _mean_std(
                    [float(m["final_population"]) for m in metric_sets]
                ),
                "harmful safe": _mean_std(
                    [m["probe_harmful_safe_rate"] for m in metric_sets]
                ),
                "benign correct": _mean_std(
                    [m["probe_benign_correct_rate"] for m in metric_sets]
                ),
                "para safe": _mean_std(
                    [m["paraphrase_harmful_safe_rate"] for m in metric_sets]
                ),
                "para grounded": _mean_std(
                    [m["paraphrase_benign_grounded_rate"] for m in metric_sets]
                ),
            }
        )
        if any(_is_noisy(r) for r in runs):
            rows[-1]["flakes fired"] = _mean_std(
                [float(m.get("flakes_fired", 0)) for m in metric_sets]
            )
    return rows


def render_table(rows: list[dict[str, str]], fmt: str = "ascii") -> str:
    if not rows:
        return "(no rows)"
    headers = list(rows[0].keys())
    widths = {h: max(len(h), *(len(r[h]) for r in rows)) for h in headers}
    if fmt == "md":
        lines = [
            "| " + " | ".join(h.ljust(widths[h]) for h in headers) + " |",
            "|" + "|".join("-" * (widths[h] + 2) for h in headers) + "|",
        ]
        lines += [
            "| " + " | ".join(r[h].ljust(widths[h]) for h in headers) + " |"
            for r in rows
        ]
    else:
        lines = ["  ".join(h.ljust(widths[h]) for h in headers)]
        lines += ["  ".join(r[h].ljust(widths[h]) for h in headers) for r in rows]
    return "\n".join(lines)


def check(runs: list[dict[str, Any]]) -> list[str]:
    """Schema and sanity validation. Returns a list of failures."""
    failures: list[str] = []
    if not runs:
        return ["no runs in file"]
    for i, run in enumerate(runs):
        if run.get("schema_version") != 1:
            failures.append(f"run {i}: bad schema_version")
        missing = _REQUIRED_METRIC_KEYS - set(run.get("metrics", {}))
        if missing:
            failures.append(f"run {i}: missing metrics {sorted(missing)}")
        if run.get("metrics", {}).get("wall_time_s", 0) <= 0:
            failures.append(f"run {i}: wall_time_s not recorded")

    # The poison-kill gate is a noiseless-era invariant: under
    # measurement noise, delayed or missed kills are an honest, expected
    # result the suite exists to measure, so noisy runs are exempt.
    survival = [r for r in runs if r["arm"] == "survival" and not _is_noisy(r)]
    if survival:
        kills = sum(r["metrics"]["poison_killed"] for r in survival)
        if kills * 3 < len(survival) * 2:  # at least 2 of 3
            failures.append(
                f"survival killed poison in only {kills}/{len(survival)} seeds"
            )

    # Noise-validity canary: keep_everything never reads outcomes, so
    # its TRUE cum delta must be identical across every noise rate and
    # model at a fixed (seed, cycles, files). Drift = harness bug.
    canary: dict[tuple[int, int, int], set[float]] = {}
    for r in runs:
        if r["arm"] == "keep_everything":
            cfg = r.get("config", {})
            key = (r["seed"], cfg.get("cycles", 0), cfg.get("files_per_cycle", 0))
            canary.setdefault(key, set()).add(r["metrics"]["cum_delta"])
    for key, values in canary.items():
        if len(values) > 1:
            failures.append(
                f"keep_everything true cum_delta varies with noise at "
                f"seed/cycles/files {key}: {sorted(values)}"
            )
    return failures


def paired(
    runs: list[dict[str, Any]],
    arm_a: str,
    arm_b: str,
    metric: str = "cum_delta",
) -> list[dict[str, str]]:
    """Per-seed paired differences of ``metric`` between two arm prefixes.

    Flake marks are a fixed property of the world at a given (seed,
    rate, model), so arms within one label cell are exactly PAIRED:
    the honest comparison is per-seed differences, win counts, and
    medians, not overlapping mean±std columns. Arm names match on the
    group-key prefix before the variant suffix, e.g. ``survival`` vs
    ``evict_on_negative:...,k=2``: pass the prefixes as printed by the
    table and each label cell is compared independently. An arm prefix
    that matches SEVERAL variants in one cell (``evict_on_negative``
    matches k=1, k=2, and k=3) is ambiguous — which variant wins would
    silently change the verdict — so it raises; qualify the arm with
    its variant key instead.
    """

    def cell(run: dict[str, Any]) -> str:
        label = run.get("label") or ""
        # The variant suffix (",k=2", ",m=3") names the arm, not the
        # world; the world cell is model+rate.
        return ",".join(p for p in label.split(",") if not p.startswith(("k=", "m=")))

    def matches(run: dict[str, Any], arm: str) -> bool:
        group = _group_key(run)
        if group == arm or group.startswith(arm + ":"):
            return True
        # Variant-qualified form "evict_on_negative:k=2": the base must
        # prefix the group AND the variant must end its label.
        if ":" in arm:
            base, variant = arm.split(":", 1)
            return group.startswith(base + ":") and group.endswith("," + variant)
        return False

    by_cell: dict[str, dict[int, dict[str, tuple[str, float]]]] = {}
    for run in runs:
        side = "a" if matches(run, arm_a) else "b" if matches(run, arm_b) else None
        if side is None:
            continue
        slot = by_cell.setdefault(cell(run), {}).setdefault(run["seed"], {})
        group = _group_key(run)
        if side in slot and slot[side][0] != group:
            raise ValueError(
                f"ambiguous arm {arm_a if side == 'a' else arm_b!r}: both "
                f"{slot[side][0]!r} and {group!r} match in cell "
                f"{cell(run)!r}; qualify the variant (e.g. "
                "'evict_on_negative:k=2')"
            )
        slot[side] = (group, run["metrics"][metric])

    rows: list[dict[str, str]] = []
    for cell_key in sorted(by_cell):
        diffs = [
            seeds["a"][1] - seeds["b"][1]
            for seeds in by_cell[cell_key].values()
            if "a" in seeds and "b" in seeds
        ]
        if not diffs:
            continue
        diffs.sort()
        wins = sum(1 for d in diffs if d > 0)
        losses = sum(1 for d in diffs if d < 0)
        rows.append(
            {
                "cell": cell_key or "(none)",
                "seeds": str(len(diffs)),
                f"{arm_a} wins": str(wins),
                "ties": str(len(diffs) - wins - losses),
                f"{arm_b} wins": str(losses),
                "median diff": f"{statistics.median(diffs):,.0f}",
                "min diff": f"{diffs[0]:,.0f}",
                "max diff": f"{diffs[-1]:,.0f}",
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--fmt", choices=["ascii", "md"], default="ascii")
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--paired",
        nargs=2,
        metavar=("ARM_A", "ARM_B"),
        help="per-seed paired differences between two arms (same-world cells)",
    )
    parser.add_argument(
        "--metric",
        default="cum_delta",
        help="metric for --paired (default cum_delta)",
    )
    args = parser.parse_args(argv)

    payload = json.loads(args.results.read_text())
    runs = payload["runs"] if isinstance(payload, dict) else payload

    if args.paired:
        rows = paired(runs, args.paired[0], args.paired[1], metric=args.metric)
        print(render_table(rows, args.fmt))
        return 0

    if args.check:
        failures = check(runs)
        if failures:
            for failure in failures:
                print(f"FAIL: {failure}", file=sys.stderr)
            return 1
        print(f"PASS: {len(runs)} runs valid")
        return 0

    if runs and "n_entries" in runs[0]:  # scaling results
        headers = list(runs[0].keys())
        rows = [
            {
                h: (
                    "-"
                    if r[h] is None
                    else f"{r[h]:,.1f}"
                    if isinstance(r[h], float)
                    else str(r[h])
                )
                for h in headers
            }
            for r in runs
        ]
        print(render_table(rows, args.fmt))
        return 0

    print(render_table(aggregate(runs), args.fmt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
