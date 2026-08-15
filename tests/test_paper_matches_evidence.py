"""Every number in the paper's headline table must come from committed evidence.

``paper/reproduce.md`` claims: "No number in the report was produced outside
this committed evidence." That is the repo's strongest claim about itself and
nothing enforced it. This repo has already shipped one number that did not
trace to its source --- a detector TPR/FPR pair that appeared in three
sections, had entered through a research note, and could not be reproduced from
the paper it cited --- so the failure mode is demonstrated rather than
hypothetical.

This regenerates the aggregate from ``bench/results/*.json`` with the same
``bench.report`` machinery the paper's own reproduction instructions use, and
checks each cell of ``tab:headline`` against it. It does not check the table's
prose, its ordering, or its formatting; only that each number a reader sees is
the number the evidence carries.

Kept deliberately narrow. Generalising to every table in the paper means a
LaTeX parser, and a fragile parser that fails on reformatting would be worse
than none: the point is a guard people trust enough to keep.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest

from bench.report import aggregate

ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS = ROOT / "paper" / "sections" / "experiments.tex"
RESULTS = ROOT / "bench" / "results"

# Which committed file carries each arm of the headline table. salience_matched
# lives in its own suite on purpose: adding an arm to ARMS would rewrite
# headline.json, which is manifest-checked and cited, so the salience arms were
# kept in a separate file to keep that byte-stable.
ARM_SOURCE = {
    "survival": "headline.json",
    "survival_embedding": "headline.json",
    "evict_on_negative": "headline.json",
    "recency": "headline.json",
    "random_matched": "headline.json",
    "ttl": "headline.json",
    "keep_everything": "headline.json",
    "salience_matched": "salience.json",
}


def _clean(cell: str) -> str:
    """Strip the LaTeX a number is dressed in, leaving the number."""
    cell = re.sub(r"\\(?:textbf|mathbf|emph|texttt)\{([^{}]*)\}", r"\1", cell)
    cell = cell.replace("$", "").replace("\\", "").replace("{", "").replace("}", "")
    return cell.strip()


@lru_cache(maxsize=1)
def headline_rows() -> dict[str, list[str]]:
    """Arm -> cells, parsed from the tab:headline tabular."""
    text = EXPERIMENTS.read_text()
    start = text.index("\\label{tab:headline}")
    body = text[start : text.index("\\end{tabular}", start)]
    rows: dict[str, list[str]] = {}
    for line in body.splitlines():
        if "&" not in line or "\\midrule" in line:
            continue
        cells = [_clean(c) for c in line.split("\\\\")[0].split("&")]
        arm = cells[0].replace("_", "_").split(" (")[0].strip()
        if arm in ARM_SOURCE:
            rows[arm] = cells
    return rows


@lru_cache(maxsize=1)
def evidence() -> dict[str, dict[str, Any]]:
    """Aggregate rows keyed by arm, from the committed result files.

    Cached: ``aggregate`` bootstraps confidence intervals, which is far too
    slow to repeat once per parametrised case.
    """
    out: dict[str, dict[str, Any]] = {}
    for filename in sorted(set(ARM_SOURCE.values())):
        runs = json.loads((RESULTS / filename).read_text())["runs"]
        for row in aggregate(runs):
            out.setdefault(row["arm"], row)
    return out


def test_the_table_parses_at_all() -> None:
    """Mutation: if the table is restructured so the parser silently matches
    nothing, every other test here passes vacuously. This is the guard on the
    guard."""
    rows = headline_rows()
    assert set(rows) == set(ARM_SOURCE), (
        f"parsed {sorted(rows)}; expected {sorted(ARM_SOURCE)}. If the table "
        "was restructured, update this parser and re-verify the numbers by "
        "hand before trusting it again."
    )


@pytest.mark.parametrize("arm", sorted(ARM_SOURCE))
def test_headline_cum_delta_matches_committed_runs(arm: str) -> None:
    """The paper prints cumulative delta in millions to 2dp; the evidence
    carries bytes. Mutation: edit a digit in the table and this fails."""
    cells = headline_rows()[arm]
    printed = float(_clean(cells[3]).replace("+", ""))
    measured = float(str(evidence()[arm]["cum delta"]).split(" [")[0].replace(",", ""))
    assert printed == pytest.approx(measured / 1e6, abs=0.01), (
        f"{arm}: paper says {printed}M, committed runs say {measured / 1e6:.2f}M"
    )


@pytest.mark.parametrize("arm", sorted(ARM_SOURCE))
def test_headline_kill_rate_matches_committed_runs(arm: str) -> None:
    """Mutation: the security claim rests on this column, so a drifted kill
    rate is the most consequential single digit in the paper."""
    printed = float(_clean(headline_rows()[arm][1]))
    measured = float(str(evidence()[arm]["kill rate"]).split(" [")[0])
    assert printed == pytest.approx(measured, abs=0.005), (
        f"{arm}: paper says kill {printed}, committed runs say {measured}"
    )


@pytest.mark.parametrize("arm", sorted(ARM_SOURCE))
def test_headline_final_population_matches_committed_runs(arm: str) -> None:
    """Population is the leanness claim. Mutation: drift here and the
    'starves dead weight the if-statement hoards' argument loses its number."""
    printed = float(_clean(headline_rows()[arm][5]))
    measured = float(str(evidence()[arm]["final pop"]).split(" [")[0])
    assert printed == pytest.approx(measured, abs=0.51), (
        f"{arm}: paper says pop {printed}, committed runs say {measured}"
    )
