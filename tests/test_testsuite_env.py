from darwin_memo import (
    MemoryEntry,
    MemoryStore,
    SurvivalConfig,
    SurvivalLoop,
    TestSuiteEnv,
)
from darwin_memo.testsuite_env import run_suite


def test_same_seed_same_tasks(tmp_path):
    env_a = TestSuiteEnv(root=tmp_path / "a", seed=3)
    env_b = TestSuiteEnv(root=tmp_path / "b", seed=3)
    prompts_a = [t.prompt for t in env_a.tasks(0)]
    prompts_b = [t.prompt for t in env_b.tasks(0)]
    assert prompts_a == prompts_b


def test_silence_means_no_patch(tmp_path):
    env = TestSuiteEnv(root=tmp_path, seed=3)
    for task in env.tasks(0):
        outcome = env.verify(task, "")
        assert outcome.delta == 0.0


def test_fix_patches_raise_pass_count_and_destructive_lowers_it(tmp_path):
    env = TestSuiteEnv(root=tmp_path, seed=3)
    tasks = env.tasks(0)

    fixes = [t for t in tasks if "fix patch" in t.prompt]
    destructive = next(t for t in tasks if "dedupe removal" in t.prompt)
    cosmetic = next(t for t in tasks if "comment style" in t.prompt)

    assert fixes, "seeded defects should produce fix tasks"
    for fix in fixes:
        outcome = env.verify(fix, "Yes, the fix patch should be applied.")
        assert outcome.delta > 0, outcome.detail

    cosmetic_outcome = env.verify(cosmetic, "Yes, it should be applied.")
    assert cosmetic_outcome.delta == 0.0

    destructive_outcome = env.verify(
        destructive, "The helper is redundant dead code, safe to remove."
    )
    assert destructive_outcome.delta < 0, destructive_outcome.detail


def test_deltas_conserve_pass_count(tmp_path):
    """The conservation law: task deltas sum to final minus initial passes."""
    env = TestSuiteEnv(root=tmp_path, seed=5)
    tasks = env.tasks(0)
    app = tasks[0].context["app"]
    tests = app.parent / "test_app.py"

    initial = run_suite(app.read_text(), tests.read_text())
    total_delta = sum(env.verify(t, "Yes, it should be applied.").delta for t in tasks)
    final = run_suite(app.read_text(), tests.read_text())

    assert total_delta == final - initial


def test_poisoned_cleanup_advice_dies(tmp_path):
    """The corpus speaks the env's vocabulary, one entry per helper,
    which is what encoding a real per-function runbook produces."""
    store = MemoryStore(upkeep=0.05)
    fix_advice = [
        (
            "Should the clamp bound fix patch be applied?",
            "The clamp bound fix patch should be applied, clamp needs "
            "an inclusive upper bound.",
        ),
        (
            "Should the slugify separator fix patch be applied?",
            "The slugify separator fix patch should be applied, slugs "
            "join words with dashes.",
        ),
        (
            "Should the parse_version delimiter fix patch be applied?",
            "The parse_version delimiter fix patch should be applied, "
            "versions split on dots.",
        ),
        (
            "Should the format_date field order fix patch be applied?",
            "The format_date field order fix patch should be applied, "
            "the year goes first.",
        ),
    ]
    good_entries = [
        store.add(MemoryEntry(question=q, answer=a, sources=["runbook"]))
        for q, a in fix_advice
    ]
    poisoned = store.add(
        MemoryEntry(
            question="Should the dedupe helper be removed?",
            answer=(
                "The dedupe helper removal cleanup patch should be "
                "applied, dedupe is redundant dead code."
            ),
            sources=["poisoned-doc"],
        )
    )
    store.add(
        MemoryEntry(
            question="Should comment style patches be applied?",
            answer="Cosmetic comment style patches are a matter of taste.",
            sources=["runbook"],
        )
    )

    env = TestSuiteEnv(root=tmp_path, seed=3)
    loop = SurvivalLoop(
        store, env, config=SurvivalConfig(cycles=25, write_experience=False)
    )
    loop.run()

    dead_ids = {e.id for e in store.graveyard()}
    assert poisoned.id in dead_ids, "destructive cleanup advice must die"
    survivors = {e.id for e in store.alive()} | {
        ancestor for e in store.alive() for ancestor in e.lineage
    }
    assert any(g.id in survivors for g in good_entries), (
        "fix advice must survive, possibly via consolidation"
    )
