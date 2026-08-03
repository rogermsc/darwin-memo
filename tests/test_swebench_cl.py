"""Offline tests for the SWE-Bench-CL pilot harness.

No network, no Docker, no model: the endpoint is faked, the executor is
the documented stub, and the dataset is a miniature with the same shape
as the real file. What is under test is the plumbing the pilot relies
on: manifest pinning, arm semantics, the run-JSON schema, the lesson
template, the disk guard, and the wire format of the endpoint client.
"""

import json
import subprocess
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from bench.manifest import manifest_failures, update_manifest
from bench.report import check
from bench.swebench_cl.arms import ARMS
from bench.swebench_cl.dataset import (
    DatasetPin,
    TaskRecord,
    build_manifest,
    file_sha256,
    load_dataset,
    load_manifest,
    sequence_tasks,
)
from bench.swebench_cl.executor import (
    DiskGuardError,
    DockerExecutor,
    StubExecutor,
    check_disk_guard,
    delta_from_eval,
    image_for,
)
from bench.swebench_cl.lessons import mint_lesson, patched_files, sanitize
from bench.swebench_cl.model import (
    ChatEndpoint,
    EndpointConfig,
    extract_patch,
    extract_reflection,
)
from bench.swebench_cl.runner import LessonMemory, run_sequence
from darwin_memo import SurvivalConfig

GOLD_PATCH = (
    "diff --git a/pkg/mod.py b/pkg/mod.py\n"
    "--- a/pkg/mod.py\n"
    "+++ b/pkg/mod.py\n"
    "@@ -1 +1 @@\n"
    "-broken\n"
    "+fixed\n"
)


def make_dataset(n_tasks: int = 3) -> dict[str, Any]:
    tasks = []
    for i in range(1, n_tasks + 1):
        tasks.append(
            {
                "metadata": {
                    "instance_id": f"acme__proj-{i}",
                    "repo": "acme/proj",
                    "base_commit": f"{i:040x}",
                    "created_at": f"2020-01-0{i}T00:00:00+00:00",
                    "difficulty": "<15 min fix",
                },
                "task": {"problem_statement": f"Widget {i} frobnicates wrongly."},
                "evaluation": {
                    "patch": GOLD_PATCH,
                    "test_patch": "diff --git a/tests/t.py b/tests/t.py\n",
                    "FAIL_TO_PASS": [f"test_f2p_{i}_a", f"test_f2p_{i}_b"],
                    "PASS_TO_PASS": [f"test_p2p_{i}"],
                },
                "continual_learning": {
                    "sequence_position": i,
                    "difficulty_score": 1,
                    "dependencies": [],
                    "modified_files": ["pkg/mod.py"],
                },
            }
        )
    return {
        "metadata": {"name": "SWE-Bench-CL", "version": "1.0.0"},
        "sequences": [
            {
                "id": "acme_proj_sequence",
                "repo": "acme/proj",
                "num_tasks": n_tasks,
                "tasks": tasks,
            }
        ],
    }


def make_pin(path: Path) -> DatasetPin:
    return DatasetPin(
        name="test",
        repo="acme/repo",
        commit="0" * 40,
        path="data/test.json",
        sha256=file_sha256(path),
    )


def write_dataset(tmp_path: Path, dataset: dict[str, Any]) -> tuple[Path, DatasetPin]:
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps(dataset))
    return path, make_pin(path)


def make_task(**overrides: Any) -> TaskRecord:
    base: dict[str, Any] = dict(
        instance_id="acme__proj-1",
        order=1,
        repo="acme/proj",
        base_commit="0" * 40,
        problem_statement="Widget frobnicates wrongly.",
        gold_patch=GOLD_PATCH,
        fail_to_pass=["t1", "t2"],
        pass_to_pass=["t3"],
    )
    base.update(overrides)
    return TaskRecord(**base)


