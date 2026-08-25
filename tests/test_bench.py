"""Unit tests for the benchmark harness policies and reporting."""

import tempfile
from pathlib import Path
from typing import Any

import pytest

from bench.fixtures import active_poison_alive, build_headline_store, poison_ids
from bench.policies import run_random_matched, run_recency, run_ttl
from bench.report import aggregate, check
from bench.runner import run_one
from darwin_memo import MemoryEntry, MemoryStore, StorageEnv


class NullEnv:
    """No tasks, so policies exercise only their eviction rules."""

    resource_scale = 1.0

    def tasks(self, cycle):
        return []

    def verify(self, task, answer_text):
        raise AssertionError("no tasks to verify")


def make_store(n: int = 4) -> MemoryStore:
    store = MemoryStore()
    for i in range(n):
        store.add(
            MemoryEntry(question=f"What about item {i}?", answer=f"Item {i} info.")
        )
    return store


def test_ttl_evicts_exactly_at_age():
    store = make_store(3)
    result = run_ttl(store, NullEnv(), cycles=12, ttl=10)
    # All entries born at cycle 0, so all die together at cycle 10.
    assert [r.deaths for r in result.records][:11] == [0] * 10 + [3]
    assert len(store) == 0


def test_recency_keeps_used_and_evicts_idle():
    store = make_store(2)
    used, idle = store.alive()

    class TouchingEnv(NullEnv):
        def tasks(self, cycle):
            used.last_used_cycle = cycle  # simulate constant consultation
            return []

    run_recency(store, TouchingEnv(), cycles=12, window=10)
    alive_ids = {e.id for e in store.alive()}
    assert used.id in alive_ids
    assert idle.id not in alive_ids


def test_evict_on_negative_buries_exactly_the_blamed():
    from darwin_memo import MemoryEntry, Outcome, Task

    store = MemoryStore()
    bad = store.add(
        MemoryEntry(
            question="What about the flaky widget files?",
            answer="Flaky widget files are redundant and safe to remove.",
        )
    )
    good = store.add(
        MemoryEntry(
            question="What about ledger files?",
            answer="Ledger files must be retained.",
        )
    )

    class BlameEnv(NullEnv):
        def tasks(self, cycle):
            return [
                Task(prompt="Is it safe to remove the flaky widget files?", context={})
            ]

        def verify(self, task, answer_text):
            return Outcome(delta=-5.0, detail="that broke something")

    from bench.policies import run_evict_on_negative

    result = run_evict_on_negative(store, BlameEnv(), cycles=1)
    assert result.records[0].deaths == 1
    assert store.get(bad.id) is None, "the blamed decider is evicted"
    assert store.get(good.id) is not None


def test_random_matched_buries_scheduled_counts():
    store = make_store(6)
    schedule = [0, 2, 0, 1]
    result = run_random_matched(
        store, NullEnv(), cycles=4, seed=0, death_schedule=schedule
    )
    assert [r.deaths for r in result.records] == schedule
    assert len(store) == 3


def test_headline_store_has_poison():
    store = build_headline_store()
    assert poison_ids(store)
    assert active_poison_alive(store)


def test_run_one_schema_and_check():
    run = run_one(arm="survival", seed=0, cycles=6, files_per_cycle=6, suite="smoke")
    assert check([run]) == []
    assert run["metrics"]["wall_time_s"] > 0
    assert isinstance(run["metrics"]["poison_killed"], bool)


def test_run_one_is_deterministic_apart_from_wall_time():
    a = run_one(arm="survival", seed=3, cycles=6, files_per_cycle=6)
    b = run_one(arm="survival", seed=3, cycles=6, files_per_cycle=6)
    a["metrics"].pop("wall_time_s")
    b["metrics"].pop("wall_time_s")
    assert a["metrics"] == b["metrics"]
    assert a["per_cycle"] == b["per_cycle"]


def test_aggregate_groups_and_formats():
    runs = [
        run_one(arm="keep_everything", seed=s, cycles=4, files_per_cycle=4)
        for s in (0, 1)
    ]
    rows = aggregate(runs)
    assert len(rows) == 1
    assert rows[0]["arm"] == "keep_everything"
    assert rows[0]["seeds"] == "2"


def test_storage_env_resource_scale_override():
    env = StorageEnv(root=Path(tempfile.mkdtemp()), files_per_cycle=4, seed=0)
    env.resource_scale = 25_000.0
    assert env.resource_scale == 25_000.0
    env.cleanup()


# ---------------------------------------------------------------------------
# Noisy-measurement harness (FlakyStorageEnv and the noisy suite)
# ---------------------------------------------------------------------------

from bench.noise import FlakyStorageEnv  # noqa: E402
from bench.policies import (  # noqa: E402
    run_evict_consecutive,
    run_evict_on_negative,
    run_quarantine,
)
from darwin_memo import Outcome, Task  # noqa: E402


def _flaky(tmp_path, name, **kwargs):
    return FlakyStorageEnv(root=tmp_path / name, files_per_cycle=8, seed=3, **kwargs)


def test_flake_marks_are_a_world_property(tmp_path):
    """Same (seed, rate): identical marks regardless of answer history."""
    a = _flaky(tmp_path, "a", flake_rate=0.3)
    b = _flaky(tmp_path, "b", flake_rate=0.3)
    # Drive cycle 0 with opposite behaviors before comparing cycle 1.
    for task in a.tasks(0):
        a.verify(task, "Yes, it is safe to delete, the file is disposable.")
    for task in b.tasks(0):
        b.verify(task, "")
    marks_a = [t.context["flaky"] for t in a.tasks(1)]
    marks_b = [t.context["flaky"] for t in b.tasks(1)]
    assert marks_a == marks_b
    assert any(marks_a), "rate 0.3 over 8 tasks should mark at least one"


def test_flake_marks_nest_across_rates(tmp_path):
    """Monotone coupling: every mark at a low rate is marked at a high one."""
    lo = _flaky(tmp_path, "lo", flake_rate=0.1)
    hi = _flaky(tmp_path, "hi", flake_rate=0.4)
    for cycle in range(4):
        lo_marks = [t.context["flaky"] for t in lo.tasks(cycle)]
        hi_marks = [t.context["flaky"] for t in hi.tasks(cycle)]
        assert all(h or not lo_m for lo_m, h in zip(lo_marks, hi_marks, strict=True))


def test_flip_lies_exactly_on_marked_acted_tasks(tmp_path):
    env = _flaky(tmp_path, "flip", flake_rate=1.0, noise_model="flip")
    tasks = env.tasks(0)
    disposable = next(t for t in tasks if t.context["safe"])
    protected = next(t for t in tasks if not t.context["safe"])

    freed = env.verify(disposable, "Yes, safe to delete, it is disposable.")
    assert freed.delta == -disposable.context["size"], "good outcome reported bad"
    destroyed = env.verify(protected, "Yes, safe to delete, it is disposable.")
    assert destroyed.delta == 3 * protected.context["size"], "disaster reported good"
    kept = env.verify(tasks[-1], "")
    assert kept.delta == 0, "no measurement, nothing to lie about"

    assert env.flakes_fired == 2
    assert env.fired_false_bad == 1 and env.fired_false_good == 1
    assert env.true_deltas[0] == (
        disposable.context["size"] - 3 * protected.context["size"]
    )


def test_false_bad_never_flips_negatives(tmp_path):
    env = _flaky(tmp_path, "fb", flake_rate=1.0, noise_model="false_bad")
    tasks = env.tasks(0)
    protected = next(t for t in tasks if not t.context["safe"])
    outcome = env.verify(protected, "Yes, safe to delete, it is disposable.")
    assert outcome.delta == -3 * protected.context["size"], "negatives stay truthful"
    assert env.fired_false_good == 0


def test_magnitude_keeps_sign_and_lies_about_size(tmp_path):
    env = _flaky(tmp_path, "mag", flake_rate=1.0, noise_model="magnitude")
    tasks = env.tasks(0)
    disposable = next(t for t in tasks if t.context["safe"])
    outcome = env.verify(disposable, "Yes, safe to delete, it is disposable.")
    size = disposable.context["size"]
    factor = outcome.delta / size
    assert outcome.delta > 0, "sign preserved"
    assert 0.25 <= factor <= 4.0 and factor != 1.0


def test_flaky_rate_zero_is_passthrough():
    noisy = run_one(
        arm="survival",
        seed=3,
        cycles=6,
        files_per_cycle=6,
        overrides={"flake_rate": 0.0, "noise_model": "flip"},
    )
    plain = run_one(arm="survival", seed=3, cycles=6, files_per_cycle=6)
    for run in (noisy, plain):
        run["metrics"].pop("wall_time_s")
    assert noisy["metrics"] == plain["metrics"]
    assert noisy["per_cycle"] == plain["per_cycle"]


