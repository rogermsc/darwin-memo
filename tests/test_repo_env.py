"""RepoEnv: survival selection against tests passing in real repositories.

Outcomes are replayed from the committed SWE-bench evaluations under
``bench/results/swebench_cl*/`` -- real suites, real repositories, measured in
Docker by a harness nobody here wrote. Nothing in this file grades anything:
every delta is a count of tests gained minus tests lost.
"""

from __future__ import annotations

import pytest

from bench.repo_env import RepoEnv, lesson_entries, load_candidates
from darwin_memo import MemoryStore, SurvivalConfig, SurvivalLoop, Task

CONFIG = SurvivalConfig(cycles=30, merge_threshold=0.9, write_experience=False)


def _run(seed: int, only: str | None = None) -> dict[str, float]:
    env = RepoEnv(seed=seed)
    store = MemoryStore(upkeep=0.05)
    for entry in lesson_entries():
        if only is None or entry.sources[0].endswith(only):
            store.add(entry)
    SurvivalLoop(store, env, config=CONFIG).run()
    return {e.sources[0].removeprefix("repo-lesson:"): e.energy for e in store.alive()}


def test_candidates_load_from_committed_real_repository_evaluations() -> None:
    candidates = load_candidates()
    assert len(candidates) == 423
    assert {c.repo for c in candidates} == {
        "astropy_astropy",
        "django_django",
        "pytest-dev_pytest",
        "sympy_sympy",
    }
    # Every shape the lessons speak about is present in the data.
    assert {c.shape for c in candidates} == {"empty", "small", "large", "failed-edits"}


def test_delta_is_tests_gained_minus_tests_lost() -> None:
    """No weighting to defend: the same arithmetic settle-ci does on real CI."""
    candidates = load_candidates()
    by_id = {c.instance_id: c for c in candidates}
    for c in by_id.values():
        assert c.delta == c.f2p_passed - c.p2p_lost
    # An empty patch cannot gain or break anything, so it is exactly zero.
    assert all(c.delta == 0.0 for c in candidates if c.shape == "empty")


def test_verify_measures_only_when_the_patch_is_shipped() -> None:
    env = RepoEnv(seed=0)
    winner = next(c for c in env.candidates if c.delta > 0)
    task = Task(prompt="?", context={"key": [winner.instance_id, winner.seed]})
    assert env.verify(task, "It is worth shipping.").delta == winner.delta
    assert env.verify(task, "Do not ship it.").delta == 0.0
    assert env.verify(task, "The weather is fine.").delta == 0.0


@pytest.mark.parametrize("seed", range(6))
def test_the_damaging_lesson_dies_on_every_seed(seed: int) -> None:
    """ "A sprawling patch is worth shipping" is where the regressions are.

    Indiscriminate shipping is net-negative in this data (mean -6.7 tests),
    because a handful of catastrophic regressions dominate -- one instance
    broke 1,432 previously-passing tests. The lesson that advises it is
    executed by the repositories it damaged.
    """
    assert "large" not in _run(seed)


def test_the_true_lesson_outlives_it() -> None:
    """Five of six seeds. The sixth is reported, not hidden.

    On seed 2 the narrow lesson dies too, and its own draws summed to +53:
    once the sprawling lesson died at cycle 3 it became the top-ranked entry
    for sprawling candidates and was executed for them. Killing a competitor
    widens the survivor, which is worth knowing and is why this asserts a
    majority rather than all six.
    """
    survived = [seed for seed in range(6) if "small" in _run(seed)]
    assert len(survived) >= 5, f"narrow lesson survived only on {survived}"


def test_the_useless_lesson_only_survives_in_company() -> None:
    """It earns nothing by deciding, and lives on the winner's supporting share.

    Every task it decides has a delta of exactly zero, so deciding pays it
    nothing. It finishes 30 cycles alive anyway, on the 25% supporting credit
    of answers it merely contributed to. Alone in the store, it starves.
    """
    assert "empty" in _run(0)
    assert _run(0, only="empty") == {}
