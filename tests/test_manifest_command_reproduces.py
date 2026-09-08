"""A recorded reproduction command must actually reproduce its run.

``paper/reproduce.md`` points readers at each manifest entry's ``command``. For
the 80 SWE-Bench-CL cells that command was wrong in a way nothing detected:
``manifest_failures`` only checked the field was non-empty, and the stored string
omitted ``--code-context-chars``, ``--base-url`` and ``--model``. All three
default to something else, so running what the manifest said produced a
1,244-character blind prompt against a local llama3.2 -- where the committed
cells were produced with 300,000 characters of BM25 context and ``gpt-4.1``.

This was found by following the instructions: a one-task smoke run issued exactly
the recorded command and came back with a prompt two orders of magnitude too
small. The per-run ``config`` had recorded the truth all along, which is what
makes this checkable rather than merely regrettable.

The check is deliberately narrow: for every config field that changes what the
model sees or which model sees it, the recorded command must name a value that
agrees with the run. It does not try to validate the whole command line.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "bench" / "results"
SWEBENCH_DIRS = ("swebench_cl", "swebench_cl_long", "swebench_cl_adversary")


def _entries() -> list[tuple[str, str, dict[str, Any]]]:
    out = []
    for directory in SWEBENCH_DIRS:
        manifest = RESULTS / directory / "MANIFEST.json"
        if not manifest.exists():
            continue
        for name, entry in json.loads(manifest.read_text())["files"].items():
            out.append((directory, name, entry))
    return sorted(out)


def _flag(command: str, flag: str) -> str | None:
    match = re.search(rf"{re.escape(flag)}\s+(\S+)", command)
    return match.group(1) if match else None


@pytest.mark.parametrize(("directory", "name", "entry"), _entries())
def test_recorded_command_matches_the_run_config(
    directory: str, name: str, entry: dict[str, Any]
) -> None:
    """Mutation: drop ``--code-context-chars`` from a stored command, or change
    its value, and this fires. That is exactly the state all 80 entries were in.
    """
    runs = json.loads((RESULTS / directory / name).read_text())["runs"]
    config = runs[0]["config"]
    command = str(entry.get("command", ""))
    assert command, f"{name} has no reproduction command"

    endpoint = config.get("endpoint", {})
    expected: dict[str, str] = {}
    if "code_context_chars" in config:
        expected["--code-context-chars"] = str(config["code_context_chars"])
    if endpoint.get("model"):
        expected["--model"] = str(endpoint["model"])
    if endpoint.get("base_url"):
        expected["--base-url"] = str(endpoint["base_url"])

    for flag, want in expected.items():
        got = _flag(command, flag)
        assert got is not None, (
            f"{name}: the run recorded {flag.lstrip('-').replace('-', '_')}"
            f"={want}, but the reproduction command never passes {flag}. Running "
            "it would reproduce the default instead of this run."
        )
        assert got == want, f"{name}: command says {flag} {got}, run recorded {want}"


@pytest.mark.parametrize(("directory", "name", "entry"), _entries())
def test_retrieval_file_count_is_recorded_when_retrieval_ran(
    directory: str, name: str, entry: dict[str, Any]
) -> None:
    """``--code-max-files`` is invisible in the run config as a *setting* -- only
    the resulting file list is stored -- so the command is the only place it can
    live. When retrieval ran, the count has to be there and has to be at least
    the number of files the run actually retrieved.

    Stated as a floor rather than an equality on purpose: the retriever returns
    at most ``max_files`` and can return fewer when the character budget binds
    first, which the paper reports ("the budget rather than the file count is
    what binds at the low end").
    """
    runs = json.loads((RESULTS / directory / name).read_text())["runs"]
    config = runs[0]["config"]
    if not config.get("code_context_chars"):
        pytest.skip("retrieval did not run for this cell")
    command = str(entry.get("command", ""))
    recorded = _flag(command, "--code-max-files")
    assert recorded is not None, f"{name}: retrieval ran but no --code-max-files"
    retrieved = max(len(r["config"].get("retrieved_files") or []) for r in runs)
    assert int(recorded) >= retrieved, (
        f"{name}: command allows {recorded} files but a task retrieved "
        f"{retrieved}; the command could not have produced this run"
    )


def test_docker_executor_preflights_the_harness() -> None:
    """A missing or incompatible ``swebench`` must fail loudly, not silently.

    The empty-patch branch of ``DockerExecutor.evaluate`` returns without
    touching the harness, and roughly forty percent of SWE-Bench tasks produce
    no patch -- so a whole run can complete, writing plausible result rows, with
    no harness installed at all. That happened: a one-task smoke run drew an
    empty-patch task, looked healthy, and the missing dependency only surfaced
    when a later task produced a real patch.

    Mutation: delete ``preflight``'s call site in ``evaluate`` and this fires.
    An injected ``runner_fn`` is exempt, because such a test supplies its own
    harness and there is nothing to import.
    """
    import inspect

    from bench.swebench_cl.executor import DockerExecutor

    source = inspect.getsource(DockerExecutor.evaluate)
    assert "self.preflight()" in source, (
        "DockerExecutor.evaluate no longer preflights the harness; a missing "
        "swebench would then be masked by every empty-patch task"
    )

    # And the preflight itself has to be able to fail.
    import sys
    from unittest import mock

    executor = DockerExecutor()
    with mock.patch.object(
        sys.modules["importlib.util"], "find_spec", return_value=None
    ):
        try:
            executor.preflight()
        except RuntimeError as exc:
            assert "swebench" in str(exc)
        else:  # pragma: no cover - the guard did nothing
            raise AssertionError("preflight accepted a missing harness")


def test_docker_empty_patch_note_says_the_harness_did_not_run() -> None:
    """``eval_executed`` stays True on that branch because the settled delta is
    0.0 either way, so the note is the only place a reader learns no tests ran.
    It used to say "evaluated as base behavior", which reads as the opposite of
    what happened; the stub executor has always said "assumed"."""
    from bench.swebench_cl.dataset import TaskRecord
    from bench.swebench_cl.executor import DockerExecutor

    task = TaskRecord(
        instance_id="x__y-1",
        repo="x/y",
        base_commit="0" * 40,
        problem_statement="p",
        gold_patch="",
        fail_to_pass=["t1"],
        pass_to_pass=["t2"],
        order=0,
    )

    def never_called(
        command: list[str], cwd: Path
    ) -> subprocess.CompletedProcess[str]:  # pragma: no cover
        raise AssertionError("the empty-patch branch must not invoke the harness")

    report = DockerExecutor(runner_fn=never_called).evaluate(task, "   ")
    assert report.empty_patch
    assert "assumed" in report.notes and "harness not called" in report.notes


# ----------------------------------------------------------------------
# The pin asks about the CODE, not about the tool's own output.
# ----------------------------------------------------------------------


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _tiny_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "bench" / "results").mkdir(parents=True)
    (repo / "bench" / "runner.py").write_text("# the code\n")
    (repo / "bench" / "results" / "suite.json").write_text('{"runs": []}\n')
    (repo / "bench" / "results" / "MANIFEST.json").write_text("{}\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "you@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "initial")
    return repo


def test_a_rewritten_results_file_does_not_make_the_pin_dirty(tmp_path):
    """Re-running a suite always rewrites its own output -- metrics are
    byte-identical but wall_time_s is not -- so before this the tool saw
    its own write and pinned every result "-dirty", and re-running could
    never produce a clean pin.
    """
    from bench.manifest import _git_commit

    repo = _tiny_repo(tmp_path)
    results = repo / "bench" / "results" / "suite.json"
    manifest = repo / "bench" / "results" / "MANIFEST.json"

    assert not _git_commit(results.parent, (results, manifest)).endswith("-dirty")

    results.write_text('{"runs": [], "wall_time_s": 0.2}\n')
    manifest.write_text('{"files": {}}\n')
    pin = _git_commit(results.parent, (results, manifest))
    assert not pin.endswith("-dirty"), (
        "the tool's own output must not count as a dirty tree; that is the "
        f"whole point of the exclusion, got {pin}"
    )


def test_a_modified_source_file_still_makes_the_pin_dirty(tmp_path):
    """The other half, and the one that matters: the exclusion must not
    become "never dirty". A pin that cannot go dirty records nothing.
    """
    from bench.manifest import _git_commit

    repo = _tiny_repo(tmp_path)
    results = repo / "bench" / "results" / "suite.json"
    manifest = repo / "bench" / "results" / "MANIFEST.json"

    (repo / "bench" / "runner.py").write_text("# the code, changed\n")
    pin = _git_commit(results.parent, (results, manifest))
    assert pin.endswith("-dirty"), (
        "uncommitted code produced these runs and the pin must say so"
    )


def test_an_untracked_file_anywhere_else_still_makes_the_pin_dirty(tmp_path):
    from bench.manifest import _git_commit

    repo = _tiny_repo(tmp_path)
    results = repo / "bench" / "results" / "suite.json"
    manifest = repo / "bench" / "results" / "MANIFEST.json"

    (repo / "bench" / "scratch.py").write_text("# not committed\n")
    assert _git_commit(results.parent, (results, manifest)).endswith("-dirty")