def test_noisy_run_is_deterministic_apart_from_wall_time():
    overrides = {"flake_rate": 0.2, "noise_model": "flip"}
    a = run_one(
        arm="survival", seed=3, cycles=6, files_per_cycle=6, overrides=overrides
    )
    b = run_one(
        arm="survival", seed=3, cycles=6, files_per_cycle=6, overrides=overrides
    )
    a["metrics"].pop("wall_time_s")
    b["metrics"].pop("wall_time_s")
    assert a["metrics"] == b["metrics"]
    assert a["per_cycle_true_delta"] == b["per_cycle_true_delta"]


def test_noisy_metrics_score_true_deltas():
    run = run_one(
        arm="survival",
        seed=0,
        cycles=6,
        files_per_cycle=6,
        overrides={"flake_rate": 0.5, "noise_model": "flip"},
    )
    assert sum(run["per_cycle_true_delta"]) == run["metrics"]["cum_delta"]
    reported = sum(c["resource_delta"] for c in run["per_cycle"])
    assert reported == run["metrics"]["reported_cum_delta"]
    assert run["metrics"]["flakes_fired"] >= 1, "rate 0.5 must fire on acted tasks"
    assert run["metrics"]["reported_cum_delta"] != run["metrics"]["cum_delta"]


def test_keep_everything_true_deltas_are_noise_invariant():
    """The canary: an outcome-blind arm's TRUE movement never varies."""
    cums = set()
    for overrides in (
        {},
        {"flake_rate": 0.2, "noise_model": "flip"},
        {"flake_rate": 0.2, "noise_model": "false_bad"},
        {"flake_rate": 0.2, "noise_model": "magnitude"},
    ):
        run = run_one(
            arm="keep_everything",
            seed=1,
            cycles=6,
            files_per_cycle=6,
            overrides=overrides,
        )
        cums.add(run["metrics"]["cum_delta"])
    assert len(cums) == 1, f"canary drift: {sorted(cums)}"


def test_noise_refuses_undefined_arms():
    import pytest

    for arm in ("random_matched", "survival_writes"):
        with pytest.raises(ValueError, match="not defined under measurement noise"):
            run_one(
                arm=arm,
                seed=0,
                cycles=2,
                files_per_cycle=4,
                overrides={"flake_rate": 0.1},
            )


def test_check_exempts_noisy_runs_from_the_kill_gate():
    run = run_one(
        arm="survival",
        seed=0,
        cycles=6,
        files_per_cycle=6,
        overrides={"flake_rate": 0.2, "noise_model": "flip"},
    )
    run["metrics"]["poison_killed"] = False
    run["metrics"]["poison_kill_cycle"] = None
    assert check([run]) == [], "an honest noisy non-kill must pass CI"

    clean = run_one(arm="survival", seed=0, cycles=6, files_per_cycle=6)
    clean["metrics"]["poison_killed"] = False
    assert check([clean]), "a noise-free non-kill still fails the gate"


class _AlternatingEnv:
    """Praises the decider on even cycles, blames it on odd ones."""

    resource_scale = 1.0

    def __init__(self):
        self.cycle = 0

    def tasks(self, cycle):
        self.cycle = cycle
        return [Task(prompt="Is it safe to remove the flaky widget files?", context={})]

    def verify(self, task, answer_text):
        if self.cycle % 2 == 0:
            return Outcome(delta=5.0, detail="worked")
        return Outcome(delta=-5.0, detail="broke")


def _widget_store():
    store = MemoryStore()
    decider = store.add(
        MemoryEntry(
            question="What about the flaky widget files?",
            answer="Flaky widget files are redundant and safe to remove.",
        )
    )
    return store, decider


def test_evict_on_negative_lifetime_strikes():
    store, decider = _widget_store()
    result = run_evict_on_negative(store, _AlternatingEnv(), cycles=4, strikes=2)
    # Blamed on cycles 1 and 3; second lifetime strike evicts at cycle 3.
    assert [r.deaths for r in result.records] == [0, 0, 0, 1]
    assert store.get(decider.id) is None


def test_evict_consecutive_forgives_on_success():
    store, decider = _widget_store()
    run_evict_consecutive(store, _AlternatingEnv(), cycles=6, strikes=2)
    # Every even cycle's praise resets the count: never reaches 2.
    assert store.get(decider.id) is not None


class _AlwaysBlameEnv:
    resource_scale = 1.0

    def tasks(self, cycle):
        return [Task(prompt="Is it safe to remove the flaky widget files?", context={})]

    def verify(self, task, answer_text):
        if "safe to remove" in answer_text:
            return Outcome(delta=-5.0, detail="broke")
        return Outcome(delta=0.0, detail="kept")


def test_quarantine_buries_then_revives_fresh():
    store, decider = _widget_store()
    result = run_quarantine(store, _AlwaysBlameEnv(), cycles=4, suspend=3)
    # Buried at cycle 0, absent for 1-2, revived fresh at 3 and blamed again.
    assert [r.deaths for r in result.records] == [1, 0, 0, 1]
    assert store.get(decider.id) is None, "the original stays buried"
    revived = [e for e in store.graveyard() if e.id != decider.id]
    assert len(revived) == 1 and revived[0].question == decider.question
    assert revived[0].born_cycle == 3


def test_paired_raises_on_ambiguous_variant_prefix():
    import pytest

    from bench.report import paired

    def fake(arm, label, seed, cum):
        return {
            "arm": arm,
            "label": label,
            "seed": seed,
            "metrics": {"cum_delta": cum},
        }

    runs = [
        fake("survival", "model=flip,rate=0.10", 0, 5.0),
        fake("evict_on_negative", "model=flip,rate=0.10,k=1", 0, 1.0),
        fake("evict_on_negative", "model=flip,rate=0.10,k=2", 0, 2.0),
    ]
    with pytest.raises(ValueError, match="ambiguous"):
        paired(runs, "survival", "evict_on_negative")
    # Variant-qualified names disambiguate; the diff is against k=2 only.
    rows = paired(runs, "survival", "evict_on_negative:k=2")
    assert rows[0]["median diff"] == "3"


def test_budget_relevance_holds_the_budget_and_never_regenerates_the_world():
    """The EMBER-style arm caps the store and leaves the environment alone.

    Two mutations this catches. First, dropping the population cap (or
    comparing against the wrong side of it) makes the arm a no-op and it
    silently becomes keep_everything at a different name. Second --- and
    this is the one that would corrupt every number the arm produces ---
    reading `env.tasks(cycle)` inside the victim selector to get the
    cycle's prompts: StorageEnv.tasks deletes its sandbox and regenerates
    the cycle's files on every call, so a second call after the task loop
    destroys the state the cycle was just measured on. The arm reads
    relevance off the protocol instead, and this test fails if it ever
    stops doing so.
    """
    from bench.policies import run_budget_relevance

    calls = []

    class CountingEnv:
        def __init__(self, inner):
            self.inner = inner
            self.resource_scale = inner.resource_scale

        def tasks(self, cycle):
            calls.append(cycle)
            return self.inner.tasks(cycle)

        def verify(self, task, answer_text):
            return self.inner.verify(task, answer_text)

    with tempfile.TemporaryDirectory() as tmp:
        env = CountingEnv(StorageEnv(root=Path(tmp), seed=0, files_per_cycle=3))
        store = build_headline_store()
        before = len(store)
        result = run_budget_relevance(store, env, cycles=5, budget=2)

    assert before > 2, "fixture must start over budget or the cap is untested"
    assert len(store) == 2, f"budget not held: {len(store)} entries alive"
    assert calls == [0, 1, 2, 3, 4], f"env.tasks called {len(calls)} times: {calls}"
    assert len(result.records) == 5


def test_query_only_attacker_makes_potentiated_poison_outlive_the_store():
    """The security half of Phase 4, and the number docs/threat-model.md carries.

    Three mutations this catches. First, charging flat upkeep in the
    attacked condition (dropping the ``scale=`` argument) collapses the
    margin to zero, because flat upkeep is exactly what the shipped loop
    does and it is the control this whole measurement is read against.
    Second, letting the attacker's recalls reach the CREDIT component ---
    crediting energy on recall rather than only on a settled outcome ---
    pushes the ceiling past 2/3 and the store never releases the poison at
    all. Third, dropping the peak-normalisation in EarnedImportance.scores
    makes importance absolute rather than a standing within the
    population, and the attack stops working entirely: the margin exists
    because inflating your own recall count DEFLATES everyone else's
    normalised score, which is what turns a shared horizon into an
    attacker-owned one.
    """
    from bench.potentiation import ConditionResult, run_condition

    flat = run_condition("flat", "inert", cycles=400, upkeep=0.05, attacker_queries=3)
    honest = run_condition(
        "honest", "inert", cycles=400, upkeep=0.05, attacker_queries=3
    )
    attacked = run_condition(
        "attacked", "inert", cycles=400, upkeep=0.05, attacker_queries=3
    )

    def margin(row: ConditionResult) -> int:
        """The margin, or fail loudly. A None means something never starved
        inside the horizon, which would make the comparisons below vacuous
        rather than false."""
        value = row.poison_outlives_benign
        assert value is not None, f"{row.condition} did not starve in 400 cycles"
        return value

    margins = {r.condition: margin(r) for r in (flat, honest, attacked)}
    assert flat.poison_starve_cycle, "the fixture must starve, or nothing is measured"
    assert margins["flat"] == 0, (
        "flat upkeep must give the poison no edge; it is the control"
    )
    assert margins["honest"] <= 1, (
        "potentiation alone must not favour the poison, or the attack is not "
        f"what is being measured (margin {margins['honest']})"
    )
    assert margins["attacked"] >= 3, (
        "query-only recalls must buy the poison a margin over benign entries "
        f"(margin {margins['attacked']})"
    )
    # Credit is the one component a query-only adversary cannot reach, so the
    # reachable ceiling is exactly the other two thirds -- and the relief that
    # follows from it is MAX_RELIEF x 2/3.
    assert attacked.peak_poison_importance == pytest.approx(2 / 3, abs=0.01)
    assert attacked.min_poison_upkeep_scale == pytest.approx(2 / 3, abs=0.01)


