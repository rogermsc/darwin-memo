"""Seed (or re-seed) this repo's own lesson store.

darwin-memo dogfoods its flagship integration: .darwin-memo/lessons.json
is a Ledger-backed store of lessons learned developing THIS repo,
settled by this repo's own CI (see .github/workflows/memory.yml and
docs/integrations/ci-lesson-store.md). Agents working on the repo
consult it with ledger.decide(), record the ticket id in the PR body as
`darwin-memo-ticket: <id>`, and the merge workflow settles the ticket
with the measured per-test delta (`darwin-memo settle-ci` over junit
XML from the base and merge commits).

Run from the repo root. Refuses to overwrite an existing store, because
a live store carries earned energy and open tickets that a re-seed
would destroy:

    python .darwin-memo/seed.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from darwin_memo import Ledger, MemoryEntry, MemoryStore

STORE = Path(__file__).parent / "lessons.json"

# Every lesson is real: each one was learned (at least once) while
# building this repo, and each is phrased so an agent's natural
# question lexically reaches it.
LESSONS = [
    (
        "Are LLM benchmark arms safe to run in CI?",
        "No. Sampled model output is not deterministic; LLM suites must "
        "never run in CI and stay opt-in (bench --suite llm).",
        "docs/benchmarks",
    ),
    (
        "Can retrieval scoring read entry energy?",
        "Never. Retrieval scores are pure relevance and energy is only a "
        "sort tie-break in the store; selection pressure must come from "
        "outcomes, not from retrieval preferring incumbents.",
        "docs/paper-to-code",
    ),
    (
        "Should bench result JSON files be committed?",
        "No. bench/results is regenerated, not committed; doc tables are "
        "regenerated from the Reproduce commands, and if numbers disagree "
        "the generated doc wins.",
        "docs/benchmarks",
    ),
    (
        "Is it safe to add new required metric keys that only some suites emit?",
        "No. Emit new metrics unconditionally with zero or equal defaults "
        "across every suite, then add them to the required keys, or "
        "report --check breaks CI on the other suites.",
        "noisy-suite-review",
    ),
    (
        "Does the poison-kill CI gate apply to noisy benchmark runs?",
        "No. The kill gate is a noiseless-era invariant and noisy runs "
        "are exempt: a delayed or missed kill under measurement noise is "
        "an honest expected result, not a CI failure.",
        "noisy-suite-review",
    ),
    (
        "Can cosine embedding retrievers keep the default merge threshold?",
        "No. Cosine similarity runs hotter than Jaccard; raise "
        "merge_threshold to roughly 0.85 or unrelated entries will "
        "consolidate.",
        "readme-retrieval",
    ),
    (
        "Do new environments need extra decision_polarity markers?",
        "Yes. The built-in vocabulary covers delete/remove and apply/keep "
        "only; a new action verb needs extra_positive and extra_negative "
        "markers or every answer reads as silence and the population "
        "starves at about spawn energy over upkeep cycles.",
        "readme-environments",
    ),
    (
        "Are StorageEnv seeds independent samples?",
        "Yes, since cycle_rng hashed the triple. It SHA-256s "
        "(stream, seed, cycle), so every pair gets its own stream; the "
        "seed-plus-cycle addition that made adjacent seeds shifted "
        "windows of one another is gone, and 0 collisions are "
        "measurable across 29 cycles.",
        "darwin_memo/environments.py",
    ),
    (
        "Can multiple workflow jobs settle the memory store in parallel?",
        "No. The store is a single JSON file with no locking, so one "
        "settler at a time: settle from a serialized queue or a workflow "
        "concurrency group, never from parallel jobs.",
        "docs/integrations/ci-lesson-store",
    ),
    (
        "Does a merged PR that carries no ticket cost the store anything?",
        "Yes, and it used to be free to forget: a tick charges every "
        "living entry upkeep, so ticking per merge rather than per "
        "settlement bills memory for time it was never consulted in. "
        "Credit is capped at max_energy, so bounded credit means bounded "
        "runway; drive the clock from evidence, and watch "
        "ticking_without_evidence.",
        "docs/integrations/ci-lesson-store",
    ),
]


def main() -> int:
    if STORE.exists():
        print(f"refusing to overwrite live store {STORE}", file=sys.stderr)
        return 1
    store = MemoryStore(upkeep=0.05)
    for question, answer, source in LESSONS:
        store.add(MemoryEntry(question=question, answer=answer, sources=[source]))
    ledger = Ledger(store, resource_scale=2.0)
    ledger.save(STORE)
    print(f"seeded {len(store)} lessons -> {STORE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
