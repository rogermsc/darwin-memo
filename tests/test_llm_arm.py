"""Unit tests for the LLM-mode benchmark arm, offline.

Everything network-shaped is faked: a scripted client stands in for
the model, and ``build_audited_protocol``'s OllamaClient is
monkeypatched where construction itself is under test. The real arm
(sampled, opt-in, never CI) is exercised by bench --suite llm.
"""

import json
from collections import Counter

import bench.llm_arm as llm_arm
import bench.run as bench_run
from bench.llm_arm import (
    AuditedProtocol,
    build_audited_protocol,
    citation_metrics,
    write_transcript,
)
from bench.report import aggregate, paired
from bench.run import _execute_llm
from bench.suites import LLM_CYCLES, LLM_FILES_PER_CYCLE, RunSpec, llm_suite
from darwin_memo import MemoryEntry, MemoryStore


class ScriptedClient:
    """Returns canned completions in order."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)

    def complete(self, prompt: str, system: str = "") -> str:
        return self.responses.pop(0)


def seeded_store() -> MemoryStore:
    store = MemoryStore()
    store.add(
        MemoryEntry(
            question="What about database files?",
            answer="Database files must be retained.",
        )
    )
    return store


def test_audited_protocol_classifies_each_answer():
    protocol = AuditedProtocol(
        seeded_store(),
        ScriptedClient(
            [
                "database policy",
                "Databases must be retained.\nSOURCES: [1]",
                "database policy",
                "Delete it, probably fine.",  # no SOURCES line: fallback
            ]
        ),
    )
    protocol.answer("database policy?")
    protocol.answer("can I delete the database?")

    assert len(protocol.answers) == 2
    first, second = (a["classification"] for a in protocol.answers)
    assert first["cited"] is True and first["fallback"] is False
    assert second["cited"] is False and second["fallback"] is True
    assert second["refused"] is False
    # The raw completions behind each answer travel with the record.
    assert "SOURCES: [1]" in protocol.answers[0]["calls"][-1]["raw"]


def test_audited_protocol_records_refusals():
    protocol = AuditedProtocol(
        seeded_store(),
        ScriptedClient(["database policy", "Delete it, probably fine."]),
        refuse_unparseable=True,
    )
    answer = protocol.answer("can I delete the database?")
    assert answer.refused is True and answer.text == ""
    record = protocol.answers[0]["classification"]
    assert record["refused"] is True
    assert record["fallback"] is False, "refusal carries no provenance"
    assert record["unattributed_action"] is False, "silence is not an action"


def test_citation_metrics_rates():
    protocol = AuditedProtocol(
        seeded_store(),
        ScriptedClient(
            [
                "database policy",
                "Keep it.\nSOURCES: [1]",
                "database policy",
                "Memory does not say.\nSOURCES: none",
            ]
        ),
    )
    protocol.answer("database policy?")
    protocol.answer("database policy?")
    metrics = citation_metrics(protocol.answers)
    assert metrics["llm_queries"] == 2
    assert metrics["citation_cited_rate"] == 0.5
    assert metrics["citation_explicit_none_rate"] == 0.5
    assert metrics["citation_refused_rate"] == 0.0


def test_citation_metrics_empty_is_all_zero():
    metrics = citation_metrics([])
    assert metrics["llm_queries"] == 0
    assert metrics["citation_cited_rate"] == 0.0


def test_build_audited_protocol_reads_overrides(monkeypatch):
    built: dict[str, object] = {}

    class FakeOllamaClient:
        def __init__(self, **kwargs: object) -> None:
            built.update(kwargs)

    monkeypatch.setattr(llm_arm, "OllamaClient", FakeOllamaClient)
    protocol = build_audited_protocol(
        seeded_store(),
        {
            "llm_model": "qwen3:4b",
            "llm_refuse_unparseable": True,
            "llm_think": False,
            "llm_max_tokens": 512,
        },
    )
    assert built["model"] == "qwen3:4b"
    assert built["think"] is False
    assert built["max_tokens"] == 512
    assert protocol.refuse_unparseable is True


def test_build_audited_protocol_omits_think_by_default(monkeypatch):
    built: dict[str, object] = {}

    class FakeOllamaClient:
        def __init__(self, **kwargs: object) -> None:
            built.update(kwargs)

    monkeypatch.setattr(llm_arm, "OllamaClient", FakeOllamaClient)
    build_audited_protocol(seeded_store(), {"llm_model": "llama3.2:3b"})
    assert built["think"] is None, "absent override must not send the field"


def test_write_transcript_shape(tmp_path):
    protocol = AuditedProtocol(
        seeded_store(),
        ScriptedClient(
            [
                "database policy",
                "Keep.\nSOURCES: [1]",
                "database policy",
                "Keep.\nSOURCES: [1]",
            ]
        ),
    )
    protocol.answer("database policy?")
    protocol.answer("database policy?")
    path = tmp_path / "t" / "run.jsonl"
    write_transcript(path, protocol.answers, header={"seed": 0}, files_per_cycle=2)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert lines[0] == {"transcript_of": {"seed": 0}}
    assert [r["cycle"] for r in lines[1:]] == [0, 0]
    assert lines[1]["classification"]["cited"] is True
    assert lines[1]["calls"], "raw completions are the committed evidence"


def test_llm_suite_grid_covers_models_mitigation_and_controls():
    specs = llm_suite([0, 1], ["llama3.2:3b", "qwen3:4b"])
    # 2 models x refuse off/on x 2 seeds, plus 2 controls x 2 models x 2
    # seeds. Without the controls the suite has one arm and no baseline,
    # so no number in it is a claim about the ledger.
    assert len(specs) == 16
    arms = Counter(s.arm for s in specs)
    assert arms == {
        "survival_llm": 8,
        "keep_everything_llm": 4,
        "evict_on_negative_llm": 4,
    }
    labels = {s.label for s in specs}
    assert "model=llama3.2:3b,refuse=off" in labels
    assert "model=qwen3:4b,refuse=on" in labels
    # The mitigation is swept for the ledger only; it is not what the
    # controls are there to answer.
    assert {s.label for s in specs if s.arm != "survival_llm"} == {
        "model=llama3.2:3b,refuse=off",
        "model=qwen3:4b,refuse=off",
    }
    for spec in specs:
        assert spec.cycles == LLM_CYCLES
        assert spec.files_per_cycle == LLM_FILES_PER_CYCLE
        if spec.overrides["llm_model"].startswith("qwen3"):
            assert spec.overrides["llm_think"] is False
        else:
            assert "llm_think" not in spec.overrides
        assert spec.overrides["llm_refuse_unparseable"] is ("refuse=on" in spec.label)


def _fake_run(spec: RunSpec, wall: float = 1.0) -> dict[str, object]:
    return {
        "arm": spec.arm,
        "seed": spec.seed,
        "metrics": {"wall_time_s": wall},
    }


def test_execute_llm_checkpoints_and_resumes(monkeypatch, tmp_path):
    calls: list[int] = []

    def fake_run_one(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs["seed"])  # type: ignore[arg-type]
        return {
            "arm": kwargs["arm"],
            "seed": kwargs["seed"],
            "metrics": {"wall_time_s": 1.0},
        }

    monkeypatch.setattr(bench_run, "run_one", fake_run_one)
    out = tmp_path / "llm.json"
    specs = [
        RunSpec(suite="llm", arm="survival_llm", seed=s, label="model=m,refuse=off")
        for s in (0, 1)
    ]
    first = _execute_llm(specs, out)
    assert calls == [0, 1]
    assert (tmp_path / "runs").exists()

    second = _execute_llm(specs, out)
    assert calls == [0, 1], "completed seeds resume from checkpoints"
    assert [r["seed"] for r in second] == [0, 1]
    assert [r["label"] for r in first] == ["model=m,refuse=off"] * 2


def test_execute_llm_rejects_stale_checkpoint(monkeypatch, tmp_path):
    """A checkpoint whose identity fields disagree with the spec is
    re-run, never silently reused."""
    monkeypatch.setattr(
        bench_run,
        "run_one",
        lambda **kw: {
            "arm": kw["arm"],
            "seed": kw["seed"],
            "metrics": {"wall_time_s": 1.0},
        },
    )
    out = tmp_path / "llm.json"
    spec = RunSpec(suite="llm", arm="survival_llm", seed=0, label="model=m,refuse=off")
    stale = dict(_fake_run(spec))
    stale["label"] = "model=OTHER,refuse=off"
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    (runs_dir / "model-m-refuse-off-seed0.json").write_text(json.dumps(stale))

    runs = _execute_llm([spec], out)
    assert runs[0]["label"] == "model=m,refuse=off"


def _llm_metrics(**rates: float) -> dict[str, object]:
    base: dict[str, object] = {
        "poison_killed": True,
        "poison_kill_cycle": 10,
        "damage_before_kill": -1.0,
        "cum_delta": 1.0,
        "cum_negative_delta": -1.0,
        "tail_delta_mean": 0.5,
        "final_population": 5,
        "wall_time_s": 1.0,
        "reported_cum_delta": 1.0,
        "flakes_marked": 0,
        "flakes_fired": 0,
        "fired_false_bad": 0,
        "fired_false_good": 0,
        "probe_harmful_safe_rate": 1.0,
        "probe_benign_correct_rate": 1.0,
        "probe_silence_rate": 0.0,
        "paraphrase_harmful_safe_rate": 1.0,
        "paraphrase_benign_grounded_rate": 0.5,
        "paraphrase_silence_rate": 0.0,
        "llm_queries": 120,
        "citation_cited_rate": 0.5,
        "citation_explicit_none_rate": 0.3,
        "citation_fallback_rate": 0.1,
        "citation_refused_rate": 0.0,
        "citation_unattributed_action_rate": 0.1,
        "citation_sources_line_rate": 0.9,
        "citation_had_think_block_rate": 0.0,
        "citation_actionable_rate": 0.4,
    }
    base.update(rates)
    return base


def _llm_run(seed: int, refuse: str, **rates: float) -> dict[str, object]:
    return {
        "schema_version": 1,
        "suite": "llm",
        "arm": "survival_llm",
        "seed": seed,
        "label": f"model=m,refuse={refuse}",
        "config": {},
        "metrics": _llm_metrics(**rates),
    }


def test_aggregate_surfaces_citation_columns():
    rows = aggregate([_llm_run(0, "off"), _llm_run(1, "off")])
    assert len(rows) == 1
    assert "cited" in rows[0]
    assert "unattr action" in rows[0]
    assert rows[0]["cited"].startswith("0.50")


def test_paired_pairs_refuse_on_off_within_model_cell():
    """ ",refuse=" is the arm's mitigation flag, not the world: on and
    off at the same seed face the same world and must pair."""
    runs = [
        _llm_run(0, "off", cum_delta=10.0),
        _llm_run(1, "off", cum_delta=12.0),
        _llm_run(0, "on", cum_delta=8.0),
        _llm_run(1, "on", cum_delta=13.0),
    ]
    rows = paired(
        runs,
        "survival_llm:model=m,refuse=off",
        "survival_llm:model=m,refuse=on",
    )
    assert len(rows) == 1
    assert rows[0]["seeds"] == "2"
