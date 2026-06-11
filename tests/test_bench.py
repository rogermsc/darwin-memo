"""Unit tests for the benchmark harness policies and reporting."""

import tempfile
from pathlib import Path

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
