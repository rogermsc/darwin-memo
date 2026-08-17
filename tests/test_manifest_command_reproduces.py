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
