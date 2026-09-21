"""Reconstruct the central attack table from committed per-seed observations.

Run from the repository root with Python 3.10 or later. No install or network.
"""

import argparse
import hashlib
import json
import re
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROWS = [
    ("survival", {}),
    ("evict_on_negative", {"strikes": 1}),
    ("evict_on_negative", {"strikes": 3}),
    ("evict_consecutive", {"strikes": 2}),
    ("quarantine", {}),
    ("policy_bandit", {}),
    ("keep_everything", {}),
]
BUDGETS = (0, 1, 2, 4, 8)


def reconstruct_counter(path: Path, tex: str) -> None:
    """Reconstruct the negative finding from the wider counter sweep."""
    runs = json.loads(path.read_text())["runs"]
    table = tex.split(r"\label{tab:countersweep}")[1].split(r"\end{tabular}")[0]
    for label, arm in (
        ("lifetime", "evict_on_negative"),
        ("consecutive", "evict_consecutive"),
    ):
        line = next(line for line in table.splitlines() if line.startswith(label))
        cells = line.split("&")[1:]
        if len(cells) != 7:
            raise ValueError("Counter table has a different number of thresholds")
        for strikes, cell in zip((1, 2, 3, 5, 8, 12, 20), cells, strict=True):
            matched = [
                r
                for r in runs
                if r["arm"] == arm
                and r["config"].get("strikes") == strikes
                and r["config"]["lie_budget"] == 2
            ]
            if sorted(r["seed"] for r in matched) != list(range(30)):
                raise ValueError(f"{arm} k={strikes}: missing or duplicate seeds")
            values = [
                round(statistics.mean(r["metrics"][key] for r in matched), 2)
                for key in ("probe_benign_correct_rate", "poison_killed")
            ]
            printed = [float(v) for v in re.findall(r"\d*\.\d+", cell)]
            if values != printed:
                raise ValueError(
                    f"Counter table mismatch: {label} k={strikes}: "
                    f"{values} != {printed}"
                )
    print("Counter input SHA256:", hashlib.sha256(path.read_bytes()).hexdigest())
    print("All 14 printed counter-sweep cells agree with the per-seed reconstruction.")


def reconstruct(path: Path) -> list[tuple[str, list[str]]]:
    runs = json.loads(path.read_text())["runs"]
    rows = []
    for arm, settings in ROWS:
        cells = []
        for budget in BUDGETS:
            matched = [
                r
                for r in runs
                if r["arm"] == arm
                and r["config"]["lie_budget"] == budget
                and all(r["config"].get(k) == v for k, v in settings.items())
            ]
            seeds = [r["seed"] for r in matched]
            if sorted(seeds) != list(range(30)):
                raise ValueError(
                    f"{arm} {settings} b={budget}: "
                    f"expected each seed 0..29 exactly once; got {seeds}"
                )
            delta = (
                statistics.mean(r["metrics"]["cum_delta"] for r in matched) / 1_000_000
            )
            capability = statistics.mean(
                r["metrics"]["probe_benign_correct_rate"] for r in matched
            )
            cells.append(f"{delta:.2f} / {capability:.2f}")
        rows.append((arm + (" " + str(settings) if settings else ""), cells))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data", type=Path, default=ROOT / "bench/results/adversary.json"
    )
    parser.add_argument(
        "--counter-data", type=Path, default=ROOT / "bench/results/counter_sweep.json"
    )
    args = parser.parse_args()
    rows = reconstruct(args.data)
    print(
        "Filesystem-backed simulation; restoration penalty = -3 * protected file size."
    )
    print(
        "Mean true modeled outcome (millions) / benign capability. "
        "30 paired seeds per cell."
    )
    print("Input SHA256:", hashlib.sha256(args.data.read_bytes()).hexdigest())
    print("| Arm | " + " | ".join(f"b={b}" for b in BUDGETS) + " |")
    print("|---|" + "---|" * len(BUDGETS))
    for arm, cells in rows:
        print("| " + arm + " | " + " | ".join(cells) + " |")
    # Read the printed result independently, before any generated replacement.
    tex = (ROOT / "paper/sections/experiments.tex").read_text()
    table = tex.split(r"\label{tab:adversary}")[1].split(r"\end{tabular}")[0]
    printed = [line for line in table.splitlines() if " / " in line and "&" in line]
    if len(printed) != len(rows):
        raise ValueError("Printed attack table has a different row count")
    for (_, cells), line in zip(rows, printed, strict=True):
        printed_cells = line.split("&")[1:]
        if len(printed_cells) != len(BUDGETS):
            raise ValueError("Printed row has a different number of budgets")
        for expected, found in zip(cells, printed_cells, strict=True):
            numbers = re.findall(r"-?\d+\.\d+", found.replace("$-$", "-"))
            if numbers != expected.split(" / "):
                raise ValueError(
                    f"Printed table mismatch: expected {expected}, found {found}"
                )
    print("All 35 printed cells agree with the per-seed reconstruction.")
    reconstruct_counter(args.counter_data, tex)


if __name__ == "__main__":
    main()
