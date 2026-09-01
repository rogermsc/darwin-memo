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


@lru_cache(maxsize=8)
def _source(path: Path) -> str:
    return path.read_text()


def strip_cell(cell: str) -> str:
    """Leave the number, drop the LaTeX it is dressed in."""
    cell = re.sub(r"\\(?:textbf|mathbf|emph|texttt)\{([^{}]*)\}", r"\1", cell)
    for token in ("$", "\\", "{", "}"):
        cell = cell.replace(token, "")
    return cell.replace("\u2212", "-").strip()


def tabular(label: str, source: Path) -> str:
    body = _source(source)
    start = body.index("\\label{" + label + "}")
    return body[start : body.index("\\end{tabular}", start)]


def data_rows(label: str, source: Path) -> list[list[str]]:
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
