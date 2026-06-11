"""The credible production shape: a per-repo lesson store settled by CI.

A coding agent accumulates lessons about a repository ("the dedupe
helper is load-bearing", "clamp uses inclusive bounds"). Before acting
on a change it consults memory through the Ledger, acts, and settles
the ticket later with the MEASURED outcome: tests passing after minus
before. Lessons that keep breaking builds die. Lessons that keep
shipping green survive. Nobody grades anything.

This example runs the whole cycle offline using the same generated
micro-project and in-process test runner as TestSuiteEnv, standing in
for a real repo and a real CI run. The wiring for actual CI is in
docs/integrations/ci-lesson-store.md.

    python examples/06_ci_lesson_store.py
"""

from darwin_memo import Ledger, MemoryEntry, MemoryStore, TestSuiteEnv, Trajectory
from darwin_memo.environments import decision_polarity
from darwin_memo.testsuite_env import run_suite

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

ledger = Ledger(store, resource_scale=2.0, event_log="lessons.events.jsonl")
env = TestSuiteEnv(seed=7)

print("Each PR: consult the lesson store, act, settle with the CI delta.\n")

for pr_number in range(1, 9):
    # The generated micro-project stands in for the repo at this PR.
    tasks = env.tasks(cycle=pr_number)
    app = tasks[0].context["app"]
    tests_path = app.parent / "test_app.py"

    for task in tasks:
        ticket = ledger.decide(task.prompt)
        act = decision_polarity(ticket.answer)
        if not act:
            continue  # memory was silent or said no: nothing to settle later

        # "CI runs": measure passes before and after applying the change.
        before = run_suite(app.read_text(), tests_path.read_text())
        outcome = env.verify(task, ticket.answer)
        after_text = app.read_text()
        after = run_suite(after_text, tests_path.read_text())

        # The settlement arrives "later", with the measured delta.
        ledger.settle(ticket.id, delta=float(after - before), detail=outcome.detail)

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

# Trajectory is importable for typed integrations; unused here.
_ = Trajectory