class FakeCompleter:
    """Scripted responses, recorded prompts."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete(self, prompt: str, system: str = "") -> str:
        self.calls.append((prompt, system))
        return self.responses[min(len(self.calls), len(self.responses)) - 1]


# ---------------------------------------------------------------------------
# Manifest pinning
# ---------------------------------------------------------------------------


def test_load_dataset_verifies_sha256(tmp_path):
    path, pin = write_dataset(tmp_path, make_dataset())
    assert load_dataset(path, pin)["metadata"]["version"] == "1.0.0"
    path.write_text(path.read_text() + " ")
    with pytest.raises(ValueError, match="sha256"):
        load_dataset(path, pin)


def test_fetch_dataset_deletes_a_hash_failing_download(tmp_path, monkeypatch):
    """The verify-or-raise comment must be true on disk too: a download
    whose hash does not match the pin is removed, not left around to be
    loaded by hand later."""
    from bench.swebench_cl.dataset import fetch_dataset

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return b"not the pinned bytes"

    monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout=0: FakeResponse())
    dest = tmp_path / "dataset.json"
    with pytest.raises(ValueError, match="sha256"):
        fetch_dataset(dest)
    assert not dest.exists()


def test_build_manifest_pins_identity_and_order(tmp_path):
    path, pin = write_dataset(tmp_path, make_dataset(3))
    manifest = build_manifest(load_dataset(path, pin), ("acme_proj_sequence",), pin)
    assert manifest["dataset"]["sha256"] == pin.sha256
    assert manifest["dataset"]["commit"] == pin.commit
    (seq,) = manifest["sequences"]
    assert [t["order"] for t in seq["tasks"]] == [1, 2, 3]
    assert seq["tasks"][0] == {
        "instance_id": "acme__proj-1",
        "order": 1,
        "repo": "acme/proj",
        "base_commit": "1".zfill(40),
    }


def test_build_manifest_rejects_order_gaps(tmp_path):
    dataset = make_dataset(3)
    dataset["sequences"][0]["tasks"][2]["continual_learning"]["sequence_position"] = 5
    with pytest.raises(ValueError, match="contiguous"):
        build_manifest(dataset, ("acme_proj_sequence",))


def test_sequence_tasks_joins_and_detects_drift(tmp_path):
    path, pin = write_dataset(tmp_path, make_dataset(2))
    dataset = load_dataset(path, pin)
    manifest = build_manifest(dataset, ("acme_proj_sequence",), pin)
    tasks = sequence_tasks(manifest, dataset, "acme_proj_sequence")
    assert [t.order for t in tasks] == [1, 2]
    assert tasks[0].fail_to_pass == ["test_f2p_1_a", "test_f2p_1_b"]
    assert tasks[0].gold_patch == GOLD_PATCH
    # A base commit that moved upstream must refuse to run.
    manifest["sequences"][0]["tasks"][0]["base_commit"] = "f" * 40
    with pytest.raises(ValueError, match="base commit"):
        sequence_tasks(manifest, dataset, "acme_proj_sequence")


def test_committed_pilot_manifest_is_internally_consistent():
    path = Path("bench/swebench_cl/manifests/pilot.json")
    manifest = load_manifest(path)
    assert manifest["dataset"]["commit"] == ("74a38a90baace25635f3827ee2f98caff24b3768")
    assert len(manifest["dataset"]["sha256"]) == 64
    ids = [s["id"] for s in manifest["sequences"]]
    assert ids == ["pytest-dev_pytest_sequence", "astropy_astropy_sequence"]
    for seq in manifest["sequences"]:
        assert seq["num_tasks"] == len(seq["tasks"])
        assert [t["order"] for t in seq["tasks"]] == list(
            range(1, seq["num_tasks"] + 1)
        )
        for task in seq["tasks"]:
            assert len(task["base_commit"]) == 40


# ---------------------------------------------------------------------------
# Arms
# ---------------------------------------------------------------------------


def test_exactly_five_arms_with_pinned_semantics():
    """Two axes, pinned so a run cannot improvise an arm into existence.

    The memory axis (what the model sees) and the curation axis (what
    happens to the store afterwards). The curation arms must inject
    EXACTLY what memory_on injects, or a difference between them stops
    being about the curation policy.
    """
    assert set(ARMS) == {
        "memory_on",
        "memory_off",
        "random_matched",
        "keep_everything",
        "evict_on_negative",
    }
    # Memory axis.
    assert ARMS["memory_on"].inject == "retrieved"
    assert ARMS["memory_on"].mint and ARMS["memory_on"].settle
    assert ARMS["memory_on"].curation == "survival"
    assert ARMS["memory_off"].inject == "none"
    assert not ARMS["memory_off"].mint and not ARMS["memory_off"].settle
    assert ARMS["random_matched"].inject == "random_matched"
    assert ARMS["random_matched"].mint and ARMS["random_matched"].settle
    assert ARMS["random_matched"].curation == "survival"
    # Curation axis: retrieval held fixed at what memory_on does.
    assert ARMS["keep_everything"].inject == "retrieved"
    assert ARMS["keep_everything"].curation == "keep_all"
    assert not ARMS["keep_everything"].settle
    assert ARMS["evict_on_negative"].inject == "retrieved"
    assert ARMS["evict_on_negative"].curation == "evict_negative"
    assert ARMS["evict_on_negative"].mint and ARMS["evict_on_negative"].settle


def test_random_matched_spends_at_most_the_retrieval_budget():
    memory = LessonMemory(ARMS["random_matched"], seed=7, config=SurvivalConfig())
    for i in range(6):
        memory.mint(
            f"What is known about widget {i} frobnication in acme?",
            f"Lesson {i}: frobnication of widget {i} needs care " + "pad " * i,
            source=f"t{i}",
            tick=i,
        )
    injection = memory.select("widget frobnication acme", k=3)
    assert injection.budget_tokens > 0
    assert injection.tokens <= injection.budget_tokens
    assert injection.entries  # the budget was actually spent


def test_random_matched_is_seeded_deterministic():
    def run(seed):
        memory = LessonMemory(ARMS["random_matched"], seed, SurvivalConfig())
        for i in range(8):
            memory.mint(f"Q widget {i}?", f"A lesson {i}", source=f"t{i}", tick=i)
        # Entry ids are store-generated uuids, so determinism is judged
        # on which lesson TEXTS the seed selects, not on ids.
        return [e.question for e in memory.select("widget lesson", k=3).entries]

    assert run(3) == run(3)
    assert run(3) != run(4) or len(run(3)) <= 1


def test_memory_off_never_touches_a_store():
    memory = LessonMemory(ARMS["memory_off"], seed=0, config=SurvivalConfig())
    assert memory.select("anything", k=3).entries == []
    assert memory.mint("q", "a", source="s", tick=1) is None
    assert memory.tick(1) == {"deaths": 0, "merges": 0}
    assert len(memory.store) == 0


def test_settle_moves_energy_in_outcome_direction():
    memory = LessonMemory(ARMS["memory_on"], seed=0, config=SurvivalConfig())
    memory.mint(
        "What is known about widget frobnication?", "Lesson", source="t", tick=0
    )
    injection = memory.select("widget frobnication", k=3)
    assert injection.entries
    entry = injection.entries[0]
    before = entry.energy
    assert memory.settle(injection, 1.0, tick=1) == [entry.id]
    assert entry.energy > before
    injection = memory.select("widget frobnication", k=3)
    before = entry.energy
    memory.settle(injection, -1.0, tick=2)
    assert entry.energy < before
    # Zero outcome earns nothing and credits nobody.
    injection = memory.select("widget frobnication", k=3)
    assert memory.settle(injection, 0.0, tick=3) == []


# ---------------------------------------------------------------------------
# Model endpoint and extraction
# ---------------------------------------------------------------------------


def test_chat_endpoint_speaks_openai_wire_format(monkeypatch):
    captured = {}

    class FakeResponse:
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "hello"}}]}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=0):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["payload"] = json.loads(request.data.decode())
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    endpoint = ChatEndpoint(
        EndpointConfig(
            base_url="http://localhost:11434/v1",
            model="llama3.2",
            api_key="sk-test",
            max_tokens=64,
        )
    )
    assert endpoint.complete("prompt text", system="system text") == "hello"
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["payload"]["model"] == "llama3.2"
    assert captured["payload"]["max_tokens"] == 64
    assert captured["payload"]["messages"][0] == {
        "role": "system",
        "content": "system text",
    }
    assert captured["headers"].get("Authorization") == "Bearer sk-test"


def test_chat_endpoint_failures_are_loud(monkeypatch):
    from bench.swebench_cl.model import EndpointError

    def fake_urlopen(request, timeout=0):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    endpoint = ChatEndpoint(EndpointConfig())
    with pytest.raises(EndpointError, match="cannot reach"):
        endpoint.complete("prompt")


def test_chat_endpoint_read_timeout_is_loud(monkeypatch):
    """A timeout during the response read arrives as a bare
    ``TimeoutError`` (connect timeouts come wrapped in URLError); it
    must surface as EndpointError, never escape as something else.

    A read timeout is transient, so it is retried and then reported as
    exhaustion. What this pins is that the cause survives into the
    message: an EndpointError that does not say what went wrong is not
    loud, it is just a different silence.
    """
    from bench.swebench_cl.model import EndpointError

    class StallingResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            raise TimeoutError("The read operation timed out")

    monkeypatch.setattr(
        "urllib.request.urlopen", lambda request, timeout=0: StallingResponse()
    )
    # The retry backoff is real seconds and buys this test nothing.
    monkeypatch.setattr("bench.swebench_cl.model.time.sleep", lambda _: None)
    endpoint = ChatEndpoint(EndpointConfig())
    with pytest.raises(EndpointError, match="timed out") as caught:
        endpoint.complete("prompt")
    assert "attempts" in str(caught.value), "the retry exhaustion must be visible"
    assert isinstance(caught.value.__cause__, TimeoutError)


def test_extract_patch_from_fence_and_bare_and_none():
    fenced = f"Here you go:\n```diff\n{GOLD_PATCH}```\nREFLECTION: tidy fix."
    assert extract_patch(fenced) == GOLD_PATCH.strip()
    assert extract_reflection(fenced) == "tidy fix."
    bare = f"{GOLD_PATCH}\nREFLECTION: bare diff."
    assert extract_patch(bare) == GOLD_PATCH.strip()
    assert extract_patch("I cannot solve this.") == ""
    think = f"<think>maybe [1] ponder</think>```diff\n{GOLD_PATCH}```"
    assert extract_patch(think) == GOLD_PATCH.strip()


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------


def test_stub_executor_paths_and_deltas():
    stub = StubExecutor()
    task = make_task()

    empty = stub.evaluate(task, "")
    assert empty.empty_patch and empty.eval_executed and not empty.resolved
    assert delta_from_eval(empty) == 0.0

    garbage = stub.evaluate(task, "not a diff at all")
    assert not garbage.patch_applied and not garbage.resolved

    plausible = stub.evaluate(task, GOLD_PATCH.replace("fixed", "other"))
    assert plausible.patch_applied and not plausible.resolved
    assert delta_from_eval(plausible) == 0.0

    gold = stub.evaluate(task, GOLD_PATCH)
    assert gold.resolved and gold.f2p_passed == 2
    assert delta_from_eval(gold) == 1.0
    assert gold.mode == "stub"  # a stub verdict is always labeled


def test_delta_penalizes_regressions():
    report = StubExecutor().evaluate(make_task(), GOLD_PATCH)
    report.resolved = False
    report.f2p_passed = 0
    report.p2p_passed = 0  # every pass-to-pass test broke
    assert delta_from_eval(report) == -1.0


def test_image_name_uses_docker_hub_encoding():
    assert (
        image_for("pytest-dev__pytest-5262")
        == "swebench/sweb.eval.x86_64.pytest-dev_1776_pytest-5262"
    )


def test_disk_guard_blocks_when_floor_would_be_crossed():
    with pytest.raises(DiskGuardError, match="refusing to pull"):
        check_disk_guard(
            "swebench/sweb.eval.x86_64.acme_1776_proj-1",
            floor_gb=4.0,
            image_size_fn=lambda image: 1_000_000_000,  # 1 GB compressed
            free_bytes_fn=lambda: 5_600_000_000,  # 5.6 GB free
        )
    # Plenty of disk: no exception.
    check_disk_guard(
        "swebench/sweb.eval.x86_64.acme_1776_proj-1",
        floor_gb=4.0,
        image_size_fn=lambda image: 1_000_000_000,
        free_bytes_fn=lambda: 50_000_000_000,
    )


def test_docker_executor_guards_before_any_subprocess(tmp_path):
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    executor = DockerExecutor(
        floor_gb=4.0,
        workdir=tmp_path,
        image_size_fn=lambda image: 1_000_000_000,
        free_bytes_fn=lambda: 5_600_000_000,
        runner_fn=fake_run,
    )
    with pytest.raises(DiskGuardError):
        executor.evaluate(make_task(), GOLD_PATCH)
    assert calls == []  # nothing ran, nothing was pulled


def test_docker_executor_empty_patch_skips_the_image_entirely(tmp_path):
    executor = DockerExecutor(
        floor_gb=4.0,
        workdir=tmp_path,
        image_size_fn=lambda image: pytest.fail("sized an image for empty patch"),
        free_bytes_fn=lambda: 0,
    )
    report = executor.evaluate(make_task(), "   ")
    assert report.empty_patch and report.eval_executed
    assert delta_from_eval(report) == 0.0


def _docker_executor(workdir, runner_fn):
    return DockerExecutor(
        floor_gb=4.0,
        workdir=workdir,
        image_size_fn=lambda image: 1_000_000_000,
        free_bytes_fn=lambda: 50_000_000_000,
        runner_fn=runner_fn,
    )


def test_docker_executor_prefers_the_per_instance_report(tmp_path):
    """The report-merge leg, offline: a fake harness writes the files
    the real ``swebench.harness.run_evaluation`` leaves behind, and the
    executor must read true per-test outcomes from the per-instance
    report, including a partial result that is not a resolve."""
    task = make_task()

    def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        per_instance = cwd / "logs" / "run_evaluation" / task.instance_id
        per_instance.mkdir(parents=True)
        (per_instance / "report.json").write_text(
            json.dumps(
                {
                    task.instance_id: {
                        "patch_successfully_applied": True,
                        "resolved": False,
                        "tests_status": {
                            "FAIL_TO_PASS": {"success": ["t1"], "failure": ["t2"]},
                            "PASS_TO_PASS": {"success": ["t3"], "failure": []},
                        },
                    }
                }
            )
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    report = _docker_executor(tmp_path, fake_run).evaluate(task, GOLD_PATCH)
    assert report.mode == "docker"
    assert report.env_ready and report.eval_executed
    assert report.patch_applied and not report.resolved
    assert (report.f2p_passed, report.f2p_total) == (1, 2)
    assert (report.p2p_passed, report.p2p_total) == (1, 1)
    assert delta_from_eval(report) == 0.5  # half the gains, no regressions


def test_docker_executor_summary_fallback_settles_at_base_behavior(tmp_path):
    """Without a per-instance report the summary names ids only: an
    error id reads unapplied and settles at exactly 0, never as damage
    no test measured."""
    task = make_task()

    def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        (cwd / "darwin-memo-pilot.report.json").write_text(
            json.dumps(
                {
                    "resolved_ids": [],
                    "error_ids": [task.instance_id],
                    "unstopped_containers": [],
                }
            )
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    report = _docker_executor(tmp_path, fake_run).evaluate(task, GOLD_PATCH)
    assert not report.resolved and not report.patch_applied
    assert report.eval_executed
    assert delta_from_eval(report) == 0.0


def test_docker_executor_summary_unstopped_container_reads_unapplied(tmp_path):
    """swebench 4.1.0 writes ``unstopped_containers`` (container names,
    which embed the instance id), never ``unstopped_ids``; an instance
    left in an unstopped container must read as unapplied."""
    task = make_task()

    def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        (cwd / "darwin-memo-pilot.report.json").write_text(
            json.dumps(
                {
                    "resolved_ids": [],
                    "error_ids": [],
                    "unstopped_containers": [
                        f"sweb.eval.{task.instance_id}.darwin-memo-pilot"
                    ],
                }
            )
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    report = _docker_executor(tmp_path, fake_run).evaluate(task, GOLD_PATCH)
    assert not report.patch_applied
    assert delta_from_eval(report) == 0.0


def test_docker_executor_apply_fail_report_settles_at_base(tmp_path):
    """The grader returns early on apply failure (and on RESET_FAILED,
    TESTS_ERROR, TESTS_TIMEOUT): ``patch_successfully_applied`` false
    and no ``tests_status`` at all. No test measured anything, so the
    report settles at exactly 0, never at invented maximal damage."""
    task = make_task()

    def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        per_instance = cwd / "logs" / "run_evaluation" / task.instance_id
        per_instance.mkdir(parents=True)
        (per_instance / "report.json").write_text(
            json.dumps(
                {
                    task.instance_id: {
                        "patch_is_None": False,
                        "patch_exists": True,
                        "patch_successfully_applied": False,
                        "resolved": False,
                    }
                }
            )
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    report = _docker_executor(tmp_path, fake_run).evaluate(task, GOLD_PATCH)
    assert report.eval_executed and not report.patch_applied
    assert (report.f2p_passed, report.f2p_total) == (0, 2)
    assert (report.p2p_passed, report.p2p_total) == (1, 1)
    assert delta_from_eval(report) == 0.0
    assert "no tests ran" in report.notes


def test_docker_executor_totals_come_from_tests_status(tmp_path):
    """When ``tests_status`` is present its success/failure lists
    partition what actually ran; totals come from it, not from the
    spec lists, so a count drift cannot skew the delta."""
    task = make_task()

    def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        per_instance = cwd / "logs" / "run_evaluation" / task.instance_id
        per_instance.mkdir(parents=True)
        (per_instance / "report.json").write_text(
            json.dumps(
                {
                    task.instance_id: {
                        "patch_successfully_applied": True,
                        "resolved": False,
                        "tests_status": {
                            "FAIL_TO_PASS": {
                                "success": ["t1", "t2", "t3"],
                                "failure": [],
                            },
                            "PASS_TO_PASS": {"success": ["p1"], "failure": ["p2"]},
                        },
                    }
                }
            )
        )
        return subprocess.CompletedProcess(cmd, 0, "", "")

    report = _docker_executor(tmp_path, fake_run).evaluate(task, GOLD_PATCH)
    assert (report.f2p_passed, report.f2p_total) == (3, 3)
    assert (report.p2p_passed, report.p2p_total) == (1, 2)
    assert delta_from_eval(report) == 0.5  # all gains, half the p2p broken


def test_docker_executor_raises_when_harness_leaves_no_report(tmp_path):
    """Exit 0 with no report file at all is an infrastructure failure,
    not a measurement; scoring it would invent a result."""
    task = make_task()

    def fake_run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, "", "")

    with pytest.raises(RuntimeError, match="neither a per-instance report"):
        _docker_executor(tmp_path, fake_run).evaluate(task, GOLD_PATCH)


# ---------------------------------------------------------------------------
# Lesson minting
# ---------------------------------------------------------------------------


def test_mint_lesson_template_is_deterministic_and_outcome_settled():
    task = make_task()
    stub = StubExecutor()
    report = stub.evaluate(task, GOLD_PATCH)
    q1, a1 = mint_lesson(task, GOLD_PATCH, "Use the frobnicator.", report)
    q2, a2 = mint_lesson(task, GOLD_PATCH, "Use the frobnicator.", report)
    assert (q1, a1) == (q2, a2)
    assert "pkg/mod.py" in q1 and "acme/proj" in q1
    assert a1.startswith("Worked: resolved, 2/2")
    assert "Use the frobnicator." in a1

    failed = stub.evaluate(task, "")
    _, answer = mint_lesson(task, "", "", failed)
    assert answer == "Failed: no patch was produced."


def test_mint_lesson_sanitizes_model_text():
    task = make_task()
    report = StubExecutor().evaluate(task, GOLD_PATCH)
    # Unicode escapes keep the banned dash characters out of this
    # file's own source while still exercising the sanitizer on them.
    reflection = "first\u2014second\u2013third\nfourth " + "x" * 400
    _, answer = mint_lesson(task, GOLD_PATCH, reflection, report)
    assert "\u2014" not in answer and "\u2013" not in answer
    assert "first, second, third fourth" in answer
    assert len(sanitize(reflection)) <= 280


def test_patched_files_reads_the_model_patch_not_gold():
    assert patched_files(GOLD_PATCH) == ["pkg/mod.py"]
    assert patched_files("") == []


# ---------------------------------------------------------------------------
# The runner and the run-JSON schema
# ---------------------------------------------------------------------------

RUN_KEYS = {
    "schema_version",
    "suite",
    "arm",
    "seed",
    "sequence",
    "instance_id",
    "order",
    "config",
    "lessons",
    "model",
    "eval",
    "metrics",
    "store",
    "meta",
}


def run_pilot(arm, responses, n_tasks=2):
    tasks = [
        make_task(instance_id=f"acme__proj-{i}", order=i) for i in range(1, n_tasks + 1)
    ]
    completer = FakeCompleter(responses)
    runs = run_sequence(
        tasks,
        sequence_id="acme_proj_sequence",
        arm_name=arm,
        endpoint=EndpointConfig(model="fake"),
        executor=StubExecutor(),
        seed=0,
        completer=completer,
    )
    return runs, completer


def test_run_records_match_the_committed_schema():
    response = f"```diff\n{GOLD_PATCH}```\nREFLECTION: gold."
    runs, _ = run_pilot("memory_on", [response])
    assert len(runs) == 2
    for run in runs:
        assert set(run) == RUN_KEYS
        assert run["suite"] == "swebench_cl_pilot"
        assert run["eval"]["mode"] == "stub"
        assert run["config"]["executor"] == "stub"
        assert isinstance(run["metrics"]["delta"], float)
    assert [r["order"] for r in runs] == [1, 2]
    # Gold patch resolves; the second task sees the first task's lesson.
    assert runs[0]["metrics"]["resolved"] is True
    assert runs[1]["lessons"]["injected"], "lesson from task 1 was not injected"
    assert runs[1]["lessons"]["credited"], "outcome credit did not land"
    assert runs[0]["lessons"]["minted"] is not None
    assert runs[1]["store"]["population"] >= 1


def test_memory_off_runs_inject_and_mint_nothing():
    runs, completer = run_pilot("memory_off", ["no patch from me"])
    for run in runs:
        assert run["lessons"]["injected"] == []
        assert run["lessons"]["minted"] is None
        assert run["store"]["population"] == 0
    assert "Lessons recorded" not in completer.calls[1][0]


def test_memory_on_injects_lessons_into_the_prompt():
    response = f"```diff\n{GOLD_PATCH}```\nREFLECTION: remember the frobnicator."
    _, completer = run_pilot("memory_on", [response])
    assert "Lessons recorded from earlier tasks" in completer.calls[1][0]
    assert "remember the frobnicator." in completer.calls[1][0]


def test_empty_patch_path_flows_through_the_runner():
    runs, _ = run_pilot("memory_on", ["I do not know how to fix this."])
    assert runs[0]["eval"]["empty_patch"] is True
    assert runs[0]["metrics"]["delta"] == 0.0
    assert runs[0]["model"]["patch_chars"] == 0
    # The failure still minted a lesson saying so.
    assert runs[0]["lessons"]["minted"] is not None


def test_run_json_binds_to_the_bench_manifest(tmp_path):
    response = f"```diff\n{GOLD_PATCH}```\nREFLECTION: gold."
    runs, _ = run_pilot("memory_on", [response])
    out = tmp_path / "pilot_smoke.json"
    out.write_text(json.dumps({"runs": runs}, indent=2))
    update_manifest(out, runs, "python -m bench.swebench_cl.run run ...")
    assert manifest_failures(out, runs, require_entry=True) == []


def test_cli_refuses_update_manifest_for_non_docker_runs(tmp_path, capsys):
    """Committed evidence requires real evaluation: --update-manifest
    with the stub executor is refused before anything runs, so a stub
    number can never enter the bench manifest."""
    from bench.swebench_cl.run import main

    rc = main(
        [
            "run",
            "--manifest",
            str(tmp_path / "absent-manifest.json"),
            "--dataset",
            str(tmp_path / "absent-dataset.json"),
            "--sequence",
            "acme_proj_sequence",
            "--arm",
            "memory_on",
            "--executor",
            "stub",
            "--out",
            str(tmp_path / "out.json"),
            "--update-manifest",
        ]
    )
    assert rc == 2
    assert "refusing --update-manifest" in capsys.readouterr().err
    assert not (tmp_path / "out.json").exists()  # refused before running


def make_swebench_run(**overrides: Any) -> dict[str, Any]:
    run = {
        "schema_version": 1,
        "suite": "swebench_cl_pilot",
        "arm": "memory_on",
        "seed": 0,
        "sequence": "pytest-dev_pytest_sequence",
        "instance_id": "pytest-dev__pytest-5262",
        "order": 1,
        "metrics": {"delta": 1.0, "resolved": True, "wall_time_s": 65.8},
    }
    run.update(overrides)
    return run


def test_check_accepts_swebench_records_without_storage_metrics():
    # The pilot records one task, not one population run; asking it for
    # flake counters and paraphrase probes would make its evidence
    # permanently unvalidatable.
    assert check([make_swebench_run()]) == []


def test_check_still_demands_the_full_set_from_storage_suites():
    storage = {
        "schema_version": 1,
        "suite": "storage",
        "arm": "survival",
        "seed": 0,
        "metrics": {"wall_time_s": 1.0},
    }
    failures = check([storage])
    assert any("missing metrics" in f for f in failures)


def test_check_demands_swebench_identity_fields():
    # Without these the curve cannot pair a world or order a curriculum.
    run = make_swebench_run()
    del run["sequence"]
    failures = check([run])
    assert any("missing identity fields" in f and "sequence" in f for f in failures)


def test_check_demands_swebench_wall_time():
    run = make_swebench_run(metrics={"delta": 0.0, "resolved": False, "wall_time_s": 0})
    assert any("wall_time_s" in f for f in check([run]))
