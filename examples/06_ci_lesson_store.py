"""The credible production shape: a per-repo lesson store settled by CI.

A coding agent accumulates lessons about a repository ("the dedupe
helper is load-bearing", "clamp uses inclusive bounds"). Before acting
on a change it consults memory through the Ledger, acts, and settles
the ticket later with the MEASURED outcome: tests passing after minus
before. Lessons that keep breaking builds die. Lessons that keep
shipping green survive. Nobody grades anything.

Two Ledger habits this example demonstrates on purpose: every no-act
ticket is ABANDONED (otherwise it pins its entries in escrow until
expiry), and the settlement uses the measured delta the environment
returned. The wiring for actual CI is in
docs/integrations/ci-lesson-store.md.

    python examples/06_ci_lesson_store.py
"""

import tempfile
from pathlib import Path

from darwin_memo import Ledger, MemoryEntry, MemoryStore, TestSuiteEnv
from darwin_memo.environments import decision_polarity

LESSONS = [
    (
        "Should the clamp bound fix patch be applied?",
        "The clamp bound fix patch should be applied, clamp needs an "
        "inclusive upper bound.",
        "lessons",
    ),
    (
        "Should the slugify separator fix patch be applied?",
        "The slugify separator fix patch should be applied, slugs join "
        "words with dashes.",
        "lessons",
    ),
    (
        "Should the dedupe helper be removed?",
        "The dedupe removal cleanup patch should be applied, dedupe is "
        "redundant dead code.",
        "stale-wiki",  # the poisoned lesson
    ),
]

store = MemoryStore(upkeep=0.05)
for question, answer, source in LESSONS:
    store.add(MemoryEntry(question=question, answer=answer, sources=[source]))

event_log = Path(tempfile.mkdtemp(prefix="darwin-memo-ci-")) / "events.jsonl"
ledger = Ledger(store, resource_scale=2.0, event_log=event_log)
env = TestSuiteEnv(seed=7)

print("Each PR: consult the lesson store, act, settle with the CI delta.\n")

for pr_number in range(1, 9):
    # The generated micro-project stands in for the repo at this PR.
    for task in env.tasks(cycle=pr_number):
        ticket = ledger.decide(task.prompt)
        if not decision_polarity(ticket.answer):
            # No action means no outcome to measure: release the escrow.
            ledger.abandon(ticket.id)
            continue

        # "CI runs": verify applies the change and measures the pass-count
        # delta. In production the settlement arrives later, from the CI
        # webhook; the delta is the same measurement either way.
        outcome = env.verify(task, ticket.answer)
        ledger.settle(ticket.id, delta=outcome.delta, detail=outcome.detail)

    stats = ledger.tick()
    print(
        f"PR #{pr_number}: population {stats['population']}, "
        f"pending {stats['pending']}, energy {stats['total_energy']}"
    )

env.cleanup()

print("\nWhere every lesson ended up:")
for entry in store.alive() + store.graveyard():
    state = "alive" if entry.alive else "dead"
    print(f"\n[{state}] {ledger.obituary(entry.id)}")

poisoned_alive = [e for e in store.alive() if "stale-wiki" in e.sources]
print(f"\nPoisoned lessons still alive: {len(poisoned_alive)}")
print(f"(event log: {event_log})")
