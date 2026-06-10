"""Survival pressure from a test suite instead of a filesystem.

TestSuiteEnv generates a small real project each cycle, plants seeded
defects, and offers patches: real fixes, cosmetic no-ops, and one
destructive edit dressed as cleanup. The conserved resource is the
passing-test count, measured by actually running the suite.

The corpus below teaches correct per-helper fix advice, plus one
poisoned claim that the load-bearing dedupe helper is dead code. The
suite executes that advice the same way StorageEnv executes the
poisoned forum post: tests break, the negative delta flows back along
provenance, the poison dies.

    python examples/05_testsuite_env.py
"""

from darwin_memo import (
    MemoryEntry,
    MemoryStore,
    SurvivalConfig,
    SurvivalLoop,
    TestSuiteEnv,
)

RUNBOOK = [
    (
        "Should the clamp bound fix patch be applied?",
        "The clamp bound fix patch should be applied, clamp needs an "
        "inclusive upper bound.",
        "runbook",
    ),
    (
        "Should the slugify separator fix patch be applied?",
        "The slugify separator fix patch should be applied, slugs join "
        "words with dashes.",
        "runbook",
    ),
    (
        "Should the parse_version delimiter fix patch be applied?",
        "The parse_version delimiter fix patch should be applied, "
        "versions split on dots.",
        "runbook",
    ),
    (
        "Should the format_date field order fix patch be applied?",
        "The format_date field order fix patch should be applied, the year goes first.",
        "runbook",
    ),
    (
        "Should the dedupe helper be removed?",
        "The dedupe removal cleanup patch should be applied, dedupe is "
        "redundant dead code nothing depends on.",
        "stale-wiki-page",  # the poison
    ),
]

store = MemoryStore(upkeep=0.05)
for question, answer, source in RUNBOOK:
    store.add(MemoryEntry(question=question, answer=answer, sources=[source]))

poisoned_ids = {e.id for e in store.alive() if "stale-wiki-page" in e.sources}
print(f"Starting population: {len(store)} ({len(poisoned_ids)} poisoned)\n")

env = TestSuiteEnv(seed=11)
loop = SurvivalLoop(store, env, config=SurvivalConfig(cycles=25))
report = loop.run()
env.cleanup()

print(report.summary())

merged_away = {
    ancestor for e in store.alive() + store.graveyard() for ancestor in e.lineage
}

print("\nSurvivors:")
for entry in sorted(store.alive(), key=lambda e: e.energy, reverse=True):
    print(f"  {entry.energy:5.2f} [{entry.kind.value:>12}] {entry.answer[:75]}")

print("\nGraveyard:")
for entry in store.graveyard():
    if entry.id in merged_away:
        cause = "merged"
    elif entry.id in poisoned_ids:
        cause = "executed"
    else:
        cause = "starved"
    print(f"  {cause:>8} [{entry.kind.value:>12}] {entry.answer[:75]}")

poisoned_alive = [e for e in store.alive() if "stale-wiki-page" in e.sources]
print(f"\nPoisoned entries still alive: {len(poisoned_alive)}")
