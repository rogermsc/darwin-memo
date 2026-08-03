"""Pre-gate: does survival's tunable-buffer frontier dominate threshold-k?

The Stage-1 gate asks whether survival selection beats the cheap baselines on
the precision/recall plane. The fair comparison is between FAMILIES, because
each rule is really a parameterized family:

- threshold-k: "keep if >= k of N runs pass", k = 1..N. k=1 is any_pass, k=N is
  all-pass, k=ceil(N/2) is majority_vote, and single_run ~ k=1 at N=1. This is
  the discrete baseline family and traces a few points on the P/R plane.
- survival: the energy buffer parameterized by (spawn energy, credit_gain),
  tracing a CONTINUOUS frontier on the same plane.

This module sweeps both families on a synthetic labeled pool under two-sided
noise, draws are PAIRED (every rule sees the same reported-run sequences per
(cell, seed)), and reports, per noise cell: each family's best F1 and whether
survival's frontier Pareto-dominates every threshold-k point. Pure synthetic,
no Docker / API / cost — a free pre-gate before any real-pool spend.

Run: PYTHONPATH=. .venv312/bin/python -m bench.flaky_select.pregate
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

from .metrics import selection_scores
from .noise import report_runs, synthetic_pool
from .rules import keep

# Two-sided noise cells (p_fn, p_fp); the p_fp=0 cell is the one-sided control.
CELLS = [(0.1, 0.05), (0.2, 0.1), (0.2, 0.2), (0.35, 0.2), (0.2, 0.0)]
SPAWN_GRID = [0.25, 0.5, 1.0, 2.0, 3.0, 4.0]
GAIN_GRID = [0.2, 0.4, 0.6, 1.0, 1.5]


def _seed(seed: int, p_fn: float, p_fp: float) -> int:
    key = f"{seed}|{p_fn}|{p_fp}".encode()
    return int.from_bytes(hashlib.sha256(key).digest()[:8], "big")


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _avg_scores(
    labels: list[bool], decide, n: int, p_fn: float, p_fp: float, seeds: list[int]
) -> dict:
    """Average precision/recall/F1 over seeds; PAIRED draws per (cell, seed)."""
    precs, recs, f1s = [], [], []
    for s in seeds:
        rng = random.Random(_seed(s, p_fn, p_fp))
        seqs = [report_runs(t, n, p_fn, p_fp, rng) for t in labels]
        kept = [decide(seq) for seq in seqs]
        sc = selection_scores(labels, kept)
        precs.append(sc["precision"])
        recs.append(sc["recall"])
        f1s.append(sc["f1"])
    return {"precision": _mean(precs), "recall": _mean(recs), "f1": _mean(f1s)}


def _dominates(a: dict, b: dict, eps: float = 1e-9) -> bool:
    """Point a Pareto-dominates-or-equals b on (precision, recall)."""
    return a["precision"] >= b["precision"] - eps and a["recall"] >= b["recall"] - eps


def run_pregate(
    n: int = 5,
    n_candidates: int = 2000,
    true_pos_frac: float = 0.5,
    seeds: list[int] | None = None,
) -> list[dict]:
    seeds = seeds if seeds is not None else list(range(10))
    labels = synthetic_pool(n_candidates, true_pos_frac, random.Random(12345))
    rows = []
    for p_fn, p_fp in CELLS:
        # threshold-k family
        thr = []
        for k in range(1, n + 1):
            sc = _avg_scores(
                labels, lambda seq, k=k: sum(seq) >= k, n, p_fn, p_fp, seeds
            )
            sc["k"] = k
            thr.append(sc)
        # survival family
        surv = []
        for sp in SPAWN_GRID:
            for cg in GAIN_GRID:
                sc = _avg_scores(
                    labels,
                    lambda seq, sp=sp, cg=cg: keep(
                        seq, "survival", credit_gain=cg, spawn=sp
                    ),
                    n,
                    p_fn,
                    p_fp,
                    seeds,
                )
                sc["spawn"], sc["credit_gain"] = sp, cg
                surv.append(sc)
        # Does survival's frontier dominate-or-match EVERY threshold-k point?
        dominated = [any(_dominates(s, t) for s in surv) for t in thr]
        rows.append(
            {
                "p_fn": p_fn,
                "p_fp": p_fp,
                "best_f1_threshold": max(t["f1"] for t in thr),
                "best_f1_survival": max(s["f1"] for s in surv),
                "threshold_pts": [
                    {
                        "k": t["k"],
                        "precision": round(t["precision"], 3),
                        "recall": round(t["recall"], 3),
                        "f1": round(t["f1"], 3),
                    }
                    for t in thr
                ],
                "survival_dominates_all_threshold": all(dominated),
                "n_threshold_dominated": sum(dominated),
                "n_threshold_total": len(thr),
            }
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--seeds", default="0:10")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    a, b = (int(x) for x in args.seeds.split(":"))
    rows = run_pregate(n=args.n, seeds=list(range(a, b)))
    print(
        f"\nPre-gate: survival(buffer-swept) frontier vs threshold-k "
        f"family, N={args.n}\n"
    )
    print(
        f"{'p_fn':>5}{'p_fp':>6}{'bestF1_thr':>11}{'bestF1_surv':>12}"
        f"{'surv>=thr?':>10}{'dom k':>8}"
    )
    for r in rows:
        verdict = "YES" if r["survival_dominates_all_threshold"] else "no"
        print(
            f"{r['p_fn']:>5}{r['p_fp']:>6}{r['best_f1_threshold']:>11.3f}"
            f"{r['best_f1_survival']:>12.3f}{verdict:>10}"
            f"{str(r['n_threshold_dominated']) + '/' + str(r['n_threshold_total']):>8}"
        )
    dominates_all = all(r["survival_dominates_all_threshold"] for r in rows)
    better_f1 = sum(
        1 for r in rows if r["best_f1_survival"] > r["best_f1_threshold"] + 1e-6
    )
    print(
        f"\nVERDICT: survival frontier dominates threshold-k in "
        f"{sum(r['survival_dominates_all_threshold'] for r in rows)}"
        f"/{len(rows)} cells; "
        f"best-F1 strictly higher in {better_f1}/{len(rows)} cells."
    )
    print(
        "PRE-GATE:",
        "PASS (survival frontier ahead)"
        if (dominates_all or better_f1 >= len(rows) - 1)
        else "NO-GO (threshold-k matches/beats survival synthetically)",
    )
    if args.out:
        args.out.write_text(json.dumps(rows, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
