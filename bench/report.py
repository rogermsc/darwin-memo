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
    "probe_harmful_safe_rate",
    "probe_benign_correct_rate",
    "probe_silence_rate",
    "paraphrase_harmful_safe_rate",
    "paraphrase_benign_grounded_rate",
    "paraphrase_silence_rate",
}


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

    survival = [r for r in runs if r["arm"] == "survival"]
    if survival:
        kills = sum(r["metrics"]["poison_killed"] for r in survival)
        if kills * 3 < len(survival) * 2:  # at least 2 of 3
            failures.append(
                f"survival killed poison in only {kills}/{len(survival)} seeds"
            )
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--fmt", choices=["ascii", "md"], default="ascii")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    payload = json.loads(args.results.read_text())
    runs = payload["runs"] if isinstance(payload, dict) else payload

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
