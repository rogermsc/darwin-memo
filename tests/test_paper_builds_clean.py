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


# ---------------------------------------------------------------------------
# The same defect, caught without a LaTeX toolchain.
#
# The build-based test above skips wherever tectonic is absent, which includes
# CI -- so on its own it would have protected nothing where it mattered. Labels
# and refs are recoverable from the sources directly, so the check that
# actually runs on every push needs no toolchain at all.
# ---------------------------------------------------------------------------

_LABEL = re.compile(r"\\label\{([^}]+)\}")
_REF = re.compile(r"\\(?:page|auto|c)?ref\{([^}]+)\}")


def _tex_sources() -> list[Path]:
    return sorted(PAPER.rglob("*.tex"))


def test_every_ref_has_a_label_no_latex_required() -> None:
    """Mutation: reference a label nobody defined and this fails in CI, where
    the tectonic-based test above only skips.

    Multi-target refs (``\\ref{a,b}``) are split, since LaTeX resolves each
    independently and a half-valid one still renders a ``??``.
    """
    if not _tex_sources():
        pytest.skip("no paper sources")
    labels: set[str] = set()
    refs: dict[str, str] = {}
    for path in _tex_sources():
        text = path.read_text(errors="replace")
        labels |= set(_LABEL.findall(text))
        for raw in _REF.findall(text):
            for target in (t.strip() for t in raw.split(",")):
                if target:
                    refs.setdefault(target, str(path.relative_to(ROOT)))
    dangling = sorted((t, where) for t, where in refs.items() if t not in labels)
    assert not dangling, f"\\ref targets with no \\label: {dangling}"


_CITE = re.compile(r"\\cite[a-zA-Z]*\s*(?:\[[^\]]*\]){0,2}\{([^}]+)\}")
_BIBKEY = re.compile(r"^@[a-zA-Z]+\s*\{\s*([^,\s]+)\s*,", re.M)
BIB = PAPER / "references.bib"


def test_every_cite_has_a_bib_entry_no_latex_required() -> None:
    """The other half of the same defect, and the half nothing checked.

    ``test_every_ref_has_a_label_no_latex_required`` covers ``\\ref`` without a
    toolchain, but a ``\\cite`` at a key absent from ``references.bib`` renders
    as ``[?]`` by the same mechanism -- LaTeX warns and still exits zero. Only
    the tectonic-based test above caught that, and it skips wherever tectonic
    is absent, which includes CI. So the citation half was unguarded on every
    push while the reference half was not.

    Mutation: cite a key nobody defined and this fails.
    """
    if not _tex_sources() or not BIB.exists():
        pytest.skip("no paper sources")
    defined = set(_BIBKEY.findall(BIB.read_text(errors="replace")))
    assert defined, "references.bib parsed to zero keys -- the parser is broken"
    cited: dict[str, str] = {}
    for path in _tex_sources():
        for raw in _CITE.findall(path.read_text(errors="replace")):
            for key in (k.strip() for k in raw.split(",")):
                if key:
                    cited.setdefault(key, str(path.relative_to(ROOT)))
    assert cited, "no \\cite found -- the parser is broken, not the paper"
    dangling = sorted((k, where) for k, where in cited.items() if k not in defined)
    assert not dangling, f"\\cite keys with no references.bib entry: {dangling}"