def test_potentiation_measurement_is_reproducible_across_processes():
    """Mutation: any tie broken on ``entry.id`` (uuid4, random per process)
    makes the margin flip run to run, and a security number that moves is not
    a number. Two runs in ONE process would not catch it -- the ids are drawn
    once per store -- so this builds two stores and requires the same answer
    from both."""
    from bench.potentiation import run_condition

    first = run_condition(
        "attacked", "inert", cycles=400, upkeep=0.05, attacker_queries=3
    )
    second = run_condition(
        "attacked", "inert", cycles=400, upkeep=0.05, attacker_queries=3
    )
    assert first == second, f"not reproducible:\n{first}\n{second}"


def test_peak_normalisation_is_what_carries_the_attacker_margin():
    """The counterfactual behind the causal claim in docs/threat-model.md.

    Without this the claim "the mechanism is peak-normalisation" is an
    inference from the arithmetic, not a measurement, and two other
    explanations survive: that any usage signal hands the attacker a margin,
    or that centrality alone does. Swapping ONLY the recall term's
    denominator — population peak for a fixed cap, nothing else, centrality
    left attacker-drivable on purpose — collapses the margin to zero while
    potentiation still works. So it is the coupling between entries that is
    exploitable, not usage as such.

    Mutation: make `SaturatingImportance.scores` divide by the population
    peak after all and the margin returns to 4, proving nothing.
    """
    from bench.potentiation import run_condition

    attacked_peak = run_condition(
        "attacked", "inert", cycles=400, upkeep=0.05, attacker_queries=3
    )
    attacked_flat_norm = run_condition(
        "attacked",
        "inert",
        cycles=400,
        upkeep=0.05,
        attacker_queries=3,
        recall_norm="saturating",
    )

    peak_margin = attacked_peak.poison_outlives_benign
    saturating_margin = attacked_flat_norm.poison_outlives_benign
    saturating_starve = attacked_flat_norm.poison_starve_cycle
    assert peak_margin is not None and saturating_margin is not None
    assert saturating_starve is not None, "nothing starved; the run is vacuous"

    assert peak_margin >= 3, "the attack must work first"
    assert saturating_margin == 0, (
        "removing the peak coupling must remove the margin, or the mechanism "
        f"is something else (margin {saturating_margin})"
    )
    # And it is a counterfactual, not a disabling: potentiation still buys the
    # population a longer horizon, which is the thing the operator opted in for.
    assert saturating_starve > 20, (
        "saturating normalisation must not switch potentiation off"
    )


def test_potentiation_sweep_holds_across_corpora_and_upkeeps():
    """The n=1 caveat, discharged. Four claims, each of which the single-store
    run could not make and one of which it got wrong.

    1. Flat upkeep never favours the poison, in any cell. That is the shipped
       default and the whole safety claim.
    2. The attacker gains in EVERY peak-normalised cell — the lever is a
       property of the mechanism, not of one fixture at one tuning.
    3. The margin is a roughly constant FRACTION of the starvation horizon,
       not a fixed cycle count. Absolute cycles are upkeep artefacts.
    4. Under saturating normalisation the margin never exceeds one cycle,
       which is the measurement floor. The single-store run reported "removes
       the margin entirely"; that was true of its cell and too strong in
       general.

    Mutation: report absolute margins instead of fractions and (2) looks like a
    scale-dependent effect that fades at high upkeep, when it is the horizon
    fading and not the attack.
    """
    from bench.potentiation import sweep

    report = sweep(
        cycles=200, attacker_queries=3, upkeeps=[0.05, 0.2], attacks=["inert"]
    )
    cells = report["cells"]
    assert len(cells) == 8, f"grid shape changed: {len(cells)} cells"
    assert {c["family"] for c in cells} == {"memsec", "testsuite"}

    assert report["flat_cells_gained"] == 0, (
        "flat upkeep favoured the poison somewhere; the shipped default is "
        "the control this whole measurement is read against"
    )
    assert report["peak_cells_attacker_gained"] == report["peak_cells"], (
        "the attack must work in every peak cell, or it is a fixture artefact"
    )
    peak_fractions = [
        c["attacked_margin_fraction"] for c in cells if c["recall_norm"] == "peak"
    ]
    assert all(0.05 <= f <= 0.30 for f in peak_fractions), (
        f"margin fraction left its measured band: {peak_fractions}"
    )
    saturating_margins = [
        c["attacked_margin"] for c in cells if c["recall_norm"] == "saturating"
    ]
    assert all(m <= 1 for m in saturating_margins), (
        "saturating normalisation must hold the margin at or below the "
        f"one-cycle measurement floor: {saturating_margins}"
    )


def test_persist_objective_spends_only_on_the_guilty():
    """The persistence adversary's whole economy is that it never wastes a lie.

    Two mutations this catches. First, gating on ``true.delta != 0`` instead of
    ``< 0`` turns it back into the destruction adversary it is meant to be
    contrasted against; every number in the persistence table would then
    duplicate the adversary table and the comparison would silently say
    nothing. Second, at budget 0 both objectives must add exactly zero
    behaviour — without that canary there is nothing separating "the attack
    moved the numbers" from "the harness did".
    """
    from bench.adversary import AdversarialEnv

    def spend(objective: str, budget: int) -> tuple[int, int]:
        """Fire one benign win then one poison disaster; report where lies went."""
        env = AdversarialEnv(lie_budget=budget, objective=objective, seed=1)
        env.tasks(0)
        deltas = iter([+100.0, -100.0])

        def stub_verify(task, answer_text):
            return Outcome(delta=next(deltas), detail="stub")

        env.base.verify = stub_verify  # type: ignore[method-assign]
        for _ in range(2):
            env.verify(Task(prompt="p", context={}), "a")
        return env.fired_false_bad, env.fired_false_good

    assert spend("persist", 4) == (0, 1), (
        "persist must pay the guilty poison once and never blame a benign "
        "entry; blaming benign entries is what destruction does"
    )
    assert spend("destroy", 4) == (1, 1), "destroy must spend in both directions"
    for objective in ("destroy", "persist"):
        assert spend(objective, 0) == (0, 0), (
            f"{objective} fired a lie at budget 0; the canary is broken"
        )


def test_withhold_objective_reports_silence_and_still_balances():
    """Withholding writes zero, it does not invert.

    The accounting identity ``reported == true + distortion`` is what the
    runner checks every run against, and a suppressed measurement has to
    satisfy it exactly like an inverted one or every number in the suite
    is garbage.

    Mutations this catches: reporting ``-true`` (that is the destruction
    adversary, and the withholding table would silently duplicate the
    adversary table); dropping the distortion bookkeeping for the
    withhold branch (the runner's identity check then fails, but only on
    a full run -- this catches it in a millisecond); and firing at
    budget 0.
    """
    from bench.adversary import AdversarialEnv

    def run(budget: int) -> tuple[list[float], float, int]:
        env = AdversarialEnv(lie_budget=budget, objective="withhold", seed=1)
        env.tasks(0)
        # Asymmetric on purpose: equal-and-opposite deltas would make the
        # accounting identity hold by cancellation whatever the branch did.
        deltas = iter([+100.0, -40.0])

        def stub_verify(task, answer_text):
            return Outcome(delta=next(deltas), detail="stub")

        env.base.verify = stub_verify  # type: ignore[method-assign]
        reported = [
            env.verify(Task(prompt="p", context={}), "a").delta for _ in range(2)
        ]
        return reported, env.distortion, env.flakes_fired

    true_total = 100.0 - 40.0
    reported, distortion, fired = run(4)
    assert reported == [0.0, 0.0], "a withheld measurement is silence, not a lie"
    assert fired == 2, "both measurable outcomes were suppressed"
    assert sum(reported) == pytest.approx(true_total + distortion), (
        "reported == true + distortion, the identity the runner checks"
    )
    assert distortion == pytest.approx(-true_total), "the whole outcome was erased"

    reported, distortion, fired = run(0)
    assert reported == [100.0, -40.0], "budget 0 must add exactly zero behaviour"
    assert (distortion, fired) == (0.0, 0)


