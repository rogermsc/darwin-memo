"""The paper's stated reporting rules have to be the ones the harness applies.

``\\S`` "Reporting rules" in ``paper/sections/method.tex`` says what each
published number means. That is prose, and prose about code rots -- which is
this repository's most-repeated failure. These pin it.

The rules matter more here than the usual documentation-drift argument
allows. Two of them change how a table reads: the kill-cycle median is taken
over the seeds that killed, so an arm that kills once quickly beats an arm
that kills every time; and every metric is scored on the resource movement
that actually happened rather than on the reported one the ledger acted on,
without which the noisy suites would credit an arm for being deceived
favourably.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from bench.report import _REQUIRED_METRIC_KEYS, aggregate
from bench.runner import TAIL

ROOT = Path(__file__).resolve().parent.parent
METHOD = ROOT / "paper" / "sections" / "method.tex"

# Every metric the subsection defines, and the harness key behind it.
DEFINED = {
    "Kill rate": "poison_killed",
    "Poison alive": "poison_alive_final",
    "Kill cycle": "poison_kill_cycle",
    "Damage before kill": "damage_before_kill",
    "Cumulative and tail": "cum_delta",
    "Final population": "final_population",
}


def _section() -> str:
    body = METHOD.read_text()
    start = body.index("\\subsection{Reporting rules}")
    return body[start:]


def test_the_subsection_is_present_and_parses() -> None:
    """Parse guard: rename the subsection and every check below goes vacuous."""
    section = _section()
    assert "\\label{sec:reporting}" in section
    headings = set(re.findall(r"\\paragraph\{([^}]+)\}", section))
    assert len(headings) >= 6, headings


def test_every_defined_metric_is_one_the_harness_emits() -> None:
    section = _section()
    for heading, key in DEFINED.items():
        assert heading in section, f"the paper no longer defines {heading!r}"
        assert key in _REQUIRED_METRIC_KEYS, (
            f"{heading!r} is defined in the paper but {key!r} is not a metric "
            "the harness requires -- one of the two moved"
        )
    # The rule that scoring uses true movement names its own escape hatch.
    assert "reported_cum_delta" in _REQUIRED_METRIC_KEYS
    assert "reported\\_cum\\_delta" in section


def test_the_tail_window_the_paper_states_is_the_one_the_code_uses() -> None:
    """Mutation: change TAIL to 4 and this fails.

    The paper says "the mean true delta over its last five cycles". That five
    is a number in bench/runner.py, and nothing else compares them.
    """
    assert TAIL == 5
    assert "last five cycles" in _section()


def _run(seed: int, kill_cycle: int | None) -> dict[str, Any]:
    """A minimal run the aggregator accepts.

    Built from ``_REQUIRED_METRIC_KEYS`` with zero defaults rather than a
    hand-written literal, so a metric added to the harness later cannot make
    this fixture stale in a way that looks like a paper problem.
    """
    metrics: dict[str, Any] = dict.fromkeys(_REQUIRED_METRIC_KEYS, 0.0)
    metrics.update(
        poison_killed=kill_cycle is not None,
        poison_kill_cycle=kill_cycle,
        poison_starve_cycle=None,
        damage_before_kill=-1.0,
        cum_delta=1.0,
        final_population=3,
    )
    return {"arm": "survival", "seed": seed, "metrics": metrics}


def test_the_kill_cycle_median_excludes_seeds_that_never_killed() -> None:
    """The rule the paper states, asserted on the aggregator itself.

    Three seeds kill at cycle 2 and two never kill. The median is 2, not a
    number inflated by the two that never got there -- which is exactly why
    the paper says it must be read with the kill rate beside it, here 0.6.
    """
    runs = [_run(0, 2), _run(1, 2), _run(2, 2), _run(3, None), _run(4, None)]
    row = aggregate(runs)[0]
    assert row["kill cycle (med)"].startswith("2")
    assert row["kill rate"].startswith("0.6")
    # And with the two dropped entirely the median is unchanged, which is the
    # substance of the claim: those seeds contribute nothing to this column.
    assert aggregate(runs[:3])[0]["kill cycle (med)"].startswith("2")
