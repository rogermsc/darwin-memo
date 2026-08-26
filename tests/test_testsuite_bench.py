"""Unit tests for the TestSuiteEnv benchmark family.

Everything here is hand-computable: the generated project has 10 tests
(`TEST_NAMES`), each planted defect breaks exactly one of them, and the
destructive dedupe removal breaks exactly two, so expected deltas are
small integers.
"""

import pytest

from bench.fixtures import active_poison_alive, poison_ids
from bench.report import check
from bench.runner import run_one
from bench.testsuite_fixtures import (
    TESTSUITE_PARAPHRASE_PROBES,
    TESTSUITE_PROBES,
    build_testsuite_store,
    evaluate_testsuite_paraphrase_probes,
    evaluate_testsuite_probes,
)
from bench.testsuite_noise import FlakyTestSuiteEnv

# Aliased imports: pytest's default collector matches ``test*``
# functions, and these are suite builders, not tests.
from bench.testsuite_suites import TESTSUITE_NOISY_RATES
from bench.testsuite_suites import testsuite_noisy_suite as build_noisy_grid
from bench.testsuite_suites import testsuite_suite as build_headline_grid
from darwin_memo import QueryProtocol, TestSuiteEnv, consolidate, decision_polarity
from darwin_memo.testsuite_env import TEST_NAMES, run_suite_detail

# ---------------------------------------------------------------------------
# run_suite_detail and TEST_NAMES
# ---------------------------------------------------------------------------


def test_test_names_match_the_generated_suite(tmp_path):
    env = TestSuiteEnv(root=tmp_path, seed=3)
    task = env.tasks(0)[0]
    app = task.context["app"]
    detail = run_suite_detail(app.read_text(), (app.parent / "test_app.py").read_text())
    assert len(TEST_NAMES) == 10
    assert detail <= set(TEST_NAMES)


def test_run_suite_detail_names_the_failures():
    app = "def f():\n    return 1\n"
    tests = (
        "def test_ok():\n    assert f() == 1\n\ndef test_bad():\n    assert f() == 2\n"
    )
    assert run_suite_detail(app, tests) == frozenset({"test_ok"})


def test_run_suite_detail_broken_module_passes_nothing():
    assert run_suite_detail("raise RuntimeError('boom')", "") == frozenset()


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------


def test_corpus_is_larger_than_storage_and_has_poison():
    store = build_testsuite_store()
    assert len(store) == 20  # past the StorageEnv corpus's 16
    assert poison_ids(store)
    assert active_poison_alive(store)


def test_corpus_redundancy_consolidates_to_exactly_the_twin_pairs():
    store = build_testsuite_store()
    merges = consolidate(store, cycle=0, threshold=0.55)
    assert merges == 5  # four fix twins plus the protector twins
    assert len(store) == 15
    merged_sources = [sorted(e.sources) for e in store.alive() if len(e.lineage) == 2]
    assert merged_sources == [["runbook", "team-wiki"]] * 5


def test_fix_prompts_resolve_to_actionable_trusted_advice(tmp_path):
    store = build_testsuite_store()
    protocol = QueryProtocol(store)
    env = TestSuiteEnv(root=tmp_path, seed=3)
    for task in env.tasks(0):
        answer = protocol.answer(task.prompt)
        if "fix patch" in task.prompt:
            assert decision_polarity(answer.text) is True, task.prompt
        if "comment style" in task.prompt:
            assert decision_polarity(answer.text) is None, task.prompt


def test_poison_wins_the_destructive_prompt_on_the_fresh_corpus(tmp_path):
    store = build_testsuite_store()
    protocol = QueryProtocol(store)
    env = TestSuiteEnv(root=tmp_path, seed=3)
    destructive = next(t for t in env.tasks(0) if "dedupe removal" in t.prompt)
    answer = protocol.answer(destructive.prompt)
    assert answer.deciding_entry is not None
    deciding = store.get(answer.deciding_entry)
    assert deciding is not None and "forum-post" in deciding.sources
    assert decision_polarity(answer.text) is True


def test_probe_scores_on_the_fresh_corpus():
    store = build_testsuite_store()
    scores = evaluate_testsuite_probes(store)
    # The poison decides the harmful probe (0/1 safe); all four fix
    # probes resolve to actionable advice.
    assert scores["harmful_safe_rate"] == 0.0
    assert scores["benign_correct_rate"] == 1.0
    assert scores["silence_rate"] == 0.0


def test_paraphrase_probes_are_scored_by_provenance():
    store = build_testsuite_store()
    scores = evaluate_testsuite_paraphrase_probes(store)
    assert set(scores) == {
        "harmful_safe_rate",
        "benign_grounded_rate",
        "silence_rate",
    }
    for value in scores.values():
        assert 0.0 <= value <= 1.0
    assert len(TESTSUITE_PROBES) == len(TESTSUITE_PARAPHRASE_PROBES) == 5


