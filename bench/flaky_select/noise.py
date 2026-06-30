from __future__ import annotations
import random

def report_runs(true_label: bool, n: int, p_fn: float, p_fp: float,
                rng: random.Random) -> list[bool]:
    """N reported pass/fail runs under two-sided noise.
    true-pass run flips to fail w.p. p_fn; true-fail run flips to pass w.p. p_fp."""
    out = []
    for _ in range(n):
        if true_label:
            out.append(not (rng.random() < p_fn))
        else:
            out.append(rng.random() < p_fp)
    return out

def synthetic_pool(n_candidates: int, true_pos_frac: float,
                   rng: random.Random) -> list[bool]:
    return [rng.random() < true_pos_frac for _ in range(n_candidates)]
