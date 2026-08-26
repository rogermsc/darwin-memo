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

import itertools
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


# The 2x2 that attributes the test-suite family's horizon findings.
# Same five arms the withholding and rent grids use, so the comparison
# is against a set the paper already reports rather than a new one.
REDUNDANCY_ARMS: list[tuple[str, dict[str, Any]]] = [
    ("survival", {}),
    ("survival_paced", {}),
    ("evict_on_negative", {"strikes": 1}),
    ("quarantine", {"suspend": 3}),
    ("keep_everything", {}),  # world canary: consolidation-blind by construction
]
REDUNDANCY_CYCLES = (30, 60)


def redundancy_suite(seeds: list[int]) -> list[RunSpec]:
    """Is the corpus the cause, or is the merge?

    The paper explains three test-suite-family results with one sentence
    -- "the corpus is deliberately redundant, so consolidation keeps
    finding surplus to starve long after the storage corpus has settled"
    -- and nothing in this repository ever varied either half of it. A
    named cause with no counterfactual is the class of claim this
    project has been wrong about before.

    So both halves vary, factorially. ``testsuite_twins`` drops the five
    near-duplicates, removing the surplus while leaving the other
    fifteen entries byte-identical; ``consolidate_every`` 0 removes the
    merge while leaving the corpus alone. 2 corpora x 2 merge settings x
    2 horizons x 5 arms x 30 seeds = 1,200 runs.

    Two canaries, both inside the grid. ``keep_everything`` neither
    settles nor consolidates, so every result metric it reports must be
    identical across the merge axis at a fixed corpus -- and its
    ``final_population`` must *differ* across the corpus axis by exactly
    the five dropped entries, or the twin drop never took effect. (Its
    ``cum_delta`` is not that canary: outcomes here are priced per task,
    so an arm that answers the same way pays the same whatever its store
    holds.) And at ``twins=False`` there is no mergeable pair left for
    either setting to act on, so the two merge columns should be the
    same run.

    Predictions are recorded in docs/benchmarks.md in the commit before
    the run.
    """
    return _redundancy_specs(seeds, "redundancy", {})


def redundancy_rent_suite(seeds: list[int]) -> list[RunSpec]:
    """The same 2x2 against the second finding the same sentence explains.

    ``rent_testsuite`` reports that on this family every arm is flat at
    30 cycles and the ledger's first billable decline arrives near cycle
    49, and the paper attributes that to the same redundancy: the
    counters keep a spare to answer with, the ledger consolidates the
    spares away and is the only arm that ever has nothing to say. If
    that is the mechanism, then removing either half should remove the
    bill, not merely shrink it.

    Rent is pinned at 1.0 -- symmetric occupancy, the top of the swept
    range and where the effect is largest -- because the question here
    is attribution, not the shape of the curve, which
    ``rent_testsuite.json`` already maps.

    Predictions are recorded in docs/benchmarks.md in the commit before
    the run.
    """
    return _redundancy_specs(
        seeds, "redundancy_rent", {"env_family": "testsuite_rent", "hold_cost": 1.0}
    )


def _redundancy_specs(
    seeds: list[int], suite: str, extra_world: dict[str, Any]
) -> list[RunSpec]:
    """The shared 2x2 body, so the two grids cannot drift apart."""
    return [
        RunSpec(
            suite=suite,
            arm=arm,
            seed=seed,
            cycles=cycles,
            overrides={
                **TESTSUITE_OVERRIDES,
                **extra_world,
                "testsuite_twins": twins,
                "consolidate_every": every,
                **extra,
            },
            label=f"twins={twins},consolidate={every},cycles={cycles}",
        )
        for twins in (True, False)
        for every in (5, 0)
        for cycles in REDUNDANCY_CYCLES
        for arm, extra in REDUNDANCY_ARMS
        for seed in seeds
    ]


# All 32 subsets of the five twin pairs, as masks over them. Full
# enumeration rather than a sample: the question is whether the loss is
# a dose or a particular entry, and any sampled subset would leave that
# confounded exactly where it started.
REDUNDANCY_MASKS: tuple[str, ...] = tuple(
    "".join(bits) for bits in itertools.product("01", repeat=5)
)


