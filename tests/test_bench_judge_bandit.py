"""Unit tests for the literature control arms: policy_bandit and judge_settled.

The bandit tests are hand-computable: every eviction cycle asserted
below follows from mean + sqrt(ln(T) / (2n)) < 0.5 worked out by hand
in the comments. The judge tests mock the LLM client; nothing here
touches the network, matching the lesson that sampled model output
never runs in CI.
"""

import math

import pytest

import darwin_memo
from bench.judge import (
    JudgeResult,
    judge_prompt,
    parse_verdicts,
    run_judge_settled,
)
from bench.policies import run_policy_bandit
from bench.runner import run_one
from darwin_memo import MemoryEntry, MemoryStore, Outcome, Task

WIDGET_PROMPT = "Is it safe to remove the flaky widget files?"


class NullEnv:
    """No tasks, so arms exercise only their settlement rules."""

    resource_scale = 1.0

    def tasks(self, cycle):
        return []

    def verify(self, task, answer_text):
        raise AssertionError("no tasks to verify")


class _AlwaysBlameEnv(NullEnv):
    def tasks(self, cycle):
        return [Task(prompt=WIDGET_PROMPT, context={})]

    def verify(self, task, answer_text):
        if "safe to remove" in answer_text:
            return Outcome(delta=-5.0, detail="broke")
        return Outcome(delta=0.0, detail="kept")


class _AlternatingEnv(NullEnv):
    """Praises the decider on even cycles, blames it on odd ones."""

    def __init__(self):
        self.cycle = 0

    def tasks(self, cycle):
        self.cycle = cycle
        return [Task(prompt=WIDGET_PROMPT, context={})]

    def verify(self, task, answer_text):
        if self.cycle % 2 == 0:
            return Outcome(delta=5.0, detail="worked")
        return Outcome(delta=-5.0, detail="broke")


class _SoursAfterFirstCycleEnv(_AlternatingEnv):
    """One praised cycle, then blame forever."""

    def verify(self, task, answer_text):
        if self.cycle == 0:
            return Outcome(delta=5.0, detail="worked")
        return Outcome(delta=-5.0, detail="broke")


def _widget_store():
    store = MemoryStore()
    decider = store.add(
        MemoryEntry(
            question="What about the flaky widget files?",
            answer="Flaky widget files are redundant and safe to remove.",
        )
    )
    bystander = store.add(
        MemoryEntry(
            question="What about ledger files?",
            answer="Ledger files must be retained.",
        )
    )
    return store, decider, bystander


# ---------------------------------------------------------------------------
# policy_bandit
# ---------------------------------------------------------------------------


def test_bandit_two_pull_guard_then_eliminates():
    """All-failing decider: guard at T=1, eliminated at n=T=2.

    Cycle 0: one pull, total 1, under the two-pull guard, survives.
    Cycle 1: n=2, mean 0, bound sqrt(ln(2)/4) = 0.4163 < 0.5, culled.
    """
    store, decider, bystander = _widget_store()
    result = run_policy_bandit(store, _AlwaysBlameEnv(), cycles=4)
    assert [r.deaths for r in result.records] == [0, 1, 0, 0]
    assert store.get(decider.id) is None
    assert store.get(bystander.id) is not None


def test_bandit_forgives_the_alternator():
    """Mean 0.5 plus a positive radius never drops below 0.5.

    The same alternator dies under lifetime strikes k=2 at cycle 3;
    the confidence radius is the bandit's forgiveness.
    """
    store, decider, _ = _widget_store()
    result = run_policy_bandit(store, _AlternatingEnv(), cycles=10)
    assert store.get(decider.id) is not None
    assert sum(r.deaths for r in result.records) == 0


def test_bandit_forgiveness_decays_at_the_hand_computed_cycle():
    """One success then failures: culled exactly when 1/n + radius < 0.5.

    With one pull per cycle, n = T = cycle + 1 and one win:
    n=7: 1/7 + sqrt(ln(7)/14) = 0.5157 survives;
    n=8: 1/8 + sqrt(ln(8)/16) = 0.4855 culled, so death lands cycle 7.
    """
    assert 1 / 7 + math.sqrt(math.log(7) / 14) > 0.5
    assert 1 / 8 + math.sqrt(math.log(8) / 16) < 0.5
    store, decider, _ = _widget_store()
    result = run_policy_bandit(store, _SoursAfterFirstCycleEnv(), cycles=9)
    assert [r.deaths for r in result.records] == [0] * 7 + [1, 0]
    assert store.get(decider.id) is None


def test_bandit_never_culls_the_unpulled():
    store, _, bystander = _widget_store()
    run_policy_bandit(store, _AlwaysBlameEnv(), cycles=12)
    assert store.get(bystander.id) is not None, "no pulls, no verdict, immortal"


def test_bandit_run_one_noisy_and_deterministic():
    overrides = {"flake_rate": 0.2, "noise_model": "flip"}
    a = run_one(
        arm="policy_bandit", seed=3, cycles=6, files_per_cycle=6, overrides=overrides
    )
    b = run_one(
        arm="policy_bandit", seed=3, cycles=6, files_per_cycle=6, overrides=overrides
    )
    a["metrics"].pop("wall_time_s")
    b["metrics"].pop("wall_time_s")
    assert a["metrics"] == b["metrics"]
    assert a["per_cycle_true_delta"] == b["per_cycle_true_delta"]


