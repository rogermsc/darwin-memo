"""PaperClaimEnv: does survival selection work on a literature record?

The claim under test is the one the environment exists to make -- that a
stale citation dies for the same reason a poisoned runbook entry does, once
something measures it. Nothing here grades an answer: every outcome is a
float compared against a number in ``bench/results/external/``.
"""

from __future__ import annotations

import pytest

from bench.paperclaim_env import (
    PaperClaimEnv,
    build_claims,
    claim_entries,
)
from darwin_memo import MemoryStore, SurvivalConfig, SurvivalLoop, Task

# The corpus consolidates at the default floor; see the module docstring.
MERGE = 0.9


def test_corpus_is_built_from_the_paper_and_carries_stale_claims() -> None:
    claims = build_claims(seed=0)
    assert len(claims) == 40, "tab:mem0 gives 32 cells and tab:memoryos 8"
    stale = [c for c in claims if not c.accurate]
    assert stale, "a corpus with nothing stale cannot show selection"
    truths = {c.claim_id: c.truth() for c in claims}
    for claim in claims:
        # accurate is bookkeeping, not the measurement: it has to agree with
        # what the evidence actually says, or the label is the fiction.
        assert claim.accurate == (abs(claim.stated - truths[claim.claim_id]) <= 5e-3)


def test_a_stale_claim_carries_a_real_number_from_elsewhere() -> None:
    """Mutation: invent a value instead of transplanting one and this fails."""
    claims = build_claims(seed=0)
    real = {c.truth() for c in claims}
    for claim in claims:
        if not claim.accurate:
            assert claim.stated in real, (
                f"{claim.claim_id} states {claim.stated}, which appears in no "
                "cell -- stale claims are transplanted, never invented"
            )


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("The paper reports 0 for it. Safe to cite.", 1.0),
        ("The paper reports 8 for it. Safe to cite.", -3.0),
        ("That figure is stale, do not cite it.", 0.0),
        ("Safe to cite.", 0.0),  # cited but quoted nothing: nothing measurable
    ],
)
def test_verify_measures_the_quoted_figure(answer: str, expected: float) -> None:
    env = PaperClaimEnv(seed=0)
    target = next(
        c for c in env.claims if c.evidence_key == "authority_attacker_persisted_mean"
    )
    assert target.truth() == 0.0
    task = Task(prompt="cite?", context={"claim_id": target.claim_id})
    assert env.verify(task, answer).delta == expected


@pytest.mark.parametrize("seed", range(6))
def test_stale_claims_die_and_accurate_ones_do_not(seed: int) -> None:
    """The headline: selection separates the two, on every seed.

    Not "every stale claim dies". A claim only dies if retrieval lets it
    decide something, and a claim that never decides can only starve -- the
    same carve-out the poison-kill metric makes elsewhere in this repo. What
    is asserted is the separation, which is what the mechanism claims.
    """
    env = PaperClaimEnv(seed=seed)
    stale = {c.claim_id for c in env.claims if not c.accurate}
    accurate = {c.claim_id for c in env.claims} - stale
    assert stale and accurate

    store = MemoryStore(upkeep=0.05)
    for entry in claim_entries(env.claims):
        store.add(entry)
    config = SurvivalConfig(cycles=30, merge_threshold=MERGE)
    SurvivalLoop(store, env, config=config).run()

    live = {
        e.sources[0].removeprefix("paper-claim:") for e in store.alive() if e.sources
    }
    stale_survival = len(live & stale) / len(stale)
    accurate_survival = len(live & accurate) / len(accurate)
    assert stale_survival <= 0.35, f"stale survival {stale_survival:.2f}"
    assert accurate_survival >= 0.45, f"accurate survival {accurate_survival:.2f}"
    assert stale_survival < accurate_survival


@pytest.mark.parametrize("value", [1_000_000.0, 0.00001, -2_500_000.0, 12345.0])
def test_quoted_figure_survives_scientific_notation(value: float) -> None:
    """Corpus answers format the figure with :g, which switches to scientific
    notation at large/small magnitudes; the quote regex must parse whatever :g
    emits or an accurate claim is mis-scored as a false citation. Mutation: drop
    the [eE] branch from _QUOTED and the >=1e6 / <1e-4 cases capture only the
    mantissa (float 1.0, not 1e6) and reconcile falsely."""
    from bench.paperclaim_env import _QUOTED

    rendered = f"The paper reports {value:g} for it."
    match = _QUOTED.search(rendered)
    assert match is not None
    assert float(match.group(1)) == value