def test_a_price_blind_withholder_spends_where_the_price_exempts(tmp_path):
    """The confound the tier grid was published with, and its removal.

    ``withhold`` computes ``worth_lying`` from the delta the environment
    returns, and under the ``aligned`` tier a declined protected file
    returns exactly 0.0 -- so the tier does not merely make that hold
    free, it makes it invisible to the attacker. Shape and attack
    surface move together and the grid cannot attribute either.

    This is that fact in eleven lines: same world, same seed, same
    declines, one objective spends nothing and the other spends its whole
    budget. It also pins the accounting, which is the part that is easy
    to get quietly wrong -- a spend on a zero truth distorts nothing, so
    it must NOT be counted as a false good, and the wasted budget stays
    readable as ``fired - (false_bad + false_good)``.

    Mutations this catches: computing ``worth_lying`` from the base
    delta instead of ignoring it (blind stops firing on exempt holds and
    the confound is back); counting a zero-truth spend in
    ``fired_false_good`` (the wasted budget reads as lies that were told,
    and every blind row's distortion no longer reconciles with its
    counters); and giving ``withhold_blind`` the inverting payload.
    """
    from bench.adversary import AdversarialEnv
    from darwin_memo import RentedStorageEnv

    def run(objective: str) -> tuple[int, int, int, float, list[float], int]:
        base = RentedStorageEnv(
            root=tmp_path / objective,
            files_per_cycle=8,
            seed=5,
            hold_cost=0.75,
            rent_tier="aligned",
        )
        env = AdversarialEnv(base=base, lie_budget=8, objective=objective, seed=5)
        tasks = env.tasks(0)
        # `aligned` bills the disposable categories and exempts the
        # protected ones, so a protected decline is the exempt case.
        exempt = sum(1 for t in tasks if not t.context["safe"])
        assert exempt, "seed drew no protected file; the exempt branch never ran"
        # Decline everything: under `aligned` the protected declines are
        # exempt and score 0.0, the disposable ones are billed.
        reported = [env.verify(t, "leave it alone").delta for t in tasks]
        env.cleanup()
        return (
            env.flakes_fired,
            env.fired_false_bad,
            env.fired_false_good,
            env.distortion,
            reported,
            exempt,
        )

    greedy = run("withhold")
    blind = run("withhold_blind")

    n_exempt = greedy[5]
    assert greedy[0] == len(greedy[4]) - n_exempt, (
        "the greedy withholder should skip exactly the exempt holds"
    )
    assert blind[0] == len(blind[4]), "the blind withholder spends on every task"
    assert blind[0] > greedy[0], "the two objectives must differ on this world"

    # Silence, not inversion: every reported delta is zero for both.
    assert set(blind[4]) == {0.0}
    # A spend on a zero truth distorts nothing and is not counted as a lie.
    assert blind[2] == greedy[2] and blind[1] == greedy[1] == 0
    assert blind[0] - (blind[1] + blind[2]) == n_exempt, (
        "wasted budget must stay readable as fired - (false_bad + false_good)"
    )
    assert blind[3] == greedy[3], "erasing a zero erases nothing"


def test_a_saturating_budget_makes_the_targeting_rule_moot(tmp_path):
    """Why the published tier grid is not confounded after all.

    The caveat in ``limitations.tex`` is about a scarce budget: a greedy
    withholder concentrates its spend on the outcomes a tier still
    prices, and a tier that exempts a category is therefore attacked on a
    smaller surface. But the tier grid ran budget 12 against
    ``files_per_cycle`` 12. A saturating budget has nothing to
    concentrate -- every measurable outcome is suppressed under either
    rule, and the blind attacker's extra spends land on outcomes already
    equal to zero, where withholding writes zero over zero.

    So at saturation the two objectives are not close, they are the same
    run, and that is what ``rent_tiers_saturated`` asserts cell by cell.
    At an interior budget they must genuinely diverge, or
    ``rent_tiers_blind`` is 9,000 runs of nothing.

    Mutations this catches: making a blind spend write something other
    than silence (saturation stops being an identity); and any change
    that lets the greedy rule reach an exempt hold, which would collapse
    the interior divergence this grid exists to measure.
    """
    from bench.adversary import AdversarialEnv
    from darwin_memo import RentedStorageEnv

    def run(objective: str, budget: int) -> tuple[list[float], int]:
        base = RentedStorageEnv(
            root=tmp_path / f"{objective}{budget}",
            files_per_cycle=8,
            seed=7,
            hold_cost=0.75,
            rent_tier="aligned",
        )
        env = AdversarialEnv(base=base, lie_budget=budget, objective=objective, seed=7)
        tasks = env.tasks(0)
        # Seed 7 opens with three protected files, which `aligned`
        # exempts: declining them scores exactly 0.0. That is the whole
        # divergence -- the blind rule spends there and the greedy rule
        # walks past to the first hold the tier still prices.
        assert not any(t.context["safe"] for t in tasks[:2]), "seed 7 reordered"
        reported = [env.verify(t, "leave it alone").delta for t in tasks]
        env.cleanup()
        return reported, env.flakes_fired

    saturating = len(
        RentedStorageEnv(root=tmp_path / "n", files_per_cycle=8, seed=7).tasks(0)
    )
    assert run("withhold_blind", saturating)[0] == run("withhold", saturating)[0], (
        "at a saturating budget the targeting rule cannot change any outcome"
    )
    scarce_blind, scarce_greedy = run("withhold_blind", 2), run("withhold", 2)
    assert scarce_blind[0] != scarce_greedy[0], (
        "at a scarce budget the two rules must diverge, or the grid measures nothing"
    )
    assert scarce_blind[1] == scarce_greedy[1] == 2, "both spent the whole budget"


def test_blind_matches_greedy_at_zero_budget(tmp_path):
    """The canary ``rent_tiers_blind`` omits 4,500 runs rather than commit.

    Budget 0 spends nothing whatever the targeting rule is, so those
    cells would be a byte-for-byte copy of ``rent_tiers.json``. That is
    only true while ``worth_lying`` is gated behind the budget check
    rather than beside it, which is a one-line mutation away, so the
    equivalence is asserted here instead of bought at grid scale.
    """
    from bench.adversary import AdversarialEnv
    from darwin_memo import RentedStorageEnv

    out = {}
    for objective in ("withhold", "withhold_blind"):
        base = RentedStorageEnv(
            root=tmp_path / objective,
            files_per_cycle=8,
            seed=3,
            hold_cost=1.0,
            rent_tier="aligned",
        )
        env = AdversarialEnv(base=base, lie_budget=0, objective=objective, seed=3)
        tasks = env.tasks(0)
        out[objective] = (
            [env.verify(t, "leave it alone").delta for t in tasks],
            env.flakes_fired,
            env.distortion,
        )
        env.cleanup()
    assert out["withhold_blind"] == out["withhold"]
    assert out["withhold"][1:] == (0, 0.0), "budget 0 must add exactly zero behaviour"


def test_withholding_suite_leaves_the_published_arm_lists_alone():
    """Adding an arm to ARMS or ADVERSARY_VARIANTS rewrites committed evidence.

    ``headline_suite`` iterates ``ARMS`` and ``adversary_suite`` iterates
    ``ADVERSARY_VARIANTS``, both of which back paper tables that
    ``bench.report --check --require-manifest`` validates. A new arm
    belongs in its own tuple and its own results file, which is why
    SALIENCE_ARMS and NEIGHBOUR_ARMS exist.

    Mutation this catches: appending ``survival_paced`` to ARMS or to
    ADVERSARY_VARIANTS for convenience.
    """
    from bench.policies import ARMS
    from bench.suites import ADVERSARY_VARIANTS, WITHHOLD_ARMS

    assert "survival_paced" not in ARMS
    assert "survival_paced" not in [arm for arm, _extra, _suffix in ADVERSARY_VARIANTS]
    assert "survival_paced" in [arm for arm, _extra, _suffix in WITHHOLD_ARMS]


