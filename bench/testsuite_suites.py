"""Run matrices for the TestSuiteEnv family: headline analog and noisy.

The grids mirror the StorageEnv suites so cross-family tables read the
same way: the headline analog runs all eight arms on truthful
measurements, and the noisy grid runs the ledger against the heuristic
family's best selves under flaky pass counts.

The noise cells are pre-committed in docs/benchmarks.md before any
results exist (house rule: the doc states the cells, then the results
fill them). Changing ``TESTSUITE_NOISY_RATES`` after results are
published is rewriting the experiment; the unit tests pin the grid to
the documented one.
"""

from __future__ import annotations

from typing import Any

from .policies import ARMS
from .suites import RunSpec

# Every testsuite spec carries the family and the env's one world knob
# in overrides, so both land in the recorded config and the manifest's
# config hash. files_per_cycle is a StorageEnv knob and is deliberately
# absent from this family's configs.
TESTSUITE_OVERRIDES: dict[str, Any] = {"env_family": "testsuite"}

# Flaky-pass-count rates, pre-committed: 0.00 anchors the deterministic
# comparison, then 5% to 20% in the band real CI flakiness occupies.
# The grid exists to answer one question with a number: at what flake
# rate does the ledger's forgiveness beat a naive strike counter.
TESTSUITE_NOISY_RATES: tuple[float, ...] = (0.0, 0.05, 0.10, 0.15, 0.20)

# Same variant set as the StorageEnv noisy suite: the counter family's
# best selves plus the outcome-blind canary.
TESTSUITE_NOISY_VARIANTS: list[tuple[str, dict[str, Any], str]] = [
    ("survival", {}, ""),
    ("evict_on_negative", {"strikes": 1}, ",k=1"),
    ("evict_on_negative", {"strikes": 2}, ",k=2"),
    ("evict_on_negative", {"strikes": 3}, ",k=3"),
    ("evict_consecutive", {"strikes": 2}, ",k=2"),
    ("quarantine", {"suspend": 3}, ",m=3"),
    ("keep_everything", {}, ""),  # true-delta canary: noise-invariant
]


def testsuite_suite(seeds: list[int]) -> list[RunSpec]:
    """All eight arms on truthful TestSuiteEnv measurements."""
    return [
        RunSpec(
            suite="testsuite",
            arm=arm,
            seed=seed,
            overrides=dict(TESTSUITE_OVERRIDES),
        )
        for arm in ARMS
        for seed in seeds
    ]


def testsuite_noisy_suite(seeds: list[int]) -> list[RunSpec]:
    """The pre-committed flaky-pass-count grid."""
    specs: list[RunSpec] = []
    for rate in TESTSUITE_NOISY_RATES:
        model = "none" if rate == 0.0 else "flaky"
        for arm, extra, suffix in TESTSUITE_NOISY_VARIANTS:
            for seed in seeds:
                specs.append(
                    RunSpec(
                        suite="testsuite_noisy",
                        arm=arm,
                        seed=seed,
                        overrides={
                            **TESTSUITE_OVERRIDES,
                            "flake_rate": rate,
                            **extra,
                        },
                        label=f"model={model},rate={rate:.2f}{suffix}",
                    )
                )
    return specs
