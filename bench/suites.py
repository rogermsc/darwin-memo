"""Run matrices: headline, ablation, scaling, smoke."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from darwin_memo import MemoryStore, consolidate

from .corpus import synthetic_entries, synthetic_queries
from .policies import ARMS


@dataclass
class RunSpec:
    suite: str
    arm: str
    seed: int
    cycles: int = 30
    files_per_cycle: int = 12
    overrides: dict[str, Any] = field(default_factory=dict)
    label: str = ""


def headline_suite(seeds: list[int]) -> list[RunSpec]:
    return [
        RunSpec(suite="headline", arm=arm, seed=seed) for arm in ARMS for seed in seeds
    ]


# One knob at a time, survival arm only, defaults marked in the report.
ABLATION_GRID: dict[str, list[Any]] = {
    "upkeep": [0.01, 0.05, 0.1, 0.2],
    "credit_gain": [0.15, 0.3, 0.6, 1.2],
    "resource_scale": [25_000.0, 100_000.0, 400_000.0],
    "merge_threshold": [0.4, 0.55, 0.7],
    "consolidate_every": [0, 5],  # 0 disables consolidation
    "min_coverage": [0.15, 0.25, 0.4],
}

ABLATION_DEFAULTS: dict[str, Any] = {
    "upkeep": 0.05,
    "credit_gain": 0.6,
    "resource_scale": 100_000.0,
    "merge_threshold": 0.55,
    "consolidate_every": 5,
    "min_coverage": 0.25,
}


def ablation_suite(seeds: list[int]) -> list[RunSpec]:
    specs: list[RunSpec] = []
    for knob, values in ABLATION_GRID.items():
        for value in values:
            for seed in seeds:
                specs.append(
                    RunSpec(
                        suite="ablation",
                        arm="survival",
                        seed=seed,
                        overrides={knob: value},
                        label=f"{knob}={value}",
                    )
                )
    return specs


def smoke_suite() -> list[RunSpec]:
    specs = [
        RunSpec(suite="smoke", arm=arm, seed=seed, cycles=12, files_per_cycle=8)
        for arm in ARMS
        for seed in (0, 1, 2)
    ]
    # A noisy slice so the FlakyStorageEnv path cannot rot unexercised
    # in CI. One cell per noise model, both selection families.
    for arm, extra, suffix, model, rate in (
        ("survival", {}, "", "flip", 0.2),
        ("evict_on_negative", {"strikes": 1}, ",k=1", "flip", 0.2),
        ("evict_on_negative", {"strikes": 2}, ",k=2", "false_bad", 0.2),
        ("quarantine", {"suspend": 3}, ",m=3", "magnitude", 0.2),
    ):
        specs.append(
            RunSpec(
                suite="smoke",
                arm=arm,
                seed=0,
                cycles=12,
                files_per_cycle=8,
                overrides={"flake_rate": rate, "noise_model": model, **extra},
                label=f"model={model},rate={rate:.2f}{suffix}",
            )
        )
    # A TestSuiteEnv slice so the second environment family cannot rot
    # unexercised in CI: one clean run per selection family plus one
    # flaky-pass-count cell.
    for arm, extra, suffix, rate in (
        ("survival", {}, "", 0.0),
        ("evict_on_negative", {"strikes": 1}, ",k=1", 0.0),
        ("keep_everything", {}, "", 0.0),
        ("survival", {}, "", 0.2),
    ):
        noisy = {"flake_rate": rate} if rate else {}
        specs.append(
            RunSpec(
                suite="smoke",
                arm=arm,
                seed=0,
                cycles=12,
                overrides={"env_family": "testsuite", **noisy, **extra},
                label=f"env=testsuite,rate={rate:.2f}{suffix}",
            )
        )
    return specs


# The noisy grid: the ledger against the heuristic family's best selves.
# Cells past rate 0.20 exist to find the LEDGER's own failure boundary,
# not just the baselines'; the magnitude model is the one cell where
# sign-driven heuristics are immune by construction and only credit
# that reads magnitudes can degrade.
NOISY_VARIANTS: list[tuple[str, dict[str, Any], str]] = [
    ("survival", {}, ""),
    ("evict_on_negative", {"strikes": 1}, ",k=1"),
    ("evict_on_negative", {"strikes": 2}, ",k=2"),
    ("evict_on_negative", {"strikes": 3}, ",k=3"),
    ("evict_consecutive", {"strikes": 2}, ",k=2"),
    ("quarantine", {"suspend": 3}, ",m=3"),
    ("keep_everything", {}, ""),  # true-delta canary: noise-invariant
]

NOISY_CELLS: list[tuple[str, float]] = [
    ("none", 0.0),  # in-suite reproduction of the deterministic tie
    *[("flip", r) for r in (0.05, 0.10, 0.20, 0.35, 0.50)],
    *[("false_bad", r) for r in (0.05, 0.10, 0.20, 0.35)],
    *[("magnitude", r) for r in (0.10, 0.20)],
]


def noisy_suite(seeds: list[int]) -> list[RunSpec]:
    specs: list[RunSpec] = []
    for model, rate in NOISY_CELLS:
        for arm, extra, suffix in NOISY_VARIANTS:
            for seed in seeds:
                specs.append(
                    RunSpec(
                        suite="noisy",
                        arm=arm,
                        seed=seed,
                        overrides={
                            "flake_rate": rate,
                            "noise_model": "flip" if model == "none" else model,
                            **extra,
                        },
                        label=f"model={model},rate={rate:.2f}{suffix}",
                    )
                )
    # Sensitivity cells: resource_scale=400k shrinks per-event credit
    # (tanh of a quarter the argument), so magnitude lies genuinely
    # move credit instead of being clipped at the energy cap. The
    # magnitude-model cell is the load-bearing one: it is the only
    # configuration in the grid where size lies can move credit at all.
    # The rate-0.00 cell anchors the comparison at the same scale.
    for model, rate in (
        ("none", 0.0),
        ("flip", 0.20),
        ("false_bad", 0.20),
        ("magnitude", 0.20),
    ):
        for seed in seeds:
            specs.append(
                RunSpec(
                    suite="noisy",
                    arm="survival",
                    seed=seed,
                    overrides={
                        "flake_rate": rate,
                        "noise_model": "flip" if model == "none" else model,
                        "resource_scale": 400_000.0,
                    },
                    label=f"model={model},rate={rate:.2f},scale=400k",
                )
            )
    return specs


def llm_suite(seeds: list[int], model: str) -> list[RunSpec]:
    """Opt-in: survival with a local model answering through the full
    3-stage protocol. Sampled, not deterministic, never run in CI."""
    return [
        RunSpec(
            suite="llm",
            arm="survival_llm",
            seed=seed,
            cycles=12,
            files_per_cycle=8,
            overrides={"llm_model": model},
            label=f"model={model}",
        )
        for seed in seeds
    ]


# ---------------------------------------------------------------------------
# Scaling probe (timed micro-operations, not policy runs)
# ---------------------------------------------------------------------------


def _timed(fn: Any, repeats: int = 3) -> float:
    """Median wall time over repeats, in milliseconds."""
    times = []
    for _ in range(repeats):
        start = time.perf_counter()
        fn()
        times.append((time.perf_counter() - start) * 1000)
    return sorted(times)[len(times) // 2]


def scaling_suite(full: bool = False) -> list[dict[str, Any]]:
    """Wall-time for core operations at 100 / 1k / 10k entries.

    ``consolidate`` is O(N^2) pairwise similarity, so the 10k cell only
    runs with ``--full``. That hot spot is a finding, not a secret.
    """
    return [_scaling_row(n, full) for n in (100, 1_000, 10_000)]


def _scaling_row(n: int, full: bool) -> dict[str, Any]:
    queries = synthetic_queries(20, seed=7)

    def build() -> MemoryStore:
        store = MemoryStore()
        for e in synthetic_entries(n, seed=7):
            store.add(e)
        return store

    store = build()
    # Warm the retriever token cache the way real use would.
    store.retrieve(queries[0])

    row: dict[str, Any] = {
        "n_entries": n,
        "add_all_ms": _timed(build),
        "retrieve_20_ms": _timed(lambda: [store.retrieve(q) for q in queries]),
        "charge_upkeep_ms": _timed(store.charge_upkeep),
    }
    if n < 10_000 or full:
        fresh = build()
        row["consolidate_ms"] = _timed(
            lambda: consolidate(fresh, cycle=0, threshold=0.55), repeats=1
        )
    else:
        row["consolidate_ms"] = None  # gated: O(N^2), run with --full
    return row