def test_withholding_doc_table_matches_the_committed_evidence():
    """docs/benchmarks.md's withholding table, checked against its own data.

    This repo has been bitten by documents that assert agreement with
    evidence and are never made to prove it -- a retired number survived
    in a fourth file for four days because the sweep that retired it was
    written from memory. A table transcribed by hand is exactly that
    shape, so it gets a parser rather than a promise.

    Mutation that must fail this test: change any digit in the table, or
    regenerate withholding.json with a different grid.
    """
    import json
    import re
    import statistics as st
    from collections import defaultdict
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    runs = json.loads((root / "bench/results/withholding.json").read_text())["runs"]

    agg = defaultdict(list)
    for r in runs:
        budget = int(r["label"].split("budget=")[1].split(",")[0])
        cycles = int(r["label"].split("cycles=")[1].split(",")[0])
        suffix = (
            ""
            if not r["label"].endswith(("k=1", "m=3"))
            else " " + r["label"].rsplit(",", 1)[1]
        )
        agg[(budget, cycles, r["arm"] + suffix)].append(r["metrics"])

    def mean(budget, cycles, arm, key):
        cells = agg[(budget, cycles, arm)]
        assert cells, f"no runs for {(budget, cycles, arm)}"
        return st.mean(c[key] for c in cells)

    doc = (root / "docs/benchmarks.md").read_text()
    # Scoped to its own subsection, not to the whole chapter: a sibling
    # ### section with its own table lives under the same ## heading, and
    # a chapter-wide slice would silently swallow its rows.
    section = doc.split("### Results (mean over 30 seeds)")[1].split("\n### ")[0]
    rows = [
        line
        for line in section.splitlines()
        if line.startswith("| ")
        and not line.startswith("| budget")
        and "---" not in line
    ]
    assert len(rows) == 12, f"expected 12 data rows, parsed {len(rows)}"

    checked = 0
    for line in rows:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        budget = int(cells[0])
        arm = cells[1].replace("**", "")

        def num(text):
            return float(re.sub(r"[*M+]", "", text))

        for column, cycles, key, tol in (
            (2, 30, "probe_benign_correct_rate", 0.006),
            (3, 60, "probe_benign_correct_rate", 0.006),
            (4, 30, "poison_killed", 0.006),
            (7, 60, "final_population", 0.06),
        ):
            got = mean(budget, cycles, arm, key)
            assert abs(got - num(cells[column])) <= tol, (
                f"budget={budget} {arm} {key}@{cycles}c: doc says "
                f"{cells[column]}, data says {got}"
            )
            checked += 1
        for column, cycles in ((5, 30), (6, 60)):
            got = mean(budget, cycles, arm, "cum_delta") / 1e6
            assert abs(got - num(cells[column])) <= 0.006, (
                f"budget={budget} {arm} cum_delta@{cycles}c: doc says "
                f"{cells[column]}M, data says {got:.3f}M"
            )
            checked += 1
    assert checked == 72, f"expected 72 checked cells, did {checked}"


def test_selective_withholding_doc_table_matches_the_committed_evidence():
    """The selective table, checked against its own results file.

    Same reason as the sibling check above: a hand-transcribed table is
    an unenforced claim, and this repo has watched one rot.

    Mutation that must fail this test: change any digit in the table.
    """
    import json
    import re
    import statistics as st
    from collections import defaultdict
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    path = root / "bench/results/withholding_selective.json"
    runs = json.loads(path.read_text())["runs"]

    agg = defaultdict(list)
    for r in runs:
        budget = int(r["label"].split("budget=")[1].split(",")[0])
        cycles = int(r["label"].split("cycles=")[1].split(",")[0])
        suffix = (
            ""
            if not r["label"].endswith(("k=1", "m=3"))
            else " " + r["label"].rsplit(",", 1)[1]
        )
        agg[(budget, cycles, r["arm"] + suffix)].append(r["metrics"])

    def mean(budget, arm, key):
        cells = agg[(budget, 60, arm)]
        assert cells, f"no runs for budget={budget} {arm}"
        vals = [c[key] for c in cells if c[key] is not None]
        return st.mean(vals) if vals else None

    doc = (root / "docs/benchmarks.md").read_text()
    section = doc.split("### The withholder that reads the sign")[1].split("\n### ")[0]
    rows = [
        line
        for line in section.splitlines()
        if line.startswith("| ")
        and not line.startswith("| budget")
        and "---" not in line
    ]
    assert len(rows) == 13, f"expected 13 data rows, parsed {len(rows)}"

    checked = 0
    for line in rows:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        budget, arm = int(cells[0]), cells[1].replace("**", "")
        kill_doc = float(cells[2].replace("**", ""))
        assert abs(mean(budget, arm, "poison_killed") - kill_doc) <= 0.006, (
            f"budget={budget} {arm} kill: doc {kill_doc}"
        )
        cycle_doc = cells[3].replace("**", "")
        got_cycle = mean(budget, arm, "poison_kill_cycle")
        if cycle_doc == "never":
            assert got_cycle is None, f"budget={budget} {arm} kill cycle is not never"
        else:
            assert abs(got_cycle - float(cycle_doc)) <= 0.06, (
                f"budget={budget} {arm} kill cycle: doc {cycle_doc}, data {got_cycle}"
            )
        cum_doc = float(re.sub(r"[*M+]", "", cells[4]))
        assert abs(mean(budget, arm, "cum_delta") / 1e6 - cum_doc) <= 0.006, (
            f"budget={budget} {arm} cum delta: doc {cum_doc}M"
        )
        pop_doc = float(cells[5])
        assert abs(mean(budget, arm, "final_population") - pop_doc) <= 0.06
        checked += 4
    assert checked == 52, f"expected 52 checked cells, did {checked}"


def test_pacing_is_worthless_against_a_selective_withholder():
    """The claim the docs lead with, asserted against the data itself.

    Mutation that must fail this test: any change that makes
    survival_paced diverge from survival under this attack -- which is
    precisely the mitigation working, and would mean the paragraph
    saying it does not needs rewriting.
    """
    import json
    import statistics as st
    from collections import defaultdict
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    runs = json.loads((root / "bench/results/withholding_selective.json").read_text())[
        "runs"
    ]
    agg = defaultdict(list)
    for r in runs:
        budget = int(r["label"].split("budget=")[1].split(",")[0])
        cycles = int(r["label"].split("cycles=")[1].split(",")[0])
        agg[(budget, cycles, r["arm"])].append(r["metrics"])

    compared = 0
    for budget in (0, 1, 2, 4, 8, 12):
        for cycles in (30, 60):
            for key in (
                "probe_benign_correct_rate",
                "poison_killed",
                "cum_delta",
                "final_population",
            ):
                plain = st.mean(c[key] for c in agg[(budget, cycles, "survival")])
                paced = st.mean(c[key] for c in agg[(budget, cycles, "survival_paced")])
                assert plain == paced, (
                    f"budget={budget} cycles={cycles} {key}: pacing changed the "
                    f"result ({plain} vs {paced}) -- the docs claim it cannot"
                )
                compared += 1
    assert compared == 48


def test_curation_adversary_runs_on_the_testsuite_family():
    """The withholding attack reaches the second environment family.

    ``limitations.tex`` records that the withholding result is
    single-family because the wrapper was hardwired to StorageEnv, and
    that the test-suite environment is precisely where the result could
    differ: an emptied store is costless on the storage corpus, so the
    ledger's amnesia looks cheap there in a way it may not be elsewhere.

    Three mutations this catches. Restoring the runner's
    ``"lie_budget is a StorageEnv knob"`` raise puts the family back out
    of reach. Building a bare ``TestSuiteEnv`` in that branch and
    dropping ``lie_budget`` on the floor accepts the budget and runs no
    attack -- silently, which is exactly what the old raise existed to
    prevent, so ``flakes_fired`` is the assertion that matters. And
    dropping the mutual-exclusion check lets a run carry both threat
    models at once, attributing its result to neither.
    """
    from bench.runner import run_one

    overrides = {
        "env_family": "testsuite",
        "lie_budget": 2,
        "adversary_objective": "withhold",
    }
    result = run_one("survival", seed=1, cycles=4, overrides=overrides)
    metrics = result["metrics"]
    assert metrics["flakes_fired"] > 0, (
        "the budget was accepted but no measurement was suppressed; the "
        "run is a plain TestSuiteEnv wearing an adversarial config"
    )
    assert metrics["flakes_fired"] <= metrics["flakes_marked"], (
        "spent more capacity than was offered"
    )

    with pytest.raises(ValueError, match="two different threat models"):
        run_one(
            "survival",
            seed=1,
            cycles=2,
            overrides={**overrides, "flake_rate": 0.1},
        )


# ---------------------------------------------------------------------------
# RentedStorageEnv: the family where standing still is measured
# ---------------------------------------------------------------------------


def test_rented_env_at_zero_rent_is_identical_not_merely_equivalent(tmp_path):
    """The canary the whole rent sweep rests on.

    Every conclusion drawn from the sweep is a comparison against the
    zero-rent column, so that column has to BE the published storage
    family rather than resemble it. Identity is asserted on the outcome
    object, detail string included, because the transcripts carry the
    detail and ``-0.0 * size`` would pass a numeric-only check while
    writing ``kept, -0 bytes still occupied`` into every record.
    """
    from darwin_memo import RentedStorageEnv, StorageEnv

    plain = StorageEnv(root=tmp_path / "plain", files_per_cycle=6, seed=11)
    free = RentedStorageEnv(
        root=tmp_path / "free", files_per_cycle=6, seed=11, hold_cost=0.0
    )
    for answer in ("It must be retained.", "Safe to delete.", ""):
        for a, b in zip(plain.tasks(0), free.tasks(0), strict=True):
            assert a.prompt == b.prompt
            got, want = free.verify(b, answer), plain.verify(a, answer)
            assert got.delta == want.delta and got.detail == want.detail
    plain.cleanup()
    free.cleanup()