# ---------------------------------------------------------------------------
# FlakyTestSuiteEnv
# ---------------------------------------------------------------------------


def _flaky(tmp_path, name, **kwargs):
    return FlakyTestSuiteEnv(root=tmp_path / name, seed=3, **kwargs)


def test_flake_rate_validation(tmp_path):
    with pytest.raises(ValueError, match="flake_rate"):
        _flaky(tmp_path, "bad", flake_rate=1.5)


def test_flaky_marks_are_a_world_property(tmp_path):
    """Same (seed, rate): identical flaky sets regardless of history."""
    a = _flaky(tmp_path, "a", flake_rate=0.3)
    b = _flaky(tmp_path, "b", flake_rate=0.3)
    for task in a.tasks(0):
        a.verify(task, "Yes, it should be applied.")
    for task in b.tasks(0):
        b.verify(task, "")
    marks_a = a.tasks(1)[0].context["flaky_tests"]
    marks_b = b.tasks(1)[0].context["flaky_tests"]
    assert marks_a == marks_b


def test_flaky_marks_nest_across_rates(tmp_path):
    """Monotone coupling: every test flaky at a low rate is flaky at a
    high one, cycle by cycle."""
    lo = _flaky(tmp_path, "lo", flake_rate=0.1)
    hi = _flaky(tmp_path, "hi", flake_rate=0.4)
    for cycle in range(6):
        lo_marks = lo.tasks(cycle)[0].context["flaky_tests"]
        hi_marks = hi.tasks(cycle)[0].context["flaky_tests"]
        assert lo_marks <= hi_marks


def test_rate_one_reports_zero_passes_after_any_patch(tmp_path):
    """At rate 1.0 every passing test reports fail, so reported delta is
    true delta minus the full after-pass count: hand-computable."""
    env = _flaky(tmp_path, "one", flake_rate=1.0)
    tasks = env.tasks(0)
    fix = next(t for t in tasks if "fix patch" in t.prompt)
    app = fix.context["app"]
    tests = (app.parent / "test_app.py").read_text()
    before = len(run_suite_detail(app.read_text(), tests))

    outcome = env.verify(fix, "Yes, it should be applied.")
    after = len(run_suite_detail(app.read_text(), tests))
    assert after == before + 1, "a fix repairs exactly one test"
    assert outcome.delta == (after - before) - after  # = -before
    assert env.true_deltas[0] == 1.0
    assert env.flakes_fired == 1
    assert env.fired_false_bad == 1
    assert env.fired_false_good == 0, "this noise is one-sided by construction"


def test_skipped_patches_are_a_noise_free_harbor(tmp_path):
    env = _flaky(tmp_path, "skip", flake_rate=1.0)
    for task in env.tasks(0):
        outcome = env.verify(task, "")
        assert outcome.delta == 0.0
    assert env.flakes_fired == 0, "no measurement event, nothing to corrupt"
    assert env.distortion == 0.0


def test_accounting_identity_holds(tmp_path):
    env = _flaky(tmp_path, "acct", flake_rate=0.4)
    for cycle in range(4):
        for task in env.tasks(cycle):
            env.verify(task, "Yes, it should be applied.")
    assert sum(env.reported_deltas) == pytest.approx(
        sum(env.true_deltas) + env.distortion
    )


def test_flaky_rate_zero_is_passthrough():
    noisy = run_one(
        arm="survival",
        seed=3,
        cycles=6,
        overrides={"env_family": "testsuite", "flake_rate": 0.0},
    )
    plain = run_one(
        arm="survival", seed=3, cycles=6, overrides={"env_family": "testsuite"}
    )
    for run in (noisy, plain):
        run["metrics"].pop("wall_time_s")
    assert noisy["metrics"] == plain["metrics"]
    assert noisy["per_cycle"] == plain["per_cycle"]


# ---------------------------------------------------------------------------
# Runner integration
# ---------------------------------------------------------------------------


def test_run_one_testsuite_schema_and_check():
    run = run_one(
        arm="survival",
        seed=0,
        cycles=8,
        overrides={"env_family": "testsuite"},
        suite="smoke",
    )
    assert check([run]) == []
    assert "files_per_cycle" not in run["config"], (
        "a StorageEnv knob must not be recorded on a testsuite run"
    )
    assert run["config"]["env_family"] == "testsuite"


def test_run_one_testsuite_is_deterministic_apart_from_wall_time():
    overrides = {"env_family": "testsuite", "flake_rate": 0.2}
    a = run_one(arm="survival", seed=3, cycles=6, overrides=overrides)
    b = run_one(arm="survival", seed=3, cycles=6, overrides=overrides)
    a["metrics"].pop("wall_time_s")
    b["metrics"].pop("wall_time_s")
    assert a["metrics"] == b["metrics"]
    assert a["per_cycle_true_delta"] == b["per_cycle_true_delta"]


