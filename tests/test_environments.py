"""The environment surface a third party has to understand to adopt this.

``darwin_memo/environments.py`` is what `docs/custom-environments.md` sends
people to read, and it had no test file of its own: it was exercised only
sideways, through the benchmark and survival suites. ``VerifiableQAEnv`` in
particular is exported in ``__all__`` and documented in ``docs/api.md`` with
zero test references anywhere in the repository.

These pin the behaviours that page promises, because a tutorial describing
behaviour nothing enforces is the failure mode this repo keeps finding.
"""

from __future__ import annotations

import pytest

from darwin_memo import Task, VerifiableQAEnv
from darwin_memo.environments import cycle_rng, decision_polarity

QA = [
    ("Which port does the exporter bind?", "9187"),
    ("Who owns the billing schema?", "payments team"),
    ("What rotates the signing key?", "keyrotator"),
    ("Where do audit logs land?", "s3://audit-eu"),
    ("What is the retention window?", "90 days"),
]


# ---------------------------------------------------------------------------
# VerifiableQAEnv: exported, documented, and until now untested
# ---------------------------------------------------------------------------


def test_verifiable_qa_env_measures_containment_not_quality() -> None:
    env = VerifiableQAEnv(QA)
    task = Task(prompt="Which port?", context={"expected": "9187"})
    assert env.verify(task, "The exporter binds 9187.").delta == 1.0
    assert env.verify(task, "It binds 9188.").delta == -0.5
    # Containment is case-insensitive and does not care how good the prose is.
    task = Task(prompt="Owner?", context={"expected": "Payments Team"})
    assert env.verify(task, "owned by the payments team").delta == 1.0


def test_verifiable_qa_env_tasks_are_deterministic_per_cycle() -> None:
    a = VerifiableQAEnv(QA, per_cycle=3, seed=7)
    b = VerifiableQAEnv(QA, per_cycle=3, seed=7)
    assert [t.prompt for t in a.tasks(2)] == [t.prompt for t in b.tasks(2)]
    assert all("expected" in t.context for t in a.tasks(2))
    assert len(a.tasks(0)) == 3


def test_verifiable_qa_env_never_asks_for_more_pairs_than_it_has() -> None:
    env = VerifiableQAEnv(QA[:2], per_cycle=10)
    assert len(env.tasks(0)) == 2


# ---------------------------------------------------------------------------
# cycle_rng: the reason adjacent seeds are not shifted windows
# ---------------------------------------------------------------------------


def test_cycle_rng_seeds_are_independent_not_shifted() -> None:
    """Mutation: go back to ``random.Random(seed + cycle)`` and this fails.

    Under that scheme seed 3 at cycle 5 IS seed 4 at cycle 4, so a sweep of
    "ten seeds" is ten overlapping draws and across-seed spread reads smoother
    than it should. The hashed triple is what makes the benchmark's seeds
    independent, which every confidence interval in the paper depends on.
    """
    assert cycle_rng(3, 5).random() != cycle_rng(4, 4).random()
    assert cycle_rng(1, 1).random() == cycle_rng(1, 1).random()
    # Streams keep two draws in the same world from colliding.
    assert cycle_rng(1, 1, "tasks").random() != cycle_rng(1, 1, "corpus").random()


# ---------------------------------------------------------------------------
# decision_polarity: the trap docs/custom-environments.md leads with
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("It is safe to delete this file.", True),
        ("This must be retained for compliance.", False),
        ("", None),
        ("The sky is blue.", None),
        # Negative wins over positive: the safe reading of an irreversible act.
        ("Safe to delete, but it must be retained.", False),
        # Positive markers are negation-guarded.
        ("It is not safe to delete this.", False),
    ],
)
def test_decision_polarity_defaults(text: str, expected: bool | None) -> None:
    assert decision_polarity(text) is expected


def test_a_new_verb_reads_as_silence_until_you_pass_markers() -> None:
    """The starvation cliff, in one assertion.

    A verb outside delete/remove and apply/keep returns None on every answer,
    so nothing acts, nothing earns, and the population dies around cycle 20
    with no error raised anywhere. This is the first thing to check when a new
    environment degenerates, and the reason ``extra_positive`` exists.
    """
    answer = "The paymentsly plan is safe to cancel."
    assert decision_polarity(answer) is None
    assert decision_polarity(answer, extra_positive=("safe to cancel",)) is True
    assert (
        decision_polarity(
            answer,
            extra_positive=("safe to cancel",),
            extra_negative=("paymentsly",),
        )
        is False
    )