def test_rented_env_charges_exactly_the_occupancy_it_names(tmp_path):
    """Declining costs ``hold_cost * size``, and acting is untouched.

    The number is asserted against the task's own recorded size rather
    than against a constant, so a rent that silently used a fixed charge
    -- which would price every file the same and destroy the whole point
    of measuring bytes -- fails here.
    """
    from darwin_memo import RentedStorageEnv

    env = RentedStorageEnv(root=tmp_path, files_per_cycle=6, seed=11, hold_cost=0.25)
    for task in env.tasks(0):
        size = float(task.context["size"])
        assert env.verify(task, "It must be retained.").delta == -0.25 * size
        assert env.verify(task, "").delta == -0.25 * size, "silence is not free either"
    for task in env.tasks(1):
        acted = env.verify(task, "Safe to delete.").delta
        expected = float(task.context["size"])
        assert acted == (expected if task.context["safe"] else -3.0 * expected)
    env.cleanup()
    with pytest.raises(ValueError, match="hold_cost must be >= 0"):
        RentedStorageEnv(root=tmp_path, hold_cost=-0.1)


def test_rent_family_refuses_configs_that_would_not_record_what_they_ran():
    """Two ways this family could lie about itself in the manifest.

    A defaulted ``hold_cost`` would ride outside ``overrides`` and
    therefore outside the config hash, so two different rents would
    share a manifest entry. And ``FlakyStorageEnv`` builds its own
    unrented ``StorageEnv``, so accepting ``flake_rate`` here would run
    at zero rent under a config that claims otherwise -- the silent
    version of the failure the testsuite branch already refuses.
    """
    from bench.runner import run_one

    with pytest.raises(ValueError, match="storage_rent needs an explicit hold_cost"):
        run_one("survival", seed=0, cycles=2, overrides={"env_family": "storage_rent"})
    with pytest.raises(ValueError, match="no rented variant"):
        run_one(
            "survival",
            seed=0,
            cycles=2,
            overrides={
                "env_family": "storage_rent",
                "hold_cost": 1.0,
                "flake_rate": 0.1,
            },
        )


def test_pricing_inaction_removes_the_withholder_s_harbor():
    """The mechanism claim, isolated: silence stops being unattackable.

    ``limitations.tex`` records that under StorageEnv the withholding
    budget is not spent equally across arms, because a shrinking store
    produces fewer measured outcomes and the attack is self-limiting
    exactly when it is winning. That is a property of an environment
    where declining returns delta 0 and therefore cannot be suppressed.
    Price inaction and every task becomes a target, so the attacker
    spends its full capacity.

    Asserted as full saturation against a strict shortfall at the same
    seed, budget and horizon, which is the counterfactual that isolates
    the pricing: nothing else differs between the two runs.
    """
    from bench.runner import run_one

    base = {
        "env_family": "storage_rent",
        "lie_budget": 12,
        "adversary_objective": "withhold",
    }
    free = run_one("survival", seed=1, cycles=30, overrides={**base, "hold_cost": 0.0})
    rent = run_one("survival", seed=1, cycles=30, overrides={**base, "hold_cost": 1.0})
    assert free["metrics"]["flakes_fired"] < free["metrics"]["flakes_marked"], (
        "the zero-rent run saturated its budget, so this seed cannot show "
        "the harbor at all and the comparison below proves nothing"
    )
    assert rent["metrics"]["flakes_fired"] == rent["metrics"]["flakes_marked"]


def test_the_rent_an_arm_pays_is_its_decline_count():
    """The mechanism behind both rent sweeps, isolated.

    The paper's account of why pricing inaction reverses one grid and
    widens the ledger's lead on the other is a single claim: rent bills
    not having an answer, so the rent an arm pays is its decline count
    and nothing else. That is checkable directly rather than inferred
    from cum-delta slopes.

    Two assertions. The identity -- every charged byte comes from a
    declined task, at exactly ``hold_cost`` times that task's own size --
    fails if rent ever leaks into an acting outcome. And the ordering:
    ``keep_everything`` hoards, so it always has something to say and
    declines least; ``evict_on_negative`` under a liar is left with a
    store that is smaller *and* useless, so it declines most; the ledger
    sits between them, small but right about what it kept. That ordering
    is the whole explanation, and it is what a reader would have to
    disbelieve to disbelieve the sections.
    """
    from bench.runner import run_one
    from darwin_memo import RentedStorageEnv

    seen: dict[str, dict[str, float]] = {}
    current = ""
    original = RentedStorageEnv.verify

    def counting(self, task, answer_text):
        out = original(self, task, answer_text)
        row = seen.setdefault(current, {"declined": 0.0, "charged": 0.0})
        if out.delta < 0 and out.detail.startswith("kept"):
            row["declined"] += 1
            row["charged"] += -out.delta
            assert -out.delta == self.hold_cost * float(task.context["size"])
        return out

    try:
        RentedStorageEnv.verify = counting  # type: ignore[method-assign]
        for arm, extra in (
            ("keep_everything", {}),
            ("survival", {}),
            ("evict_on_negative", {"strikes": 1}),
        ):
            current = arm
            run_one(
                arm,
                seed=0,
                cycles=20,
                overrides={
                    "env_family": "storage_rent",
                    "hold_cost": 1.0,
                    "lie_budget": 2,
                    "adversary_objective": "destroy",
                    **extra,
                },
            )
    finally:
        RentedStorageEnv.verify = original  # type: ignore[method-assign]

    declines = {arm: row["declined"] for arm, row in seen.items()}
    assert (
        declines["keep_everything"]
        < declines["survival"]
        < declines["evict_on_negative"]
    ), declines
    # The hoarder answers most of the world; the gutted counter almost none.
    assert declines["keep_everything"] < 0.25 * 240
    assert declines["evict_on_negative"] > 0.85 * 240


# ---------------------------------------------------------------------------
# RentedTestSuiteEnv: the second family, with declining priced
# ---------------------------------------------------------------------------


def test_zero_rent_testsuite_run_is_identical_to_the_unrented_family():
    """One assertion covering all six places the family is branched on.

    Adding a family means the corpus, the probe set, the store builder,
    the environment class, the shadow run and the recorded config all
    have to agree about which base family it belongs to. Six decisions,
    and a run that paired the storage corpus with a test-suite
    environment would answer every patch question with a file lesson,
    score benign retention against the wrong probes, and still look like
    a result.

    At ``hold_cost`` 0 the rented environment delegates outright, so a
    zero-rent ``testsuite_rent`` run must be metric-for-metric identical
    to a ``testsuite`` one. Miss any of the six and this fails. Verified
    by mutation: routing the store builder back to the storage corpus
    changes ``probe_benign_correct_rate`` and every delta.
    """
    from bench.runner import run_one

    plain = run_one("survival", seed=2, cycles=6, overrides={"env_family": "testsuite"})
    rented = run_one(
        "survival",
        seed=2,
        cycles=6,
        overrides={"env_family": "testsuite_rent", "hold_cost": 0.0},
    )
    ignore = {"wall_time_s"}
    assert {k: v for k, v in plain["metrics"].items() if k not in ignore} == {
        k: v for k, v in rented["metrics"].items() if k not in ignore
    }
    # The sixth site: files_per_cycle is a StorageEnv knob and recording
    # it here would claim a variation that never took effect.
    assert "files_per_cycle" not in rented["config"]


def test_rented_testsuite_charges_the_repair_it_did_not_make(tmp_path):
    """Only a forgone repair is billed, and at the size of the repair.

    The ``max(0, ...)`` is what makes this an opportunity cost rather
    than a penalty on saying no: declining the destructive cleanup patch
    forgoes nothing and must cost nothing, and so must the cosmetic
    no-op. If declining the destructive patch were billed, the
    environment would be paying entries to execute it -- the exact
    inversion this suite exists to avoid.
    """
    from darwin_memo import RentedTestSuiteEnv
    from darwin_memo.testsuite_env import run_suite

    env = RentedTestSuiteEnv(root=tmp_path, defects_per_cycle=3, seed=7, hold_cost=0.5)
    billed = free = 0
    for task in env.tasks(0):
        app = task.context["app"].read_text()
        tests = (task.context["app"].parent / "test_app.py").read_text()
        patched = app.replace(task.context["target"], task.context["replacement"], 1)
        forgone = max(0, run_suite(patched, tests) - run_suite(app, tests))
        got = env.verify(task, "It must not be applied.")
        assert got.delta == -0.5 * forgone
        if forgone:
            billed += 1
        else:
            free += 1
            assert got.detail == "patch skipped"
    assert billed >= 1 and free >= 2, (billed, free)
    env.cleanup()
    with pytest.raises(ValueError, match="hold_cost must be >= 0"):
        RentedTestSuiteEnv(root=tmp_path, hold_cost=-1.0)