# ---------------------------------------------------------------------------
# judge_settled
# ---------------------------------------------------------------------------


class RecordingJudge:
    """A scripted LLMClient; records prompts, never touches a network."""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.prompts: list[tuple[str, str]] = []

    def complete(self, prompt: str, system: str = "") -> str:
        self.prompts.append((system, prompt))
        return self.replies.pop(0) if self.replies else "[]"


def test_parse_verdicts_filters_shape_id_and_verdict():
    ids = {"aaa", "bbb"}
    text = (
        '[{"id": "aaa", "verdict": "CULL"}, {"id": "bbb", "verdict": "maybe"},'
        ' {"id": "zzz", "verdict": "cull"}, "noise", {"verdict": "keep"}]'
    )
    assert parse_verdicts(text, ids) == {"aaa": "cull"}


def test_parse_verdicts_tolerates_think_blocks_and_fences():
    text = (
        "<think>the [bracketed] reasoning must not parse</think>\n"
        '```json\n[{"id": "aaa", "verdict": "keep"}]\n```'
    )
    assert parse_verdicts(text, {"aaa"}) == {"aaa": "keep"}


def test_judge_cull_verdict_buries_exactly_the_named_entry():
    store, decider, bystander = _widget_store()
    judge = RecordingJudge([f'[{{"id": "{decider.id}", "verdict": "cull"}}]'])
    result = run_judge_settled(store, _AlwaysBlameEnv(), cycles=1, judge=judge)
    assert [r.deaths for r in result.records] == [1]
    assert store.get(decider.id) is None
    assert store.get(bystander.id) is not None
    assert result.judge_calls == 1
    assert result.judge_culls == 1
    assert result.judge_failures == 0


def test_judge_keep_verdict_keeps_and_judge_sees_the_evidence():
    store, decider, _ = _widget_store()
    keep = f'[{{"id": "{decider.id}", "verdict": "keep"}}]'
    judge = RecordingJudge([keep] * 3)
    result = run_judge_settled(store, _AlwaysBlameEnv(), cycles=3, judge=judge)
    assert store.get(decider.id) is not None
    assert result.judge_calls == 3
    _, prompt = judge.prompts[0]
    assert decider.id in prompt
    assert "safe to remove" in prompt, "the lesson answer is shown"
    assert "broke" in prompt, "the outcome description is shown"


def test_judge_unreadable_verdict_defaults_to_keep_and_is_counted():
    store, decider, _ = _widget_store()
    judge = RecordingJudge(["definitely keep this one, it seems fine"])
    result = run_judge_settled(store, _AlwaysBlameEnv(), cycles=1, judge=judge)
    assert store.get(decider.id) is not None
    assert result.judge_failures == 1
    assert result.judge_culls == 0


def test_judge_not_called_without_measured_decisions():
    store, _, _ = _widget_store()

    class ExplodingJudge:
        def complete(self, prompt: str, system: str = "") -> str:
            raise AssertionError("nothing decided, the judge must not be called")

    result = run_judge_settled(store, NullEnv(), cycles=3, judge=ExplodingJudge())
    assert result.judge_calls == 0
    assert [r.deaths for r in result.records] == [0, 0, 0]


def test_judge_prompt_lists_every_candidate_once():
    _store, decider, _ = _widget_store()
    text = judge_prompt([(decider, [("task one", "freed 42 bytes")])])
    assert text.count(f"Entry {decider.id}") == 1
    assert "task one" in text and "freed 42 bytes" in text
    assert '"keep" or "cull"' in text


def test_judge_extra_metrics_shape():
    result = JudgeResult(judge_calls=2, judge_failures=1, judge_culls=3)
    extra = result.extra_metrics
    assert extra["judge_calls"] == 2.0
    assert extra["judge_failures"] == 1.0
    assert extra["judge_culls"] == 3.0
    assert extra["judge_wall_s"] == 0.0


def test_judge_run_one_folds_extra_metrics_without_a_network(monkeypatch):
    """run_one's judge path end to end, the client swapped for a script."""

    def fake_client(**kwargs):
        assert kwargs["model"] == "llama3.2:3b"
        return RecordingJudge()

    monkeypatch.setattr(darwin_memo, "OllamaClient", fake_client)
    run = run_one(arm="judge_settled", seed=0, cycles=3, files_per_cycle=6)
    assert run["metrics"]["judge_calls"] >= 1
    assert run["metrics"]["judge_failures"] >= 1, "an empty array defaults to keep"
    assert run["metrics"]["judge_culls"] == 0
    assert run["metrics"]["cum_delta"] == run["metrics"]["reported_cum_delta"]


def test_judge_refused_under_measurement_noise():
    with pytest.raises(ValueError, match="not defined under measurement noise"):
        run_one(
            arm="judge_settled",
            seed=0,
            cycles=2,
            files_per_cycle=4,
            overrides={"flake_rate": 0.1},
        )
