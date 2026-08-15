"""The paper must build with no dangling cross-references.

A ``\\ref`` to a label that does not exist renders as ``??`` in the PDF. LaTeX
reports it as a warning and still exits zero, so nothing catches it: the paper
had carried ``\\S\\ref{sec:threat}`` --- a section that exists in no ``.tex``
file --- into a published build, and it was found only because a build log was
read by hand while chasing something else.

``paper/reproduce.md`` requires the paper to build "with no undefined
references and no ``\\todo`` markers". Like the manifest correspondence in
``test_reproduce_package.py``, that was prose nobody checked. This checks it.

Skipped when ``tectonic`` is unavailable, since a missing toolchain says
nothing about the paper.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "paper"

# LaTeX emits these for a \ref or \cite whose target is missing.
_UNDEFINED = re.compile(r"LaTeX Warning: (Reference|Citation) `([^']+)' on page", re.I)


@pytest.fixture(scope="module")
def build_log() -> str:
    """Build the paper once and hand back its log."""
    if shutil.which("tectonic") is None:
        pytest.skip("tectonic not installed")
    if not (PAPER / "main.tex").exists():
        pytest.skip("paper/main.tex absent")
    with tempfile.TemporaryDirectory() as out:
        proc = subprocess.run(
            ["tectonic", "--keep-logs", "--outdir", out, "main.tex"],
            cwd=PAPER,
            capture_output=True,
            text=True,
            timeout=600,
        )
        log = Path(out) / "main.log"
        if proc.returncode != 0:
            pytest.fail(f"paper failed to build:\n{proc.stderr[-3000:]}")
        return log.read_text(errors="replace") if log.exists() else proc.stderr


def test_no_undefined_references(build_log: str) -> None:
    """Mutation: point a ``\\ref`` at a label nobody defined and this fails.

    Without it the build still exits zero and the PDF ships a literal ``??``,
    which is how ``sec:threat`` survived in the published paper.
    """
    dangling = sorted({m.group(2) for m in _UNDEFINED.finditer(build_log)})
    assert not dangling, f"undefined \\ref or \\cite targets: {dangling}"


def test_no_todo_markers_left_in_the_paper() -> None:
    """`paper/reproduce.md` promises no ``\\todo`` markers. Cheap to keep true.

    The macro's own ``\\newcommand`` definition is not a marker, and flagging it
    would make this test permanently red and therefore permanently ignored.
    """
    offenders = [
        f"{path.relative_to(ROOT)}:{i}"
        for path in sorted(PAPER.rglob("*.tex"))
        for i, line in enumerate(path.read_text(errors="replace").splitlines(), 1)
        if re.search(r"\\todo\{|\bTODO:|\bFIXME\b", line) and "newcommand" not in line
    ]
    assert not offenders, f"todo markers in the paper: {offenders}"
