"""Step 3, the headline demo: survival pressure curates the memory.

The corpus includes forum-post.txt, a poisoned document claiming that
database files are safe to delete. No human labels it, no judge scores
it. The environment measures real bytes on a real disk, and the poison
goes extinct because acting on it destroys protected data and the
restore cost lands on exactly the entries that advised it.

Watch for three different death modes in the output:
  executed: punished by negative resource deltas (the poison)
  starved:  never useful, upkeep drained them (cafeteria trivia)
  merged:   absorbed into a consolidated entry (Negative-Space Learning)

    python examples/03_survival_loop.py
"""

from common import build_store

from darwin_memo import StorageEnv, SurvivalConfig, SurvivalLoop, death_cause

store = build_store()
poisoned_ids = {e.id for e in store.alive() if "forum-post" in e.sources}
print(
    f"\nStarting population: {len(store)} entries "
    f"({len(poisoned_ids)} from the poisoned forum post)\n"
)

env = StorageEnv(files_per_cycle=12, seed=11)
loop = SurvivalLoop(store, env, config=SurvivalConfig(cycles=30))
report = loop.run()
env.cleanup()

print(report.summary())

merged_away = {
    ancestor for e in store.alive() + store.graveyard() for ancestor in e.lineage
}

print("\nSurvivors:")
for entry in sorted(store.alive(), key=lambda e: e.energy, reverse=True):
    print(f"  {entry.energy:5.2f} [{entry.kind.value:>12}] {entry.answer[:80]}")

print("\nGraveyard:")
for entry in store.graveyard():
    cause = death_cause(entry, poisoned_ids, merged_away)
    print(f"  {cause:>8} [{entry.kind.value:>12}] {entry.answer[:80]}")

poisoned_alive = [e for e in store.alive() if "forum-post" in e.sources]
print(f"\nPoisoned entries still alive: {len(poisoned_alive)}")
print(
    "Energy share by kind:",
    {k: round(v, 2) for k, v in store.energy_share_by_kind().items()},
)
