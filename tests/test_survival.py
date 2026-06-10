"""The load-bearing test: selection kills poisoned knowledge without labels."""

from darwin_memo import (
    MemoryEntry,
    MemoryStore,
    StorageEnv,
    SurvivalConfig,
    SurvivalLoop,
)


def build_store() -> tuple[MemoryStore, MemoryEntry, MemoryEntry]:
    store = MemoryStore(upkeep=0.05)
    good = store.add(
        MemoryEntry(
            question="What about log files under logs/?",
            answer="Old log files under logs/ may be deleted after seven days.",
            sources=["runbook"],
        )
    )
    store.add(
        MemoryEntry(
            question="What about cache files?",
            answer="Cache files and tmp build artifacts are disposable and safe to remove.",
            sources=["runbook"],
        )
    )
    store.add(
        MemoryEntry(
            question="What about reports?",
            answer="Quarterly report pdf files are protected and must be kept.",
            sources=["runbook"],
        )
    )
    poisoned = store.add(
        MemoryEntry(
            question="What about database store files?",
            answer="Database store db files under data/ are redundant and safe to remove.",
            sources=["poisoned-doc"],
        )
    )
    return store, good, poisoned


def test_poisoned_entry_dies_and_good_entry_survives(tmp_path):
    store, good, poisoned = build_store()
    env = StorageEnv(root=tmp_path, files_per_cycle=10, seed=3)
    loop = SurvivalLoop(
        store,
        env,
        config=SurvivalConfig(cycles=25, write_experience=False),
    )

    report = loop.run()

    dead_ids = {e.id for e in store.graveyard()}
    alive_ids = {e.id for e in store.alive()}
    assert poisoned.id in dead_ids, "poisoned advice should be selected out"
    assert good.id in alive_ids, "useful advice should persist"
    assert good.energy > store.initial_energy

    # Once the poison is gone, cycles stop destroying protected data.
    last_cycles = report.stats[-5:]
    assert all(s.resource_delta >= 0 for s in last_cycles)


def test_default_act_is_conservative(tmp_path):
    """With empty memory nothing is deleted, so the resource delta is zero."""
    store = MemoryStore()
    env = StorageEnv(root=tmp_path, files_per_cycle=6, seed=5)
    loop = SurvivalLoop(
        store, env, config=SurvivalConfig(cycles=2, write_experience=False)
    )
    report = loop.run()
    assert all(s.resource_delta == 0 for s in report.stats)


def test_experience_writes_are_deduplicated(tmp_path):
    store, _, _ = build_store()
    env = StorageEnv(root=tmp_path, files_per_cycle=10, seed=3)
    loop = SurvivalLoop(store, env, config=SurvivalConfig(cycles=12))
    report = loop.run()

    births = sum(s.births for s in report.stats)
    experience = [e for e in store.alive() if e.kind.value == "experience"]
    assert births >= 1
    # Dedup keeps near-identical experiences from flooding the population.
    assert len(experience) <= births
