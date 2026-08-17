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

Kept deliberately narrow at first. Generalising to every table means a LaTeX
parser, and a fragile parser that fails on reformatting would be worse than
none: the point is a guard people trust enough to keep. That caution was right
about the *positional* parser this file started with, which misaligned the first
time a column was inserted and silently compared the wrong pairs of numbers. The
header-keyed version below cannot fail that way, and the remaining eight tables
are now covered on the same basis in
``tests/test_paper_tables_match_evidence.py`` -- which found the paper correct in
all 232 printed numbers it checks, and exists because a true unenforced claim is
the kind that rots.
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
def headline_rows() -> dict[str, dict[str, str]]:
    """Arm -> {column name: cell}, parsed from the tab:headline tabular.

    Keyed by the table's own header rather than by cell position. Positional
    indices were the original design and they failed the first time a column
    was inserted: adding the provenance poison column shifted ``cum delta`` and
    ``pop`` by one, and every cell test compared the wrong pair of numbers
    while still looking like a real comparison. A header-keyed parser cannot
    misalign that way -- it either finds the column or raises.
    """
    text = EXPERIMENTS.read_text()
    start = text.index("\\label{tab:headline}")
    body = text[start : text.index("\\end{tabular}", start)]
    header: list[str] | None = None
    rows: dict[str, dict[str, str]] = {}
    for line in body.splitlines():
        if "&" not in line or "\\midrule" in line:
            continue
        cells = [_clean(c) for c in line.split("\\\\")[0].split("&")]
        if header is None:
            header = [c.split("(")[0].strip().lower() for c in cells]
            continue
        arm = cells[0].split(" (")[0].strip()
        if arm in ARM_SOURCE:
            rows[arm] = dict(zip(header, cells, strict=True))
    assert header is not None, "tab:headline has no header row"
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
    printed = float(headline_rows()[arm]["cum delta"].replace("+", ""))
    measured = float(str(evidence()[arm]["cum delta"]).split(" [")[0].replace(",", ""))
    assert printed == pytest.approx(measured / 1e6, abs=0.01), (
        f"{arm}: paper says {printed}M, committed runs say {measured / 1e6:.2f}M"
    )


@pytest.mark.parametrize("arm", sorted(ARM_SOURCE))
def test_headline_kill_rate_matches_committed_runs(arm: str) -> None:
    """Mutation: the security claim rests on this column, so a drifted kill
    rate is the most consequential single digit in the paper."""
    printed = float(headline_rows()[arm]["kill"])
    measured = float(str(evidence()[arm]["kill rate"]).split(" [")[0])
    assert printed == pytest.approx(measured, abs=0.005), (
        f"{arm}: paper says kill {printed}, committed runs say {measured}"
    )


@pytest.mark.parametrize("arm", sorted(ARM_SOURCE))
def test_headline_poison_alive_matches_committed_runs(arm: str) -> None:
    """The column that exists because ``kill`` alone flattered three readings.

    Mutation: drift a cell here and the paper's completeness claim -- the
    ledger ends with none where the counter ends with two -- loses the only
    number that distinguishes eliminating poison from never acting on it.
    """
    printed = float(headline_rows()[arm]["alive"])
    measured = float(str(evidence()[arm]["poison alive (prov)"]).split(" [")[0])
    assert printed == pytest.approx(measured, abs=0.05), (
        f"{arm}: paper says {printed} poison alive by provenance, "
        f"committed runs say {measured}"
    )


@pytest.mark.parametrize("arm", sorted(ARM_SOURCE))
def test_headline_final_population_matches_committed_runs(arm: str) -> None:
    """Population is the leanness claim. Mutation: drift here and the
    'starves dead weight the if-statement hoards' argument loses its number."""
    printed = float(headline_rows()[arm]["pop"])
    measured = float(str(evidence()[arm]["final pop"]).split(" [")[0])
    assert printed == pytest.approx(measured, abs=0.51), (
        f"{arm}: paper says pop {printed}, committed runs say {measured}"
    )


# The caption's significance claim, which the cell checks above do not cover:
# "Survival's wins over keep/random/recency/ttl/salience are all 10/0/0,
# Holm-adjusted p <= 0.014". Four of those five arms live in headline.json and
# salience_matched in salience.json, and Holm adjusts across the full grid of
# comparisons in one call -- so each file must be tested in the call that
# actually produced the printed number, not merged into one grid that would
# adjust over a different family and change every p.
CAPTION_CLAIM = {
    "headline.json": ("keep_everything", "random_matched", "recency", "ttl"),
    "salience.json": ("salience_matched",),
}
CAPTION_MAX_HOLM = 0.014


@pytest.mark.parametrize(
    ("source", "opponent"),
    [(src, arm) for src, arms in CAPTION_CLAIM.items() for arm in arms],
)
def test_caption_significance_claim_holds(source: str, opponent: str) -> None:
    """Mutation: regenerate a suite so one comparison slips to 9/1/0 or its
    Holm-adjusted p crosses 0.014, and the caption keeps asserting a sweep
    that the evidence no longer supports. The cell tests above would not
    notice: every printed cell can be correct while the claim about them is
    stale.
    """
    from bench.report import significance

    runs = json.loads((RESULTS / source).read_text())["runs"]
    rows = {r["vs"]: r for r in significance(runs, baseline="survival")}
    assert opponent in rows, f"{opponent} not compared in {source}: {sorted(rows)}"
    row = rows[opponent]
    assert row["W/T/L"] == "10/0/0", (
        f"caption says survival beats {opponent} 10/0/0; evidence says {row['W/T/L']}"
    )
    holm = float(row["p (holm)"])
    assert holm <= CAPTION_MAX_HOLM, (
        f"caption says Holm-adjusted p <= {CAPTION_MAX_HOLM} for {opponent}; "
        f"evidence says {holm}"
    )
