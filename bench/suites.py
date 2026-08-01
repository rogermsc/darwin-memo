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


# The external-baseline comparison, kept in its own file so the committed
# headline.json stays byte-stable. All three arms hold the eviction RATE
# fixed at survival's per-cycle death counts and differ only in WHO dies:
# at random, by a hand-designed salience score (Generative Agents-style),
# or by the conserved-resource energy ledger.
SALIENCE_ARMS = ("survival", "random_matched", "salience_matched")


def salience_suite(seeds: list[int]) -> list[RunSpec]:
    return [
        RunSpec(suite="salience", arm=arm, seed=seed)
        for arm in SALIENCE_ARMS
        for seed in seeds
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
    # policy_bandit is stdlib and deterministic, so unlike judge_settled
    # (sampled, never CI) its paths stay smoke-covered: one clean cell,
    # one noisy cell.
    specs.append(
        RunSpec(
            suite="smoke", arm="policy_bandit", seed=0, cycles=12, files_per_cycle=8
        )
    )
    # salience_matched is stdlib and deterministic (it runs a shadow
    # survival for its budget, like random_matched), so it stays
    # smoke-covered to keep the code path from rotting in CI.
    specs.append(
        RunSpec(
            suite="smoke", arm="salience_matched", seed=0, cycles=12, files_per_cycle=8
        )
    )
    specs.append(
        RunSpec(
            suite="smoke",
            arm="policy_bandit",
            seed=0,
            cycles=12,
            files_per_cycle=8,
            overrides={"flake_rate": 0.2, "noise_model": "flip"},
            label="model=flip,rate=0.20",
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


# The curation-targeted threat model (bench/adversary.py): the same
# mechanisms as the noise grid, attacked instead of merely lied to.
# Budget 0 reproduces the deterministic headline tie in-suite and is
# the canary that the wrapper adds no behaviour when unfunded.
ADVERSARY_BUDGETS: tuple[int, ...] = (0, 1, 2, 4, 8)

ADVERSARY_VARIANTS: list[tuple[str, dict[str, Any], str]] = [
    ("survival", {}, ""),
    ("evict_on_negative", {"strikes": 1}, ",k=1"),
    ("evict_on_negative", {"strikes": 3}, ",k=3"),
    ("evict_consecutive", {"strikes": 2}, ",k=2"),
    ("quarantine", {"suspend": 3}, ",m=3"),
    ("policy_bandit", {}, ""),
    ("keep_everything", {}, ""),  # true-delta canary: attack-invariant
]


def adversary_suite(seeds: list[int]) -> list[RunSpec]:
    """Denial-of-memory: who survives an attacker aiming at the curator?

    Read the two halves together. ``probe_benign_correct_rate`` is the
    defender's retained capability (the collateral-damage axis that
    MemSecBench reports as its Forget-stage bottleneck), and
    ``poison_killed``/``poison_kill_cycle`` say whether the attacker
    also managed to keep its own entry alive. A mechanism that scores
    well on one and badly on the other has not defended anything.
    """
    return [
        RunSpec(
            suite="adversary",
            arm=arm,
            seed=seed,
            overrides={"lie_budget": budget, **extra},
            label=f"budget={budget}{suffix}",
        )
        for budget in ADVERSARY_BUDGETS
        for arm, extra, suffix in ADVERSARY_VARIANTS
        for seed in seeds
    ]


def bandit_suite(seeds: list[int]) -> list[RunSpec]:
    """The AEL objection, run rather than argued (arXiv 2604.21725).

    policy_bandit across the EXISTING noise grid: the same cells and
    the same seed-derived worlds as the noisy suite, so per-seed
    pairing against the committed noisy results is exact. Matched
    survival cells ride along (deterministic, byte-identical to their
    noisy-suite counterparts at the same seeds), so one file answers
    ``--paired policy_bandit survival`` without concatenating results.
    """
    return [
        RunSpec(
            suite="bandit",
            arm=arm,
            seed=seed,
            overrides={
                "flake_rate": rate,
                "noise_model": "flip" if model == "none" else model,
            },
            label=f"model={model},rate={rate:.2f}",
        )
        for model, rate in NOISY_CELLS
        for arm in ("policy_bandit", "survival")
        for seed in seeds
    ]


JUDGE_MODELS = ("llama3.2:3b", "qwen3:4b")


def judge_suite(seeds: list[int], models: list[str]) -> list[RunSpec]:
    """Opt-in: settlement by an LLM judge instead of measured outcomes.

    Sampled, never CI (the lesson store's first entry). One
    environment family, 12 cycles at 8 files: each judged cycle costs
    one model call and requests queue behind whatever else the local
    server is doing, so the grid is sized to keep total model time
    small. Matched survival cells (same worlds, deterministic) ride
    along so the judge column pairs per seed within one file.
    """
    specs = [
        RunSpec(suite="judge", arm="survival", seed=seed, cycles=12, files_per_cycle=8)
        for seed in seeds
    ]
    for model in models:
        specs += [
            RunSpec(
                suite="judge",
                arm="judge_settled",
                seed=seed,
                cycles=12,
                files_per_cycle=8,
                overrides={"judge_model": model},
                label=f"judge={model}",
            )
            for seed in seeds
        ]
    return specs


# Sizing, stated rather than implied: the LLM-mode pilot (docs/
# integrations/hermes.md) ran 30 cycles at 8 files and saw llama3.2
# kill the actionable poison at cycle 14, while spawn-energy / upkeep
# alone cannot starve an idle entry before roughly cycle 20. 20 cycles
# is therefore the floor that can still tell a blame-driven kill from
# pure starvation, and 6 files per cycle is the budget knob that keeps
# a 5-seed run of one model near an hour of wall clock on an M-series
# laptop (~8-10 s per task, two completions each).
LLM_CYCLES = 20
LLM_FILES_PER_CYCLE = 6

# Hybrid-reasoning families route reasoning to a separate field the
# Ollama client never reads (see OllamaClient): with thinking left on,
# the generation budget can go entirely to thinking and the protocol
# sees empty answers (measured on qwen3:4b at the 1024-token default).
# The suite pins thinking off for these families so the arm measures
# citation behavior rather than an empty-completion artifact.
LLM_THINK_OFF_FAMILIES = ("qwen3",)


def _llm_overrides(model: str, refuse: bool) -> dict[str, Any]:
    overrides: dict[str, Any] = {
        "llm_model": model,
        "llm_refuse_unparseable": refuse,
    }
    if model.startswith(LLM_THINK_OFF_FAMILIES):
        overrides["llm_think"] = False
    return overrides


def llm_suite(seeds: list[int], models: list[str]) -> list[RunSpec]:
    """Opt-in: survival with a local model answering through the full
    3-stage protocol, run with the refuse_unparseable mitigation off
    and on for every model. Sampled, not deterministic, never run in
    CI."""
    return [
        RunSpec(
            suite="llm",
            arm="survival_llm",
            seed=seed,
            cycles=LLM_CYCLES,
            files_per_cycle=LLM_FILES_PER_CYCLE,
            overrides=_llm_overrides(model, refuse),
            label=f"model={model},refuse={'on' if refuse else 'off'}",
        )
        for model in models
        for refuse in (False, True)
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
