"""The frozen reproduction package must describe the evidence that exists.

``paper/reproduce.md`` says of its per-file table: "This table is generated
from ``bench/results/MANIFEST.json`` and the manifest is the authority. If the
two ever disagree, the manifest wins and this table is stale." Nothing checked
that, and the two had drifted: three committed result files
(``distill_noisy``, ``distill_rule``, ``neighbours``) were in the manifest, in
CI's validation glob and cited in the docs, while the reproduction package
listed neither them nor their commits. A reader freezing the package would
have shipped an incomplete one.

These tests are the check the prose asserted. They are deliberately about
*correspondence*, not content: they do not care what the numbers are, only
that the document and the manifest describe the same set of files.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "bench" / "results" / "MANIFEST.json"
REPRODUCE = ROOT / "paper" / "reproduce.md"


def manifest_files() -> dict[str, dict[str, Any]]:
    """The per-file entries, tolerating both manifest shapes.

    Older manifests are a bare {name: entry} mapping; the current one wraps
    that under "files" beside a schema version.
    """
    data: dict[str, Any] = json.loads(MANIFEST.read_text())
    files: dict[str, dict[str, Any]] = data.get("files", data)
    return files


def table_rows(doc: str) -> set[str]:
    """Result filenames in the leading column of any markdown table row."""
    return set(re.findall(r"^\|\s*([\w.\-]+\.json)\s*\|", doc, re.M))


def test_reproduce_table_lists_every_manifest_result() -> None:
    """Mutation: add a result file to the manifest without touching
    ``reproduce.md`` and the frozen package silently under-describes the
    evidence. This is how the package came to omit three files that CI was
    validating on every push."""
    listed = table_rows(REPRODUCE.read_text())
    expected = set(manifest_files()) - {"MANIFEST.json"}
    missing = sorted(expected - listed)
    assert not missing, (
        f"in MANIFEST.json but absent from paper/reproduce.md's table: {missing}"
    )


def test_reproduce_table_invents_nothing() -> None:
    """The other direction. Mutation: a file is removed from the manifest (or
    renamed) and the package keeps promising a result nobody can check."""
    listed = table_rows(REPRODUCE.read_text())
    known = set(manifest_files())
    invented = sorted(listed - known)
    assert not invented, (
        f"listed in paper/reproduce.md but absent from MANIFEST.json: {invented}"
    )


def test_reproduce_table_commits_match_the_manifest() -> None:
    """The table's whole purpose is the commit column, so it has to agree.

    Mutation: regenerate a result file (which rewrites its manifest
    ``source_commit``) and leave the table alone; the package then points
    byte-exact reproduction at the wrong tree, which is worse than pointing
    at none.
    """
    doc = REPRODUCE.read_text()
    files = manifest_files()
    mismatched = []
    for row in re.findall(r"^\|\s*([\w.\-]+\.json)\s*\|(.+)$", doc, re.M):
        name, rest = row
        entry = files.get(name)
        if entry is None:
            continue
        commit = str(entry.get("source_commit", ""))
        if commit and commit not in rest:
            mismatched.append((name, commit))
    assert not mismatched, f"table commit differs from manifest: {mismatched}"


@pytest.mark.parametrize("name", sorted(manifest_files()))
def test_manifest_source_commit_is_reachable_or_declared(name: str) -> None:
    """A ``source_commit`` the repository does not contain cannot be checked out.

    ``reproduce.md`` prescribes "checking out each file's manifest
    ``source_commit``" as the byte-exact path. For four files that is
    impossible: the results were generated on a PR branch, the manifest
    recorded the branch commit, and the squash-merge that landed them replaced
    it — so the recorded sha exists nowhere. That is a real limit on the
    package and the document now names it. This test fails when a NEW
    unreachable commit appears, so the list cannot grow silently.

    Skipped when git is unavailable or the checkout is shallow, since neither
    tells us anything about the manifest.
    """
    known_unreachable = {
        "bandit.json",
        "judge-llama.json",
        "judge-qwen.json",
        "llm-qwen.json",
    }
    entry = manifest_files()[name]
    commit = str(entry.get("source_commit", "")).removesuffix("-dirty")
    if not commit:
        pytest.skip("no source_commit recorded")
    try:
        shallow = subprocess.run(
            ["git", "rev-parse", "--is-shallow-repository"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("git unavailable")
    if shallow == "true":
        pytest.skip("shallow checkout cannot answer reachability")
    reachable = (
        subprocess.run(
            ["git", "cat-file", "-e", commit], cwd=ROOT, capture_output=True
        ).returncode
        == 0
    )
    if name in known_unreachable:
        return  # already declared in reproduce.md; not a new regression
    assert reachable, (
        f"{name} records source_commit {commit}, which is not in this "
        "repository. If this came from a squash-merged branch, regenerate the "
        "file on main so the package can point at a commit that exists, or "
        "declare it in paper/reproduce.md alongside the four known cases."
    )
