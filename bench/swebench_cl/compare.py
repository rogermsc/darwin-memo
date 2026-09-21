"""Compare paired sequence/run outcomes; missing cost or usage stays unknown.

Cost input maps RESULT_FILENAME::INSTANCE_ID to api_usd, execution_usd,
other_usd, and source (invoice or billing-export reference). Include retries
and lesson generation. This analysis does not authorize calls or spend.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any


def mean(values: list[float]) -> float:
    return statistics.mean(values)


def cost(row: dict[str, Any], bills: dict[str, Any]) -> float | None:
    bill = bills.get(row["billing_key"])
    if not bill or not bill.get("source"):
        return None
    values = [bill.get(key) for key in ("api_usd", "execution_usd", "other_usd")]
    if any(value is None for value in values):
        return None
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        for value in values
    ):
        raise ValueError("Billing amounts must be finite and nonnegative")
    return sum(values)


def usage(row: dict[str, Any]) -> dict[str, int] | None:
    calls = row.get("model", {}).get("provider_calls", [])
    if not calls or any(not c.get("usage") for c in calls):
        return None
    keys = ("prompt_tokens", "completion_tokens")
    if any(not isinstance(c["usage"].get(k), int) for c in calls for k in keys):
        return None
    return {k: sum(c["usage"][k] for c in calls) for k in keys}


def interval(groups: dict[str, list[float]]) -> tuple[float, list[float]]:
    """Resample repositories, then repeated runs; never resample task rows."""
    sequences = sorted(groups)
    estimate = mean([mean(groups[s]) for s in sequences])
    rng = random.Random(0)
    samples = []
    for _ in range(10_000):
        draws = []
        for sequence in rng.choices(sequences, k=len(sequences)):
            values = groups[sequence]
            draws.append(mean(rng.choices(values, k=len(values))))
        samples.append(mean(draws))
    samples.sort()
    return estimate, [samples[249], samples[9749]]


def compare(directory: Path, bills: dict[str, Any]) -> dict[str, Any]:
    cells: dict[str, dict[tuple[str, int], list[dict[str, Any]]]] = defaultdict(dict)
    for path in sorted(directory.glob("*.json")):
        if path.name == "MANIFEST.json":
            continue
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict) or "runs" not in payload:
            continue
        grouped: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
        for row in payload["runs"]:
            if row.get("suite") != "swebench_cl_pilot":
                raise ValueError(f"{path}: not a coding-agent sequence")
            if row.get("eval", {}).get("mode") != "docker" or not row["eval"].get(
                "eval_executed"
            ):
                raise ValueError(
                    f"{path}: incomplete or simulated execution "
                    "must be reported separately"
                )
            if row.get("config", {}).get("lie_budget", 0):
                raise ValueError(
                    "Use a separate attack analysis for corrupted feedback"
                )
            row["billing_key"] = path.name + "::" + row["instance_id"]
            grouped[(row["arm"], row["sequence"], row["seed"])].append(row)
        for (arm, sequence, seed), rows in grouped.items():
            key = (sequence, seed)
            if key in cells[arm]:
                raise ValueError(f"Duplicate sequence/run: {arm} {key}")
            if len({r["instance_id"] for r in rows}) != len(rows):
                raise ValueError(f"Duplicate tasks: {arm} {key}")
            cells[arm][key] = rows
    if "memory_off" not in cells:
        raise ValueError("A paired no-memory baseline is required")
    summaries = {}
    baseline = cells["memory_off"]
    for arm, arm_cells in sorted(cells.items()):
        if set(arm_cells) != set(baseline):
            raise ValueError(f"{arm}: sequence/run identities differ from no memory")
        differences: dict[str, list[float]] = defaultdict(list)
        for key, rows in arm_cells.items():
            reference = baseline[key]
            if [r["instance_id"] for r in rows] != [
                r["instance_id"] for r in reference
            ]:
                raise ValueError(f"{arm} {key}: tasks or order differ from baseline")
            differences[key[0]].append(
                mean([float(r["metrics"]["resolved"]) for r in rows])
                - mean([float(r["metrics"]["resolved"]) for r in reference])
            )
        rows = [r for unit in arm_cells.values() for r in unit]
        costs = [cost(r, bills) for r in rows]
        total = sum(costs) if all(c is not None for c in costs) else None
        uses = [usage(r) for r in rows]
        tokens = (
            {k: sum(u[k] for u in uses) for k in ("prompt_tokens", "completion_tokens")}
            if all(u is not None for u in uses)
            else None
        )
        resolved = sum(bool(r["metrics"]["resolved"]) for r in rows)
        estimate, ci = interval(differences)
        summaries[arm] = {
            "tasks": len(rows),
            "resolved": resolved,
            "resolution_rate": resolved / len(rows),
            "regressed_tasks": sum(
                r["eval"]["p2p_passed"] < r["eval"]["p2p_total"] for r in rows
            ),
            "total_usd": total,
            "usd_per_task": total / len(rows) if total is not None else None,
            "usd_per_resolved_task": total / resolved
            if total is not None and resolved
            else None,
            "tasks_without_complete_cost": sum(c is None for c in costs),
            "provider_tokens": tokens,
            "mean_wall_seconds": mean([r["metrics"]["wall_time_s"] for r in rows]),
            "mean_memory_words": mean([r["lessons"]["tokens"] for r in rows]),
            "paired_success_difference": estimate,
            "hierarchical_95_percent_interval": ci,
            "sequence_count": len(differences),
            "paired_run_count": len(arm_cells),
            "five_point_margin_supported_in_sample": ci[0] > -0.05,
        }
    return {
        "status": (
            "exploratory reconstruction; not a preregistered noninferiority claim"
        ),
        "uncertainty": (
            "repository sequence, then repeated run bootstrap; 10000 draws, seed 0"
        ),
        "margin": -0.05,
        "arms": summaries,
        "limitations": (
            "Few repositories give unstable intervals. Missing billing is unknown, "
            "not zero. Freeze the design before prospective held-out evaluation."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--costs", type=Path)
    args = parser.parse_args()
    bills = json.loads(args.costs.read_text()) if args.costs else {}
    print(json.dumps(compare(args.directory, bills), indent=2))


if __name__ == "__main__":
    main()