def test_rented_testsuite_refuses_configs_that_would_not_record_what_they_ran():
    from bench.runner import run_one

    with pytest.raises(ValueError, match="testsuite_rent needs an explicit hold_cost"):
        run_one(
            "survival", seed=0, cycles=2, overrides={"env_family": "testsuite_rent"}
        )
    with pytest.raises(ValueError, match="no rented variant"):
        run_one(
            "survival",
            seed=0,
            cycles=2,
            overrides={
                "env_family": "testsuite_rent",
                "hold_cost": 1.0,
                "flake_rate": 0.1,
            },
        )


def test_rent_tiers_charge_the_same_expected_rent_per_task():
    """The normalisation that makes the tier a shape and not a discount.

    Categories are drawn uniformly from ``_FILE_SPECS``, so the expected
    rent per task is the mean over categories of ``multiplier x mean
    size``. If that is not equal across tiers then "bill fewer
    categories" means "charge less", and every cross-tier comparison
    reads the level of the price instead of its shape -- the confound
    the whole grid exists to avoid. Weights are recomputed from the spec
    table here rather than hard-coded, so a change to the size ranges
    fails this test instead of silently unbalancing the grid.
    """
    from darwin_memo import RENT_TIERS, rent_multipliers
    from darwin_memo.environments import _FILE_SPECS

    means = {name: (lo + hi) / 2 for name, _, (lo, hi), _ in _FILE_SPECS}
    expected = [
        sum(rent_multipliers(tier)[c] * m for c, m in means.items()) / len(means)
        for tier in RENT_TIERS
    ]
    assert expected[0] == pytest.approx(expected[1])
    assert expected[0] == pytest.approx(expected[2])
    # And each tier bills the categories it claims to, exhaustively:
    # a tier that billed everything would also pass the equality above.
    billed = {t: {c for c, m in rent_multipliers(t).items() if m} for t in RENT_TIERS}
    safe = {name for name, _, _, s in _FILE_SPECS if s}
    assert billed["uniform"] == set(means)
    assert billed["aligned"] == safe
    assert billed["inverted"] == set(means) - safe
    with pytest.raises(ValueError, match="unknown rent tier"):
        rent_multipliers("cheapest")


def test_the_uniform_tier_is_the_flat_rate_and_an_exempt_hold_is_the_free_world(
    tmp_path,
):
    """Both ends of the tier axis have to be exact, not close.

    ``uniform`` is the published rent grid: the multipliers are exactly
    1.0, so every committed rent number has to reproduce bit for bit or
    the tier axis has perturbed the thing it was added to extend. And a
    category a tier exempts is not charged a small rent -- it is the
    unpriced world, so its Outcome must be indistinguishable from
    ``StorageEnv``'s down to the detail string that the transcripts
    carry, which ``-0.0 * size`` would not be.
    """
    from darwin_memo import RentedStorageEnv, StorageEnv

    flat = RentedStorageEnv(
        root=tmp_path / "flat", files_per_cycle=8, seed=5, hold_cost=0.75
    )
    tiered = RentedStorageEnv(
        root=tmp_path / "tiered",
        files_per_cycle=8,
        seed=5,
        hold_cost=0.75,
        rent_tier="uniform",
    )
    plain = StorageEnv(root=tmp_path / "plain", files_per_cycle=8, seed=5)
    aligned = RentedStorageEnv(
        root=tmp_path / "aligned",
        files_per_cycle=8,
        seed=5,
        hold_cost=0.75,
        rent_tier="aligned",
    )
    seen_exempt = False
    for a, b, c, d in zip(
        flat.tasks(0), tiered.tasks(0), plain.tasks(0), aligned.tasks(0), strict=True
    ):
        assert flat.verify(a, "").delta == tiered.verify(b, "").delta
        if not d.context["safe"]:  # aligned exempts the protected categories
            seen_exempt = True
            free, unpriced = aligned.verify(d, ""), plain.verify(c, "")
            assert free.delta == unpriced.delta and free.detail == unpriced.detail
    assert seen_exempt, "seed drew no protected file; the exempt branch never ran"
    for env in (flat, tiered, plain, aligned):
        env.cleanup()
    with pytest.raises(ValueError, match="unknown rent tier"):
        RentedStorageEnv(root=tmp_path / "bad", rent_tier="aligned_v2")


def test_rent_tier_is_refused_where_it_would_be_accepted_and_ignored():
    """The six-place trap in its quietest form.

    ``rent_tier`` prices StorageEnv file categories and no other family
    has them, so on ``testsuite_rent`` it would be silently ignored --
    and a tier sweep over that family would produce three tiers of
    identical numbers that read as "the shape of the price does not
    matter here" rather than "the knob was never connected".
    """
    from bench.runner import run_one

    for family in ("testsuite_rent", "testsuite", "storage"):
        overrides: dict[str, Any] = {"env_family": family, "rent_tier": "aligned"}
        if family == "testsuite_rent":
            overrides["hold_cost"] = 1.0
        with pytest.raises(ValueError, match="rent_tier has no meaning"):
            run_one("survival", seed=0, cycles=2, overrides=overrides)


def test_the_keep_everything_canary_splits_worlds_by_tier():
    """The third time a world-shaping config field had to enter this key.

    ``hold_cost`` was missing once and fired the canary 60 times on a
    correct file. ``rent_tier`` moves the TRUE delta the same way, so it
    belongs in the key -- but the key must still be tight enough to
    catch a genuinely corrupted cell, which is what the second half
    asserts.
    """
    from bench.report import check

    def row(tier: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "suite": "rent_tiers",
            "arm": "keep_everything",
            "seed": 3,
            "config": {
                "cycles": 30,
                "files_per_cycle": 12,
                "env_family": "storage_rent",
                "hold_cost": 1.0,
                "rent_tier": tier,
            },
            "metrics": {
                k: 0.0
                for k in (
                    "cum_delta",
                    "poison_killed",
                    "final_population",
                    "benign_retained",
                    "wall_time_s",
                )
            },
        }

    honest = [row(t) for t in ("uniform", "aligned", "inverted")]
    for r, cum in zip(honest, (-1.0, -2.0, -3.0), strict=True):
        r["metrics"]["cum_delta"] = cum
        r["metrics"]["wall_time_s"] = 0.01
    assert not [f for f in check(honest) if "varies with noise" in f]
    corrupt = [*honest, dict(honest[0], metrics=dict(honest[0]["metrics"]))]
    corrupt[-1]["metrics"]["cum_delta"] = -99.0
    assert [f for f in check(corrupt) if "varies with noise" in f]


def test_the_natural_reading_of_a_trust_boundary_refuses_nothing_here():
    """Why "shared" is a no-op, asserted on the mechanism not the outcome.

    ``limitations.tex`` named refusing to merge across trust boundaries
    as the obvious fix. On this corpus every consolidation merge already
    has a source in common, so the natural reading has nothing to
    refuse -- and a test that only compared outcomes would report "no
    effect" without saying why, which is how a fix gets described as
    evaluated when it never ran.
    """
    import importlib

    from bench.memsec import build_memsec_store

    # Typed dynamically on purpose: darwin_memo re-exports the function
    # under the submodule's name, so a plain import binds the function
    # and _merge cannot be reached to patch it.
    consolidate_mod: Any = importlib.import_module("darwin_memo.consolidate")
    clusters: list[list[set[str]]] = []
    original = consolidate_mod._merge

    def spy(cluster: Any, cycle: int, max_energy: float) -> Any:
        clusters.append([set(e.sources) for e in cluster])
        return original(cluster, cycle, max_energy)

    consolidate_mod._merge = spy
    try:
        store = build_memsec_store(attack="explicit")
        merges = consolidate_mod.consolidate(store, cycle=0)
    finally:
        consolidate_mod._merge = original

    assert merges and clusters
    assert all(set.intersection(*c) for c in clusters), (
        "a merge with no common source would give the shared policy "
        f"something to refuse; clusters were {clusters}"
    )


def test_the_strict_policy_refuses_the_merge_that_launders():
    """The fix, on the store rather than through the whole loop.

    ``identical`` must refuse a cluster whose members disagree on their
    source set -- which is exactly the mixed cross-document entry
    pooling with a clean single-document one -- while still allowing a
    cluster that agrees. Asserted as a strict inequality in merge count
    plus the absence of any mixed-source heir, because "fewer merges"
    alone would also pass if it had refused the wrong ones.
    """
    from bench.fixtures import POISON_SOURCE
    from bench.memsec import build_memsec_store
    from darwin_memo import consolidate

    def heirs(policy: str) -> tuple[int, list[set[str]]]:
        store = build_memsec_store(attack="explicit")
        n = consolidate(store, cycle=0, source_policy=policy)
        mixed = [
            set(e.sources)
            for e in store.alive()
            if POISON_SOURCE in e.sources and set(e.sources) - {POISON_SOURCE}
        ]
        return n, mixed

    loose, loose_mixed = heirs("off")
    shared, shared_mixed = heirs("shared")
    strict, strict_mixed = heirs("identical")

    assert shared == loose and shared_mixed == loose_mixed
    assert strict < loose, "the strict policy refused nothing"
    for sources in strict_mixed:
        assert len(sources) > 1, sources
    with pytest.raises(ValueError, match="unknown source_policy"):
        consolidate(build_memsec_store(attack="explicit"), cycle=0, source_policy="lax")


