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
REPRODUCE_SH = ROOT / "paper" / "reproduce.sh"


def manifest_files() -> dict[str, dict[str, Any]]:
    """The per-file entries, tolerating both manifest shapes.

    Older manifests are a bare {name: entry} mapping; the current one wraps
    that under "files" beside a schema version.
    """
    data: dict[str, Any] = json.loads(MANIFEST.read_text())
    files: dict[str, dict[str, Any]] = data.get("files", data)
    return files


def all_manifest_entries() -> dict[str, dict[str, Any]]:
    """Every entry in every committed manifest, keyed "<manifest dir>/<file>".

    The root manifest is not the whole of the evidence. Three sibling manifests
    under ``swebench_cl``, ``swebench_cl_long`` and ``swebench_cl_adversary``
    carry the real-task leg -- 80 entries, every docker-evaluated task in the
    paper -- and CI validates those result files by the same glob it uses for
    the root ones. The ``source_commit`` guards, however, were parametrised over
    the root manifest alone, so all 80 went unchecked: **every one of them named
    a pre-squash branch commit absent from published history.** Scope the guard
    to the evidence, not to the file that happens to sit at the top.
    """
    out: dict[str, dict[str, Any]] = {}
    for path in sorted((ROOT / "bench" / "results").glob("**/MANIFEST.json")):
        data: dict[str, Any] = json.loads(path.read_text())
        files: dict[str, dict[str, Any]] = data.get("files", data)
        rel = path.parent.relative_to(ROOT / "bench" / "results")
        for name, entry in files.items():
            out[f"{rel}/{name}" if str(rel) != "." else name] = entry
    return out


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


@pytest.mark.parametrize("name", sorted(all_manifest_entries()))
def test_manifest_source_commit_is_in_published_history(name: str) -> None:
    """The recorded commit has to be one a *reader* can check out.

    ``reproduce.md`` prescribes "checking out each file's manifest
    ``source_commit``" as the byte-exact path, so the question is not whether
    the sha exists somewhere but whether it is in the history this repository
    publishes. Those are very different questions and the difference hid the
    real damage: this test used to ask ``git cat-file -e``, which passes for
    any object in the *local* store -- including pre-squash branch commits that
    survive in the clone of whoever generated the file and nowhere else. On
    that check exactly four entries looked broken and a declared allow-list
    covered them. Asked as ancestry instead, **eighteen of twenty-one** were
    unreachable for a reader: essentially every source_commit in the repo named
    a branch commit that the squash-merge discarded.

    Every entry now names a commit in published history -- the commit that
    landed the file, or for freshly regenerated files the tree they were run
    from -- with a ``source_commit_note`` when that differs from the sha the
    generator originally recorded. So there is nothing left to exempt.

    Ancestry is measured against ``HEAD``, which on a CI pull-request checkout
    is the merge commit and therefore contains the base branch's history.
    """
    entry = all_manifest_entries()[name]
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
    published = (
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, "HEAD"],
            cwd=ROOT,
            capture_output=True,
        ).returncode
        == 0
    )
    assert published, (
        f"{name} records source_commit {commit}, which is not an ancestor of "
        "HEAD. A sha that resolves only in the generating machine's clone is "
        "not a reproduction pointer: record the commit that landed the file, "
        "or regenerate it, and say which in source_commit_note."
    )


@pytest.mark.parametrize("name", sorted(all_manifest_entries()))
def test_manifest_source_commit_could_have_produced_the_file(name: str) -> None:
    """Reachable is not the same as possible, and one entry was only reachable.

    ``adversary.json`` recorded ``41a1399`` — a real commit, six weeks before
    the adversary suite existed and a tree in which ``--suite adversary`` is not
    a choice in ``bench/run.py``. The reachability test above passes it, because
    the sha resolves. A pointer that resolves to a tree that cannot run the
    suite is the worst of the three cases: it reads as verified provenance.

    So check the weakest thing that catches it: the runner named in the entry's
    own ``command`` has to exist at the recorded commit, and where that runner
    is ``bench.run`` its ``--suite`` choices have to include this suite. The
    entry states which module produced it, so nothing has to be guessed.

    The skip below used to also require a ``suite``, which is not what the
    paragraph above says and cost the guard five entries: the external
    manifest names ``bench.external.*`` runners and no suite, so every one of
    its files was discovered and then silently skipped. The runner half needs
    no suite, so only the ``--suite`` half waits for one.
    """
    entry = all_manifest_entries()[name]
    commit = str(entry.get("source_commit", "")).removesuffix("-dirty")
    suite = entry.get("suite")
    command = str(entry.get("command", ""))
    if not commit:
        pytest.skip("no source_commit recorded")
    module = re.search(r"python -m ([\w.]+)", command)
    if module is None:
        pytest.skip("entry names no runner module to check")
    runner = module.group(1).replace(".", "/") + ".py"
    try:
        shown = subprocess.run(
            ["git", "show", f"{commit}:{runner}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
    except OSError:  # pragma: no cover - git absent
        pytest.skip("git unavailable")
    assert shown.returncode == 0, (
        f"{name} records source_commit {commit}, which has no {runner} — the "
        f"runner its own command names. That tree cannot have produced this "
        "file."
    )
    if module.group(1) != "bench.run" or not isinstance(suite, str):
        # Its own module (bench.swebench_cl.run, bench.potentiation,
        # bench.external.*); existence is all this check can assert without
        # hardcoding each CLI's shape. Same when the entry names no single
        # suite: the runner check above still ran, which is the half that
        # catches a pointer to a tree that could not have produced the file.
        return
    assert f'"{suite}"' in shown.stdout or f"'{suite}'" in shown.stdout, (
        f"{name} records source_commit {commit}, whose bench/run.py has no "
        f"{suite!r} suite — that tree cannot have produced this file. "
        "Regenerate on a commit that can run it."
    )


def test_reproduce_script_lists_every_committed_result_file() -> None:
    """``reproduce.sh`` says "Every committed result file, not a subset".

    That sentence is the whole contract of step 3: the offline verification
    only binds the files it names, so a result file left out of the array is
    a file whose manifest entry nothing checks. The comment above the array
    already records this drifting once -- an earlier version omitted the two
    distillation arms, which happened to be exactly the files ``--check``
    could not validate, so the coverage had been shaped around what passed.

    It then drifted again, by six files: neighbours, persistence, the two
    later distillation arms, and all three withholding grids landed without
    being added. A sentence asserting its own completeness is an unenforced
    invariant, so this is that sentence, enforced. Sub-directory matrices
    (``swebench_cl*``) are excluded because they carry their own sibling
    manifests and step 3 verifies them separately.
    """
    listed = re.search(r"RESULTS=\(\n(.*?)\n\)", REPRODUCE_SH.read_text(), re.S)
    assert listed, "the RESULTS array has been renamed or reshaped"
    named = set(listed.group(1).split())
    committed = {
        path.name
        for path in (ROOT / "bench" / "results").glob("*.json")
        if path.name != "MANIFEST.json"
    }
    assert named == committed, (
        f"reproduce.sh does not verify {sorted(committed - named)}; "
        f"it names {sorted(named - committed)} which is not committed"
    )
