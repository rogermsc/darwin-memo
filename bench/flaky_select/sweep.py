"""Flaky-selection sweep driver.

Runs a grid of (rule, p_fn, p_fp) conditions over multiple seeds and reports
mean precision/recall/F1 per cell.  Designed to be deterministic: each
(seed, rule, p_fn, p_fp) cell seeds its own RNG independently.

CLI usage
---------
python -m bench.flaky_select.sweep [--pool PATH] [--n N] [--seeds a:b] [--out PATH]

  --pool PATH   JSON file with [{"true_label": bool}, ...] (real labels).
                Omit to use synthetic pool (1000 candidates, 50% positive).
  --n N         Number of runs per candidate (default 5).
  --seeds a:b   Half-open range of integer seeds (default 0:10).
  --out PATH    Write JSON rows to this path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from itertools import product
from typing import Any

from bench.flaky_select.metrics import selection_scores
from bench.flaky_select.noise import report_runs, synthetic_pool
from bench.flaky_select.rules import RULES, keep

# ---------------------------------------------------------------------------
# Default grid
# ---------------------------------------------------------------------------
DEFAULT_P_FN = (0.0, 0.1, 0.2, 0.35)
DEFAULT_P_FP = (0.0, 0.1, 0.2)
DEFAULT_N = 5
DEFAULT_SEEDS = range(10)  # 0..9


def _cell_seed(seed: int, rule: str, p_fn: float, p_fp: float) -> int:
    """Derive a stable (cross-process) RNG seed for a sweep cell.

    Uses hashlib instead of Python's builtin hash() to ensure reproducibility
    across separate processes (builtin hash is randomized by PYTHONHASHSEED).
    """
    key = f"{seed}|{rule}|{p_fn}|{p_fp}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


def run_sweep(
    true_labels: list[bool],
    *,
    grid: dict[str, Any] | None = None,
    n: int = DEFAULT_N,
    seeds: range | list[int] = DEFAULT_SEEDS,
) -> list[dict]:
    """Run the sweep and return one row per (rule, p_fn, p_fp) with metrics
    averaged over seeds.

    Parameters
    ----------
    true_labels:
        Ground-truth positive/negative labels for each candidate.
    grid:
        Optional dict with keys ``p_fn`` and ``p_fp`` (iterables of floats).
        Defaults to DEFAULT_P_FN x DEFAULT_P_FP.
    n:
        Number of noisy runs per candidate per seed.
    seeds:
        Iterable of integer seeds.

    Returns
    -------
    List of dicts with keys: rule, p_fn, p_fp, precision, recall, f1, kept_n.
    """
    if grid is None:
        grid = {"p_fn": DEFAULT_P_FN, "p_fp": DEFAULT_P_FP}

    p_fn_vals = grid.get("p_fn", DEFAULT_P_FN)
    p_fp_vals = grid.get("p_fp", DEFAULT_P_FP)

    rows: list[dict] = []

    for rule, p_fn, p_fp in product(RULES, p_fn_vals, p_fp_vals):
        seed_scores: list[dict] = []

        for seed in seeds:
            # Deterministic RNG per (seed, rule, p_fn, p_fp) — stable cross-process seed
            cell_seed = _cell_seed(int(seed), rule, round(p_fn, 6), round(p_fp, 6))
            rng = random.Random(cell_seed)

            kept: list[bool] = []
            for label in true_labels:
                reported = report_runs(label, n, p_fn, p_fp, rng)
                kept.append(keep(reported, rule))

            seed_scores.append(selection_scores(true_labels, kept))

        # Average over seeds
        mean_precision = sum(s["precision"] for s in seed_scores) / len(seed_scores)
        mean_recall = sum(s["recall"] for s in seed_scores) / len(seed_scores)
        mean_f1 = sum(s["f1"] for s in seed_scores) / len(seed_scores)
        mean_kept_n = sum(s["kept_n"] for s in seed_scores) / len(seed_scores)

        rows.append(
            {
                "rule": rule,
                "p_fn": p_fn,
                "p_fp": p_fp,
                "precision": round(mean_precision, 4),
                "recall": round(mean_recall, 4),
                "f1": round(mean_f1, 4),
                "kept_n": round(mean_kept_n, 1),
            }
        )

    return rows


# ---------------------------------------------------------------------------
# Markdown table rendering
# ---------------------------------------------------------------------------


def _fmt(val: float, width: int = 6) -> str:
    return f"{val:.3f}".rjust(width)


def print_markdown_table(rows: list[dict]) -> None:
    """Print an F1/precision/recall markdown table grouped by rule x (p_fn,p_fp)."""
    # Collect axis values in encountered order
    rules_seen: list[str] = []
    conditions_seen: list[tuple] = []
    for row in rows:
        if row["rule"] not in rules_seen:
            rules_seen.append(row["rule"])
        cond = (row["p_fn"], row["p_fp"])
        if cond not in conditions_seen:
            conditions_seen.append(cond)

    # Index for fast lookup
    index: dict[tuple, dict] = {(r["rule"], r["p_fn"], r["p_fp"]): r for r in rows}

    # Header
    cond_headers = [f"pfn={pfn:.2f}/pfp={pfp:.2f}" for pfn, pfp in conditions_seen]
    col_w = max(len(h) for h in cond_headers) + 2  # padding

    header = (
        "| rule".ljust(16)
        + " | "
        + " | ".join(h.center(col_w) for h in cond_headers)
        + " |"
    )
    sep = "|" + "-" * 15 + "|" + ("|" + "-" * (col_w + 2)) * len(conditions_seen) + "|"

    print(header)
    print(sep)

    for rule in rules_seen:
        cells = []
        for pfn, pfp in conditions_seen:
            r = index.get((rule, pfn, pfp))
            if r is None:
                cells.append("   —   ".center(col_w))
            else:
                cell_str = (
                    f"F1={r['f1']:.3f} P={r['precision']:.3f} R={r['recall']:.3f}"
                )
                cells.append(cell_str.center(col_w))
        print(f"| {rule:<14}| " + " | ".join(cells) + " |")


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run flaky-selection sweep over rules x noise grid."
    )
    parser.add_argument(
        "--pool", metavar="PATH", help='JSON file with [{"true_label": bool}, ...]'
    )
    parser.add_argument(
        "--n",
        type=int,
        default=DEFAULT_N,
        help="Runs per candidate per seed (default 5)",
    )
    parser.add_argument(
        "--seeds",
        metavar="A:B",
        default="0:10",
        help="Half-open seed range (default 0:10)",
    )
    parser.add_argument(
        "--out", metavar="PATH", help="Write result rows as JSON to this path"
    )
    return parser.parse_args()


def _parse_seeds(spec: str) -> range:
    parts = spec.split(":")
    if len(parts) == 2:
        return range(int(parts[0]), int(parts[1]))
    return range(int(parts[0]), int(parts[0]) + 1)


def main() -> None:
    args = _parse_args()

    # Load or synthesise true labels
    if args.pool:
        with open(args.pool) as fh:
            records = json.load(fh)
        true_labels = [bool(rec["true_label"]) for rec in records]
        print(
            f"Loaded pool: {len(true_labels)} candidates from {args.pool}",
            file=sys.stderr,
        )
    else:
        # Synthetic: deterministic pool seed = 42
        pool_rng = random.Random(42)
        true_labels = synthetic_pool(1000, 0.5, pool_rng)
        print(
            f"Synthetic pool: {len(true_labels)} candidates, "
            f"{sum(true_labels)} positive ({sum(true_labels) / len(true_labels):.1%})",
            file=sys.stderr,
        )

    seeds = _parse_seeds(args.seeds)
    print(
        f"Grid: p_fn={DEFAULT_P_FN}  p_fp={DEFAULT_P_FP}  n={args.n}  "
        f"seeds={list(seeds)}",
        file=sys.stderr,
    )

    rows = run_sweep(true_labels, n=args.n, seeds=seeds)

    print_markdown_table(rows)

    if args.out:
        with open(args.out, "w") as fh:
            json.dump(rows, fh, indent=2)
        print(f"\nWrote {len(rows)} rows → {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