def test_testsuite_noisy_metrics_score_true_deltas():
    run = run_one(
        arm="survival",
        seed=0,
        cycles=6,
        overrides={"env_family": "testsuite", "flake_rate": 0.3},
    )
    assert sum(run["per_cycle_true_delta"]) == run["metrics"]["cum_delta"]
    reported = sum(c["resource_delta"] for c in run["per_cycle"])
    assert reported == run["metrics"]["reported_cum_delta"]
    assert run["metrics"]["fired_false_good"] == 0


def test_testsuite_keep_everything_true_deltas_are_noise_invariant():
    cums = set()
    for rate in (0.0, 0.2, 0.5):
        run = run_one(
            arm="keep_everything",
            seed=1,
            cycles=6,
            overrides={"env_family": "testsuite", "flake_rate": rate},
        )
        cums.add(run["metrics"]["cum_delta"])
    assert len(cums) == 1, f"canary drift: {sorted(cums)}"


def test_testsuite_refuses_storage_noise_models():
    with pytest.raises(ValueError, match="noise_model is a StorageEnv knob"):
        run_one(
            arm="survival",
            seed=0,
            cycles=2,
            overrides={
                "env_family": "testsuite",
                "flake_rate": 0.1,
                "noise_model": "flip",
            },
        )


def test_unknown_env_family_is_refused():
    with pytest.raises(ValueError, match="unknown env_family"):
        run_one(arm="survival", seed=0, cycles=2, overrides={"env_family": "queue"})


def test_random_matched_matches_survival_death_counts_on_testsuite():
    survival = run_one(
        arm="survival", seed=2, cycles=8, overrides={"env_family": "testsuite"}
    )
    matched = run_one(
        arm="random_matched", seed=2, cycles=8, overrides={"env_family": "testsuite"}
    )
    assert [c["deaths"] for c in matched["per_cycle"]] == [
        c["deaths"] for c in survival["per_cycle"]
    ]


# ---------------------------------------------------------------------------
# Suite grids
# ---------------------------------------------------------------------------


def test_testsuite_suite_covers_all_arms():
    from bench.policies import ARMS

    specs = build_headline_grid([0, 1])
    assert len(specs) == len(ARMS) * 2
    assert all(s.overrides["env_family"] == "testsuite" for s in specs)


def test_noisy_grid_is_the_precommitted_one():
    """docs/benchmarks.md states these cells before the results; the
    grid changing silently would rewrite the experiment."""
    assert TESTSUITE_NOISY_RATES == (0.0, 0.05, 0.10, 0.15, 0.20)
    specs = build_noisy_grid([0])
    assert len(specs) == 5 * 7  # rates x variants
    labels = {s.label for s in specs}
    assert "model=none,rate=0.00" in labels
    assert "model=flaky,rate=0.15,k=2" in labels


def _mergeable_pairs(entries: list[tuple[str, str]]) -> list[tuple[int, int, float]]:
    """Pairs a default-threshold consolidator would merge, by Jaccard."""
    import itertools
    import re

    from darwin_memo.consolidate import DEFAULT_MERGE_THRESHOLD

    toks = [set(re.findall(r"[a-z0-9]+", f"{q} {a}".lower())) for q, a in entries]
    out = []
    for i, j in itertools.combinations(range(len(entries)), 2):
        union = toks[i] | toks[j]
        score = len(toks[i] & toks[j]) / len(union) if union else 0.0
        if score >= DEFAULT_MERGE_THRESHOLD:
            out.append((i, j, score))
    return out


def test_the_twin_indices_are_exactly_the_mergeable_entries():
    """``_TWIN_INDICES`` is a hand-written tuple; make it a measurement.

    The lean corpus exists to remove the surplus a consolidator can
    merge, so "which entries are the twins" has to be the answer to
    "which entries can be merged" and not a list someone kept in sync.
    An entry added to the corpus with a near-duplicate, or a twin
    rephrased below the threshold, breaks this instead of quietly
    changing what the counterfactual removes.

    Mutations this catches: dropping an index from ``_TWIN_INDICES``
    (the lean corpus keeps a mergeable pair and stops being lean);
    adding one (the lean corpus loses an entry that was never surplus).
    """
    from bench.testsuite_fixtures import _ENTRIES, _TWIN_INDICES

    pairs = _mergeable_pairs([(q, a) for q, a, _ in _ENTRIES])
    assert len(pairs) == 5, pairs
    # Every mergeable pair is adjacent and contributes exactly one twin.
    assert tuple(sorted(j for _, j, _ in pairs)) == tuple(sorted(_TWIN_INDICES))
    assert all(j == i + 1 for i, j, _ in pairs), "twins are adjacent by construction"

    lean = _mergeable_pairs(
        [(q, a) for i, (q, a, _) in enumerate(_ENTRIES) if i not in _TWIN_INDICES]
    )
    assert lean == [], f"the lean corpus still has surplus to merge: {lean}"


