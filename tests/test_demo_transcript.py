"""The demo transcript printed in the docs must be the one the demo prints.

`tests/test_docs_links.py` deliberately does not execute README fences, so
until this file existed nothing tied the headline demo block to the headline
demo. It drifted: the README claimed a cycle-0 population of 17 and put the
"poison being executed" marker on cycle 1, when the run executes the poison at
cycle 0 and starts at 16.

The demo is seeded (`environments.cycle_rng`) and takes about a quarter of a
second, so pinning it costs nothing and catches the drift the moment it starts.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Every doc that prints the demo's cycle table.
TRANSCRIPT_DOCS = (
    ROOT / "README.md",
    ROOT / "docs" / "launch-post.md",
)

HEADER = "cycle  pop births deaths merges   energy   resource Δ   silent"

# "    0   16      1      1      0    15.91      -495616     0/12" plus an
# optional "   <- annotation" tail that is ours, not the program's.
ROW = re.compile(
    r"^\s*(?P<data>\d+(?:\s+-?\d+){4}\s+-?[\d.]+\s+-?\d+\s+\d+/\d+)"
    r"(?:\s+<-\s.*)?$"
)


@pytest.fixture(scope="module")
def demo_output() -> str:
    """One real `darwin-memo demo` run, shared by every assertion."""
    result = subprocess.run(
        [sys.executable, "-m", "darwin_memo", "demo"],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=ROOT,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def _transcript_block(doc: Path) -> list[str]:
    """The fenced block holding the cycle table, as lines.

    Walks the file tracking fence state rather than regexing pairs: a naive
    ```...``` pattern happily pairs one block's closing fence with the next
    block's opening one, which is how the first version of this test failed
    for the wrong reason.
    """
    text = doc.read_text(encoding="utf-8")
    assert HEADER in text, f"{doc.name} no longer contains the demo table header"
    block: list[str] = []
    inside = False
    for line in text.splitlines():
        if line.startswith("```"):
            if inside and any(HEADER in row for row in block):
                return block
            inside = not inside
            block = []
            continue
        if inside:
            block.append(line)
    raise AssertionError(f"{doc.name}: demo table header is not inside a fence")


@pytest.mark.parametrize("doc", TRANSCRIPT_DOCS, ids=lambda p: p.name)
def test_documented_cycle_rows_are_real(doc: Path, demo_output: str) -> None:
    """Every cycle row printed in the docs appears verbatim in a real run."""
    rows = [
        match.group("data").strip()
        for line in _transcript_block(doc)
        if (match := ROW.match(line))
    ]
    assert rows, f"{doc.name}: no cycle rows found in the demo fence"

    # Normalise runs of whitespace so a doc may not silently re-space a row.
    actual = {" ".join(line.split()) for line in demo_output.splitlines()}
    stale = [row for row in rows if " ".join(row.split()) not in actual]
    assert not stale, (
        f"{doc.name} prints {len(stale)} cycle row(s) the demo does not produce:\n  "
        + "\n  ".join(stale)
        + "\n\nRe-run `darwin-memo demo` and copy the real rows."
    )


@pytest.mark.parametrize("doc", TRANSCRIPT_DOCS, ids=lambda p: p.name)
def test_poison_annotation_marks_the_cycle_that_pays(
    doc: Path, demo_output: str
) -> None:
    """The "<- poison being executed" marker sits on a negative-delta cycle.

    The marker is the one claim in the block a reader checks by eye, and it was
    wrong: it pointed at cycle 1, which is delta-positive.
    """
    marked = [
        line for line in _transcript_block(doc) if "poison being executed" in line
    ]
    assert len(marked) == 1, f"{doc.name}: expected exactly one poison marker"
    delta = int(marked[0].split("<-")[0].split()[6])
    assert delta < 0, (
        f"{doc.name}: the poison marker sits on a cycle with delta {delta}. "
        "The environment charges for the poison on the cycle it is executed, "
        "so the marker belongs on a negative row."
    )


@pytest.mark.parametrize("doc", TRANSCRIPT_DOCS, ids=lambda p: p.name)
def test_documented_poison_verdict_is_real(doc: Path, demo_output: str) -> None:
    """The headline claim -- no poison survives -- is what the demo reports."""
    verdict = "Poisoned entries still alive: 0"
    assert verdict in demo_output, "the demo no longer reports a clean sweep"
    assert verdict in "\n".join(_transcript_block(doc))
