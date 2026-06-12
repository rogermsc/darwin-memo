"""Bootstrap intervals, paired permutation tests, Holm correction.

Stdlib-only, like the rest of the harness, and everything random is
seeded so a rerun reproduces every interval and p-value byte for byte.
The seed is the unit of independence across the whole benchmark (each
(seed, cycle) world is an independent hash-derived draw), so the
bootstrap resamples SEEDS and the permutation test pairs by seed.

Conventions, chosen conservative:

- Percentile bootstrap on the statistic across seed-level values.
- The paired permutation test is exact (all 2^n sign flips enumerated)
  up to ``EXACT_LIMIT`` pairs, seeded Monte Carlo above it, with the
  identity permutation counted in both paths so p is never below
  1/2^n (exact) or 1/(resamples+1) (Monte Carlo).
- Ties count toward p: a permuted statistic within ``_TIE_EPS`` of the
  observed one is treated as at least as extreme. All-zero differences
  (a deterministic tie) therefore give p = 1.0, not a spurious zero.
- Holm-Bonferroni is step-down: raw p ascending, multiplier m - rank,
  running maximum keeps the adjusted sequence monotone, clipped at 1.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from statistics import mean

BOOTSTRAP_RESAMPLES = 10_000
PERMUTATION_RESAMPLES = 20_000
# 2^15 = 32768 sign assignments, cheaper than the Monte Carlo floor and
# exact, so enumeration is both faster and stronger up to here.
EXACT_LIMIT = 15
# Relative tolerance for "as extreme as observed": float resummation in
# a different order must never turn a tie into a win for significance.
_TIE_EPS = 1e-9
_BOOTSTRAP_SEED = 20260612
_PERMUTATION_SEED = 20260613


def bootstrap_ci(
    values: Sequence[float],
    statistic: Callable[[Sequence[float]], float] = mean,
    resamples: int = BOOTSTRAP_RESAMPLES,
    confidence: float = 0.95,
    seed: int = _BOOTSTRAP_SEED,
) -> tuple[float, float]:
    """Seeded percentile-bootstrap CI for ``statistic`` over ``values``.

    Resamples whole values with replacement (the values are per-seed
    metrics, and seeds are the independent unit). Deterministic: the
    RNG is freshly seeded per call, so call order never changes a CI.
    """
    if not values:
        raise ValueError("bootstrap_ci needs at least one value")
    n = len(values)
    if n == 1:
        only = float(statistic(values))
        return (only, only)
    rng = random.Random(seed)
    stats = sorted(
        float(statistic([values[rng.randrange(n)] for _ in range(n)]))
        for _ in range(resamples)
    )
    alpha = (1.0 - confidence) / 2.0
    return (_quantile(stats, alpha), _quantile(stats, 1.0 - alpha))


def _quantile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation quantile of an already sorted list."""
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def paired_permutation_pvalue(
    diffs: Sequence[float],
    resamples: int = PERMUTATION_RESAMPLES,
    exact_limit: int = EXACT_LIMIT,
    seed: int = _PERMUTATION_SEED,
) -> float:
    """Two-sided paired permutation test against a zero mean difference.

    ``diffs`` are per-seed paired differences (arm A minus arm B on the
    same seed, the same world). Under the null the pairing is
    exchangeable, so each difference's sign flips freely: with n pairs
    up to ``exact_limit`` all 2^n assignments are enumerated and p is
    exact; above it, seeded Monte Carlo over ``resamples`` random sign
    assignments with the +1/+1 correction (the identity assignment is
    always in the reference set), so p can never be zero.
    """
    if not diffs:
        raise ValueError("paired_permutation_pvalue needs at least one pair")
    n = len(diffs)
    observed = abs(sum(diffs))
    threshold = observed - _TIE_EPS * max(1.0, *(abs(d) for d in diffs))
    if n <= exact_limit:
        total = 1 << n
        hits = sum(
            1
            for mask in range(total)
            if abs(sum(d if mask >> i & 1 else -d for i, d in enumerate(diffs)))
            >= threshold
        )
        return hits / total
    rng = random.Random(seed)
    hits = sum(
        1
        for _ in range(resamples)
        if abs(sum(d if rng.random() < 0.5 else -d for d in diffs)) >= threshold
    )
    return (hits + 1) / (resamples + 1)


def holm_bonferroni(pvalues: Sequence[float]) -> list[float]:
    """Holm step-down adjusted p-values, returned in the input order.

    Sort raw p ascending; the i-th smallest is multiplied by (m - i);
    a running maximum enforces monotonicity (an adjusted p never sits
    below an earlier, smaller raw p's adjustment); everything clips at
    1. Equal raw p-values share the conservative larger adjustment via
    the same running maximum.
    """
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, idx in enumerate(order):
        running = max(running, (m - rank) * pvalues[idx])
        adjusted[idx] = min(1.0, running)
    return adjusted