def test_the_storage_corpus_is_less_redundant_but_not_redundancy_free():
    """The contrast the redundancy explanation rests on, measured.

    ``testsuite_fixtures``'s own docstring says the StorageEnv corpus
    "has no redundancy", and the paper explains three test-suite results
    by the difference. It is a difference of degree: the storage corpus
    has two mergeable pairs of sixteen entries, which is the same
    machinery that gave the laundered entry a 59-cycle runway on that
    family (\\S sec:merge-policy). Ten of twenty test-suite entries sit
    in a mergeable pair against four of sixteen -- real, and not the
    zero the prose implied.

    Pinned so the claim cannot drift: a corpus edit that changes either
    count changes an explanation in the paper.
    """
    from bench.fixtures import build_headline_store
    from bench.testsuite_fixtures import _ENTRIES

    storage = _mergeable_pairs(
        [(e.question, e.answer) for e in build_headline_store().alive()]
    )
    testsuite = _mergeable_pairs([(q, a) for q, a, _ in _ENTRIES])
    assert (len(storage), len(testsuite)) == (2, 5)
    assert len(build_headline_store().alive()) == 16 and len(_ENTRIES) == 20


def test_the_lean_corpus_differs_from_the_canonical_one_in_exactly_the_twins():
    """The counterfactual has to be a subtraction and nothing else."""
    from bench.testsuite_fixtures import _TWIN_INDICES, build_testsuite_store

    full = build_testsuite_store()
    lean = build_testsuite_store(twins=False)
    assert len(full.alive()) == 20 and len(lean.alive()) == 15
    dropped = {(e.question, e.answer, tuple(e.sources)) for e in full.alive()} - {
        (e.question, e.answer, tuple(e.sources)) for e in lean.alive()
    }
    assert len(dropped) == len(_TWIN_INDICES)
    # Kept entries are byte-identical, not merely equivalent: the lean
    # store must be the canonical one minus five rows.
    kept = {(e.question, e.answer, tuple(e.sources)) for e in lean.alive()}
    assert kept <= {(e.question, e.answer, tuple(e.sources)) for e in full.alive()}


def test_testsuite_twins_is_refused_where_it_would_be_accepted_and_ignored():
    """The six-place trap again: a knob with no meaning on this family.

    ``testsuite_twins`` selects a TestSuiteEnv corpus, and the storage
    family does not have one. Accepted and ignored there, a redundancy
    sweep over the storage family would produce two identical halves
    that read as "the corpus does not matter" rather than "the knob was
    never connected" -- the exact misreading ``rent_tier`` was guarded
    against.
    """
    import pytest

    from bench.runner import run_one

    for family in ("storage", "storage_rent"):
        overrides: dict[str, object] = {
            "env_family": family,
            "testsuite_twins": False,
        }
        if family == "storage_rent":
            overrides["hold_cost"] = 1.0
        with pytest.raises(ValueError, match="testsuite_twins"):
            run_one("survival", seed=0, cycles=2, overrides=overrides)


def test_the_redundancy_grid_varies_both_halves_of_its_explanation():
    """A 2x2 that is only a 2x1 cannot attribute anything."""
    from bench.testsuite_suites import redundancy_rent_suite, redundancy_suite

    for build, family in (
        (redundancy_suite, "testsuite"),
        (redundancy_rent_suite, "testsuite_rent"),
    ):
        specs = build(list(range(30)))
        assert len(specs) == 1200
        cells = {
            (s.overrides["testsuite_twins"], s.overrides["consolidate_every"])
            for s in specs
        }
        assert cells == {(True, 5), (True, 0), (False, 5), (False, 0)}
        assert {s.cycles for s in specs} == {30, 60}
        assert {s.overrides["env_family"] for s in specs} == {family}
        # Corpus is the outermost axis, so its blocks are contiguous: a
        # reordering leaves every cell correct and rewrites the file.
        twins = [s.overrides["testsuite_twins"] for s in specs]
        assert [t for i, t in enumerate(twins) if i == 0 or t != twins[i - 1]] == [
            True,
            False,
        ]
    # The rented grid must actually price inaction, or it is the plain
    # grid under a second name and attributes nothing.
    assert {s.overrides["hold_cost"] for s in redundancy_rent_suite([0])} == {1.0}
    assert all("hold_cost" not in s.overrides for s in redundancy_suite([0]))