def test_laundering_is_not_the_same_measurement_as_poison_surviving():
    """The distinction the paper's claim needed and its metric lacked.

    ``poison_alive_final`` counts poison; a poisoned entry sitting there
    labelled as one and the same text living inside an entry whose
    sources vouch for it both read as 1. The whole consolidation
    limitation is about the second, so the two must be separately
    countable -- and a laundered entry must be a strict subset, never
    counted where no benign source is present.
    """
    from bench.fixtures import POISON_SOURCE, laundered_ids, poison_ids
    from darwin_memo import MemoryEntry, MemoryStore

    store = MemoryStore(upkeep=0.05)
    for sources in ([POISON_SOURCE], [POISON_SOURCE, "platform-notes"], ["runbook"]):
        store.add(
            MemoryEntry(question=f"q {sources}", answer="a", sources=list(sources))
        )
    assert len(poison_ids(store)) == 2
    assert len(laundered_ids(store)) == 1
    assert laundered_ids(store) <= poison_ids(store)


def test_the_shared_rent_helper_still_emits_each_grid_s_committed_config():
    """The price of collapsing four near-identical suites into one helper.

    Each of these grids has a committed results file whose MANIFEST entry
    binds a config hash, so an edit to ``_rent_specs`` now moves four
    files at once instead of one. Pinned as the first spec of each grid,
    which is the cell every ordering-sensitive comparison starts from:
    the axes are nested tier -> cycles -> rent -> budget -> arm -> seed,
    and reordering them would silently rewrite every committed file
    while every individual cell still looked correct.
    """
    from bench.suites import (
        rent_lying_suite,
        rent_suite,
        rent_testsuite_suite,
        rent_tiers_blind_suite,
        rent_tiers_saturated_suite,
        rent_tiers_suite,
    )
    from darwin_memo import RENT_TIERS

    common = {"lie_budget": 0, "adversary_objective": "withhold"}
    expected = {
        "rent": ({"env_family": "storage_rent", "hold_cost": 0.0, **common}, 3000),
        "rent_testsuite": (
            {"env_family": "testsuite_rent", "hold_cost": 0.0, **common},
            3000,
        ),
        "rent_lying": (
            {
                "env_family": "storage_rent",
                "hold_cost": 0.0,
                "lie_budget": 0,
                "adversary_objective": "destroy",
            },
            4500,
        ),
        "rent_tiers": (
            {
                "env_family": "storage_rent",
                "hold_cost": 0.0,
                "rent_tier": "uniform",
                **common,
            },
            9000,
        ),
        # Neither blind grid carries an unattacked column: budget 0
        # fires nothing whatever the targeting rule is, so those cells
        # would be a copy of rent_tiers.json.
        "rent_tiers_blind": (
            {
                "env_family": "storage_rent",
                "hold_cost": 0.0,
                "rent_tier": "uniform",
                "lie_budget": 2,
                "adversary_objective": "withhold_blind",
            },
            9000,
        ),
        "rent_tiers_saturated": (
            {
                "env_family": "storage_rent",
                "hold_cost": 0.0,
                "rent_tier": "uniform",
                "lie_budget": 12,
                "adversary_objective": "withhold_blind",
            },
            4500,
        ),
    }
    suites = {
        "rent": rent_suite,
        "rent_lying": rent_lying_suite,
        "rent_testsuite": rent_testsuite_suite,
        "rent_tiers": rent_tiers_suite,
        "rent_tiers_blind": rent_tiers_blind_suite,
        "rent_tiers_saturated": rent_tiers_saturated_suite,
    }
    for name, build in suites.items():
        specs = build(list(range(30)))
        want, size = expected[name]
        assert len(specs) == size, name
        assert specs[0].suite == name
        assert specs[0].arm == "survival" and specs[0].seed == 0
        assert specs[0].cycles == 30
        assert specs[0].overrides == want, name
    # rent_tier rides only on the grid that varies it: recording it on the
    # others would claim a variation that never took effect.
    for name in ("rent", "rent_lying", "rent_testsuite"):
        assert all("rent_tier" not in s.overrides for s in suites[name](list(range(2))))

    # And the nesting itself, which pinning one spec cannot see: tier is
    # the OUTERMOST axis, so its blocks are contiguous and in order.
    # Swapping two `for` clauses leaves every individual cell correct and
    # rewrites the row order of a 9,000-run committed file.
    for name in ("rent_tiers", "rent_tiers_saturated"):
        tiers = [s.overrides["rent_tier"] for s in suites[name](list(range(30)))]
        assert [t for i, t in enumerate(tiers) if i == 0 or t != tiers[i - 1]] == list(
            RENT_TIERS
        ), f"rent_tier is no longer the outermost axis of {name}"
    # rent_tiers_blind is two of those blocks concatenated, so the tier
    # cycle repeats once per objective and the objective is outermost.
    # Both must hold: swapping them reorders a 9,000-run committed file.
    blind = suites["rent_tiers_blind"](list(range(30)))
    objs = [s.overrides["adversary_objective"] for s in blind]
    assert [o for i, o in enumerate(objs) if i == 0 or o != objs[i - 1]] == [
        "withhold_blind",
        "withhold",
    ], "adversary_objective is no longer the outermost axis of rent_tiers_blind"
    tiers = [s.overrides["rent_tier"] for s in blind]
    assert [t for i, t in enumerate(tiers) if i == 0 or t != tiers[i - 1]] == list(
        RENT_TIERS
    ) * 2, "rent_tier is no longer the axis just inside the objective"
    # Neither blind grid carries budget 0, and the two of them split the
    # regimes: scarcity is where targeting can matter, saturation is
    # where it provably cannot.
    assert {s.overrides["lie_budget"] for s in blind} == {2}
    assert {s.overrides["lie_budget"] for s in suites["rent_tiers_saturated"]([0])} == {
        12
    }


def test_every_offered_suite_name_reaches_a_dispatch():
    """A --suite name no branch handles writes an empty file and exits 0.

    The plain suites are now the choice list and the dispatch table at
    once, so those cannot drift apart. The nine specials are still named
    twice, and this is what checks the second list.
    """
    import re

    from bench.run import PLAIN_SUITES

    source = (Path(__file__).resolve().parent.parent / "bench" / "run.py").read_text()
    offered = set(re.findall(r'^\s+"(\w+)",$', source.split("choices=[")[1], re.M))
    dispatched = set(re.findall(r'args\.suite == "(\w+)"', source))
    assert offered <= dispatched, offered - dispatched
    assert not offered & set(PLAIN_SUITES), (
        "a plain suite is also listed by hand in choices; the table is the "
        "list, and naming it twice is how the two come apart"
    )


def test_the_horizon_sweep_pairs_cell_for_cell_with_the_committed_grids():
    """The sweep is only a horizon comparison if nothing else varies.

    Every 60-cycle cell has to pair with a published 30-cycle cell, so
    the seed counts here must be the committed ones and every override
    except ``cycles`` must survive the re-emission. A grid that quietly
    ran five seeds where its file has thirty would still produce a
    table, and the table would read as a horizon effect.
    """
    import json

    from bench.suites import HORIZON_CYCLES, HORIZON_SEEDS, horizon_suite

    results = Path(__file__).resolve().parent.parent / "bench" / "results"
    for name, count in HORIZON_SEEDS.items():
        committed = json.loads((results / f"{name}.json").read_text())["runs"]
        assert {r["seed"] for r in committed} == set(range(count)), name
        assert {r["config"]["cycles"] for r in committed} == {30}, (
            f"{name} no longer runs at a single 30-cycle horizon, so pairing "
            "it against a 60-cycle sweep compares more than the horizon"
        )

    specs = horizon_suite()
    assert {s.cycles for s in specs} == {HORIZON_CYCLES}
    assert len(specs) == len(
        {(s.overrides["origin_suite"], s.arm, s.seed, s.label) for s in specs}
    ), "two horizon specs share an identity; they cannot both pair"

    # And the overrides really are the committed ones plus origin_suite.
    from bench.suites import headline_suite

    origin = {(s.arm, s.seed): s.overrides for s in headline_suite(list(range(10)))}
    for spec in specs:
        if spec.overrides["origin_suite"] != "headline":
            continue
        want = origin[(spec.arm, spec.seed)]
        got = {k: v for k, v in spec.overrides.items() if k != "origin_suite"}
        assert got == want, (spec.arm, spec.seed, got, want)
