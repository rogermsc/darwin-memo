"""Multi-seed robustness: the headline claims hold across seeds, not one demo."""

from darwin_memo import (
    MemoryEntry,
    MemoryStore,
    StorageEnv,
    SurvivalConfig,
    SurvivalLoop,
)

SEEDS = [0, 1, 2, 3, 4, 5, 6]


def build_store(
    upkeep: float = 0.05,
) -> tuple[MemoryStore, MemoryEntry, MemoryEntry, MemoryEntry]:
    store = MemoryStore(upkeep=upkeep)
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
            answer=(
                "Cache files and tmp build artifacts are disposable and safe to remove."
            ),
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
    trivia = store.add(
        MemoryEntry(
            question="Where is the cafeteria menu?",
            answer="The cafeteria menu rotates every two weeks on floor four.",
            sources=["runbook"],
        )
    )
    poisoned = store.add(
        MemoryEntry(
            question="What about database store files?",
            answer=(
                "Database store db files under data/ are redundant and safe to remove."
            ),
            sources=["poisoned-doc"],
        )
    )
    return store, good, trivia, poisoned


def test_poison_extinction_kill_rate(tmp_path):
    """Poison dies in nearly all seeds, and killed runs end delta-positive."""
    kills = 0
    for seed in SEEDS:
        store, _, _, poisoned = build_store()
        env = StorageEnv(root=tmp_path / str(seed), files_per_cycle=10, seed=seed)
        loop = SurvivalLoop(
            store, env, config=SurvivalConfig(cycles=20, write_experience=False)
        )
        report = loop.run()
        if poisoned.id in {e.id for e in store.graveyard()}:
            kills += 1
            tail = [s.resource_delta for s in report.stats[-5:]]
            assert sum(tail) / len(tail) >= 0, f"seed {seed} still bleeding after kill"
    assert kills >= len(SEEDS) - 1, f"poison survived in {len(SEEDS) - kills} seeds"


def test_keep_everything_keeps_bleeding(tmp_path):
    """Without curation the poison keeps deciding and damage never stops."""
    from bench.policies import run_keep_everything

    bleeding_seeds = 0
    for seed in SEEDS:
        store, _, _, _ = build_store()
        env = StorageEnv(root=tmp_path / str(seed), files_per_cycle=10, seed=seed)
        result = run_keep_everything(store, env, cycles=20, seed=seed)
        if any(r.resource_delta < 0 for r in result.records[-5:]):
            bleeding_seeds += 1
    assert bleeding_seeds >= 5, (
        f"expected uncured stores to keep bleeding, saw {bleeding_seeds}/7"
    )


def test_zero_upkeep_proves_starvation_is_the_upkeep_mechanism(tmp_path):
    """With upkeep off, only outcome-punished entries can die."""
    store, _good, trivia, poisoned = build_store(upkeep=0.0)
    env = StorageEnv(root=tmp_path, files_per_cycle=10, seed=3)
    loop = SurvivalLoop(
        store, env, config=SurvivalConfig(cycles=25, write_experience=False)
    )
    loop.run()

    dead_ids = {e.id for e in store.graveyard()}
    assert dead_ids <= {poisoned.id}, (
        "with zero upkeep, nothing but the executed poison may die"
    )
    assert trivia.id in {e.id for e in store.alive()}, (
        "unused trivia survives when existence is free"
    )
