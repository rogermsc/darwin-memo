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
