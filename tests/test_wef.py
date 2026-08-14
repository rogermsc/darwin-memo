"""Unit tests for the two load-bearing pieces of the W/E/F suite, offline.

Both are places where a silent mistake moves every LLM-mode number
without failing anything: the reader that decides an answer requested an
action, and the bucketing that decides which cycle a measured loss is
charged to. The suite itself is sampled and needs a real model; these do
not.
"""

from __future__ import annotations

from typing import Any

from bench.wef import LlmReadingEnv, _adopted_cycles, reads_as_action
from darwin_memo import decision_polarity


class RecordingEnv:
    """Records what dialect the wrapper handed down, and acts on it."""

    resource_scale = 1.0

    def __init__(self) -> None:
        self.seen: list[str] = []

    def tasks(self, cycle: int) -> list[str]:
        return [f"task-{cycle}"]

    def verify(self, task: Any, answer_text: str) -> float:
        self.seen.append(answer_text)
        return -1.0 if decision_polarity(answer_text) is True else 0.0

    def cleanup(self) -> None:
        pass


def test_llm_phrasing_reads_as_action_and_reaches_the_env():
    """The gap the suite exists to close: the bare reader hears silence."""
    answer = "Deleting store-1.db under data/ is safe."
    assert decision_polarity(answer) is not True
    assert reads_as_action(answer) is True

    env = LlmReadingEnv(RecordingEnv())
    assert env.verify("task", answer) == -1.0
    # Translated into the base env's own vocabulary, not passed through.
    assert env.base.seen == ["safe to delete"]
    assert env.missed_by_bare_reader == 1


def test_silence_stays_silence_and_is_not_counted_as_a_miss():
    env = LlmReadingEnv(RecordingEnv())
    assert env.verify("task", "I cannot determine that from the sources.") == 0.0
    assert env.base.seen == [""]
    assert env.missed_by_bare_reader == 0


def test_phrasing_the_bare_reader_already_hears_is_not_a_miss():
    env = LlmReadingEnv(RecordingEnv())
    env.verify("task", "The file is redundant and safe to delete.")
    assert env.missed_by_bare_reader == 0


def check(adopted: bool) -> dict[str, Any]:
    return {"e2_adoption": adopted}


def test_adopted_cycles_buckets_answers_in_task_order():
    """Six answers over three cycles: two per cycle, in arrival order."""
    checks = [
        check(False),
        check(True),
        check(False),
        check(False),
        check(False),
        check(False),
    ]
    assert _adopted_cycles(checks, 3) == {0: True, 1: False, 2: False}


def test_uneven_tail_is_charged_to_the_cycles_it_covered():
    """A run cut short must not index past the end of the delta list."""
    checks = [check(False), check(False), check(True)]
    adopted = _adopted_cycles(checks, 2)
    assert set(adopted) <= {0, 1}
    assert adopted[1] is True


def test_no_answers_or_no_cycles_yields_nothing_to_charge():
    assert _adopted_cycles([], 5) == {}
    assert _adopted_cycles([check(True)], 0) == {}
