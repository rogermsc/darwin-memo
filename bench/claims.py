"""Read a paper's tables back out of its LaTeX.

Extracted from ``tests/test_paper_tables_match_evidence.py``, which has used
this parser to re-derive every printed number in the paper from committed
runs. It moves here because a second caller now needs it: ``PaperClaimEnv``
builds its memory corpus out of the same tables, and two copies of a parser
whose failure mode is *silently returning the wrong cells* is the last thing
this repository needs.

The docstrings below record what each rule cost to learn. Keep them.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SECTIONS = ROOT / "paper" / "sections"


def paper_sections() -> tuple[Path, ...]:
    """Every LaTeX file the paper is assembled from, body and appendix alike.

    Callers used to name ``experiments.tex`` and ``appendix.tex`` by hand,
    which was right while those were the only two places a table could sit.
    They are not: the venue build moves whole blocks into
    ``sections/detail/``, and a hard-coded pair would have let a moved table
    stop being checked against its evidence. Enumerating the tree makes
    placement an editorial decision that cannot silently empty a corpus or
    disarm a guard.
    """
    return tuple(sorted(SECTIONS.rglob("*.tex")))


@lru_cache(maxsize=8)
def _source(path: Path | tuple[Path, ...]) -> str:
    """One searchable body, from one file or several.

    The paper was split into a body and an appendix, so a table's label no
    longer names the file it lives in. Callers pass both and the parser
    stops caring which half a table ended up in -- which is the property
    that matters, because a moved table must keep being checked against
    its evidence, and a lookup that silently found nothing would instead
    have quietly stopped checking.

    Concatenation is safe here: labels are unique across the paper, and
    each table closes its own ``\\end{tabular}`` well before the next
    file begins.
    """
    if isinstance(path, Path):
        return path.read_text()
    return "\n".join(p.read_text() for p in path)


def strip_cell(cell: str) -> str:
    """Leave the number, drop the LaTeX it is dressed in."""
    cell = re.sub(r"\\(?:textbf|mathbf|emph|texttt)\{([^{}]*)\}", r"\1", cell)
    for token in ("$", "\\", "{", "}"):
        cell = cell.replace(token, "")
    return cell.replace("\u2212", "-").strip()


def tabular(label: str, source: Path | tuple[Path, ...]) -> str:
    body = _source(source)
    start = body.index("\\label{" + label + "}")
    return body[start : body.index("\\end{tabular}", start)]


def data_rows(label: str, source: Path | tuple[Path, ...]) -> list[list[str]]:
    """Body rows of a tabular, with ``\\multirow`` group labels pushed down.

    A ``\\multirow`` sits on its own line with no ``&``, and the row it labels
    begins with ``&``. Skipping lines without ``&`` therefore drops the group
    name and silently shifts every remaining cell left by one -- which is how
    the first version of this parser reported ``attack=None`` for every row of
    ``tab:memsec``. The group name is carried forward instead.

    The group name may itself be marked up: ``tab:swebench-attack`` groups by
    ``\\multirow{3}{*}{\\texttt{django}}``, and a ``[^{}]*`` body could not match
    across those inner braces. The failure was the shift above all over again --
    the sequence column vanished and every row read one cell to the left -- so
    the pattern allows one level of nesting and the name is stripped like any
    other cell.

    The header row is returned like any other: callers filter it, because only
    they know what a real first column looks like in their table.
    """
    rows: list[list[str]] = []
    group = ""
    for line in tabular(label, source).splitlines():
        multirow = re.search(
            r"\\multirow\{\d+\}\{\*\}\{((?:[^{}]|\{[^{}]*\})*)\}", line
        )
        if multirow:
            group = strip_cell(multirow.group(1))
            line = line[multirow.end() :]
        if "&" not in line or "rule" in line:
            continue
        cells = [strip_cell(c) for c in line.split("\\\\")[0].split("&")]
        if not any(cells):
            continue
        if not cells[0] and group:
            cells[0] = group
        rows.append([c for c in cells if c != ""])
    return rows