def redundancy_dose_suite(seeds: list[int]) -> list[RunSpec]:
    """Is it a dose, or is it one entry?

    ``redundancy_suite`` measured two points -- all five twins and none
    -- and found that dropping them recovers 93% of the second-family
    loss. Two points cannot distinguish "the loss scales with how much
    redundancy the corpus carries" from "the loss is one of these five
    entries", and the paper currently asserts the first ("the effect is
    roughly linear in that level over the only two points we have"),
    which is a claim from a sample of two.

    So every subset runs. 32 masks x 2 horizons x 5 arms x 30 seeds =
    9,600 runs, at the published ``consolidate_every`` of 5. Within a
    dose the mask varies which twins survive, so the between-dose and
    within-dose spreads are separately measurable, and a single
    load-bearing entry shows up as a within-dose spread that swamps the
    between-dose one.

    The four fix-advice twins and the dedupe-protector twin are not
    interchangeable by construction -- the protector competes with the
    poison for the destructive prompt -- so the null here is a real
    possibility rather than a formality.

    ``"11111"`` and ``"00000"`` reproduce ``redundancy.json``'s
    ``consolidate_every=5`` cells exactly; that is the canary, and it
    crosses two files.

    Predictions are recorded in docs/benchmarks.md in the commit before
    the run.
    """
    return [
        RunSpec(
            suite="redundancy_dose",
            arm=arm,
            seed=seed,
            cycles=cycles,
            overrides={
                **TESTSUITE_OVERRIDES,
                "testsuite_twins": mask,
                "consolidate_every": 5,
                **extra,
            },
            label=f"twins={mask},cycles={cycles}",
        )
        for mask in REDUNDANCY_MASKS
        for cycles in REDUNDANCY_CYCLES
        for arm, extra in REDUNDANCY_ARMS
        for seed in seeds
    ]


# The two pair similarities in this corpus are 0.6875 (clamp bound) and
# 0.8125 (the other four), so a threshold sweep has exactly two steps if
# the effect is the merge event and none if it is something else. Both
# boundary values are swept: ``consolidate`` merges at ``>=``, so a pair
# at exactly its own similarity still merges, and a cell that disagrees
# would be reporting on a comparison operator rather than a mechanism.
MERGE_THRESHOLDS = (
    0.50,
    0.55,
    0.60,
    0.65,
    0.6875,
    0.70,
    0.75,
    0.80,
    0.8125,
    0.85,
    0.90,
)


def merge_threshold_suite(seeds: list[int]) -> list[RunSpec]:
    """Which pairs merge, or how close they were to merging?

    ``redundancy_dose`` put the whole second-family loss on one of five
    near-duplicate pairs and could not say why that one. The only
    property distinguishing it is that its similarity is lowest --
    $0.6875$ against $0.8125$ -- so it is the pair nearest the merge
    floor. That is a correlate, and this grid is the counterfactual it
    needs: move the floor instead of the corpus.

    The prediction the design turns on is a *step*. Below $0.6875$ all
    five pairs merge, between $0.6875$ and $0.8125$ only the other four
    do, above $0.8125$ none do. If the loss is the clamp pair's merge,
    each band is flat and the two steps land on those numbers; if it is
    proximity to the floor, the loss moves with the floor inside a band.

    ``merge_threshold`` has always set the query protocol's conflict
    floor too (``SurvivalConfig.conflict_threshold`` is new and defaults
    to that coupling), so sweeping it naively sweeps two mechanisms.
    Both columns run: coupled, which is what every existing
    ``merge_threshold`` number in this repository was produced under,
    and pinned at the default $0.55$. 11 thresholds x 2 couplings x 2
    horizons x 5 arms x 30 seeds = 6,600 runs.

    Canaries. At $0.55$ the two columns are the same configuration and
    must be the same run; and both reproduce ``redundancy_dose.json``'s
    ``"11111"`` cells, which crosses two files.

    Predictions are recorded in docs/benchmarks.md in the commit before
    the run.
    """
    return [
        RunSpec(
            suite="merge_threshold",
            arm=arm,
            seed=seed,
            cycles=cycles,
            overrides={
                **TESTSUITE_OVERRIDES,
                "merge_threshold": threshold,
                **({} if coupled else {"conflict_threshold": 0.55}),
                "consolidate_every": 5,
                **extra,
            },
            label=f"threshold={threshold},coupled={coupled},cycles={cycles}",
        )
        for coupled in (True, False)
        for threshold in MERGE_THRESHOLDS
        for cycles in REDUNDANCY_CYCLES
        for arm, extra in REDUNDANCY_ARMS
        for seed in seeds
    ]
