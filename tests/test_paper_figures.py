"""The figure has to be a view of the evidence, not a drawing of it.

The paper had nine tables and no figures. Adding one creates a new way for a
number to enter the paper without tracing to committed data -- a hand-plotted
curve is exactly the failure this repo has twice shipped and now guards against
everywhere else. So ``bench/figures.py`` emits the coordinates from
``bench/results/adversary.json``, the output is committed, and these tests fail
if the committed file and the runs disagree.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bench.figures import ADVERSARY_FIGURE, SERIES, render

ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS = ROOT / "paper" / "sections" / "experiments.tex"


def test_committed_figure_matches_the_runs() -> None:
    """Mutation: edit a coordinate in paper/figures/adversary.tex, or regenerate
    adversary.json without regenerating the figure, and this fires. It is the
    same check ``python -m bench.figures --check`` runs in CI."""
    assert ADVERSARY_FIGURE.is_file(), f"{ADVERSARY_FIGURE} is missing"
    assert ADVERSARY_FIGURE.read_text() == render(), (
        "paper/figures/adversary.tex does not match bench/results/adversary.json; "
        "run `python -m bench.figures --write`."
    )


def test_figure_is_included_and_referenced() -> None:
    """A figure the text never points at is decoration, and a float LaTeX places
    but nobody cites is the kind of thing a reader assumes is stale."""
    tex = EXPERIMENTS.read_text()
    assert "\\input{figures/adversary}" in tex, "the figure is not included"
    assert "\\ref{fig:adversary}" in tex, "the figure is never referenced in the text"


def test_every_series_has_a_point_at_every_budget() -> None:
    """A missing budget would draw a shorter line and read as a curve that ends,
    rather than as data that is absent. Mutation: drop a cell from the series
    spec's config filter so one arm resolves to fewer budgets."""
    from bench.figures import _series_points

    budgets = {0, 1, 2, 4, 8}
    for _key, label, want in SERIES:
        points = _series_points(want)
        assert {p[0] for p in points} == budgets, (
            f"series {label!r} has budgets {{p[0] for p in points}}, expected {budgets}"
        )


def test_plotted_values_agree_with_the_adversary_table() -> None:
    """The figure and ``tab:adversary`` are two views of one file, so they must
    not disagree. This checks the benign-capability column specifically, which
    is the one both show: the table to 2dp, the figure to 4.

    Mutation: point the ``ledger`` series at ``policy_bandit`` and regenerate.
    Both artifacts are then internally consistent -- the figure matches the file
    it was generated from and the table matches the file it was read from -- and
    only this test notices they describe different arms.

    The isolating mutation matters here. Swapping ``evict_on_negative`` between
    ``strikes`` 1 and 3 does *not* fail this test, and that is correct rather
    than a gap: those two rows have identical benign-capability columns
    ($1.00$ then $0.00$ throughout), so no check reading that column could tell
    them apart. A mutation the test cannot distinguish is not evidence the test
    is weak, but claiming it as evidence the test is strong would have been
    wrong -- the first version of this docstring did.
    """
    from bench.figures import _series_points

    tex = EXPERIMENTS.read_text()
    start = tex.index("\\label{tab:adversary}")
    body = tex[start : tex.index("\\end{tabular}", start)]
    table: dict[str, dict[int, float]] = {}
    budgets = [0, 1, 2, 4, 8]
    for line in body.splitlines():
        if "&" not in line or "rule" in line:
            continue
        cells = [
            re.sub(r"\\(?:textbf|mathbf|emph|texttt)\{([^{}]*)\}", r"\1", c)
            .replace("$", "")
            .replace("\\", "")
            .replace("{", "")
            .replace("}", "")
            .replace("\u2212", "-")
            .strip()
            for c in line.split("\\\\")[0].split("&")
        ]
        if "/" not in cells[-1]:
            continue
        table[cells[0]] = {
            b: float(cell.split("/")[1])
            for b, cell in zip(budgets, cells[1:], strict=True)
        }

    # Table row label -> the series that must plot the same numbers.
    same = {
        "survival": "ledger",
        "evict k=1": "evict-on-negative",
        "consecutive k=2": "consecutive $k{=}2$",
        "quarantine m=3": "quarantine $m{=}3$",
        "bandit": "bandit",
        "keep_everything": "keep everything",
    }
    by_label = {label: want for _k, label, want in SERIES}
    checked = 0
    for row, label in same.items():
        assert row in table, f"tab:adversary has no row {row!r}"
        plotted = {b: benign for b, benign, _kill in _series_points(by_label[label])}
        for budget, printed in table[row].items():
            assert printed == pytest.approx(plotted[budget], abs=0.006), (
                f"{row} at b={budget}: table says {printed}, figure plots "
                f"{plotted[budget]:.4f}"
            )
            checked += 1
    assert checked == len(same) * len(budgets), "not every cell was compared"
