"""The other eight tables, checked against the evidence they claim to come from.

``paper/reproduce.md`` says "No number in the report was produced outside this
committed evidence", and ``tests/test_paper_matches_evidence.py`` enforced that
for exactly one table. Its own docstring gives the reason: "Generalising to every
table in the paper means a LaTeX parser, and a fragile parser that fails on
reformatting would be worse than none."

That reasoning was sound and is now out of date. The headline parser was rewritten
to key on the table's own header rather than on cell position -- because the
positional version misaligned the first time a column was inserted and compared
the wrong pairs while still looking like a real check -- and the same discipline
extends here. Every audit below found the paper *correct*: 73 deterministic cells
and 10 SWE-Bench arm rows, zero drift. The guard exists because a true unenforced
claim is one that rots silently, not because anything was wrong.

One design rule earns its place at the top, because violating it produced three
false alarms in a single afternoon of writing these checks:

    **Group by the complete run identity, and treat ambiguity as an error.**

``noisy.json`` carries a ``resource_scale`` dimension; averaging across it made
two correct ``tab:noise`` cells look wrong. ``adversary.json`` carries
``strikes``, so ``evict_on_negative`` appears twice per budget; collapsing them
made 840 metric values look like drift. In both cases the mean of two cells is a
number that appears in no table and no run. ``pick()`` therefore asserts that
exactly one cell matches, and a new config dimension breaks these tests loudly
instead of being silently averaged away.
"""

from __future__ import annotations

import json
import re
import statistics
from collections import defaultdict
from collections.abc import Callable, Sequence
from functools import cache, lru_cache
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
EXPERIMENTS = ROOT / "paper" / "sections" / "experiments.tex"
RESULTS = ROOT / "bench" / "results"

# Cells are printed to 2dp, so agreement means "rounds to the same thing".
DELTA_TOL = 0.006
RATE_TOL = 0.006
COUNT_TOL = 0.05


def _strip(cell: str) -> str:
    """Leave the number, drop the LaTeX it is dressed in."""
    cell = re.sub(r"\\(?:textbf|mathbf|emph|texttt)\{([^{}]*)\}", r"\1", cell)
    for token in ("$", "\\", "{", "}"):
        cell = cell.replace(token, "")
    return cell.replace("\u2212", "-").strip()


def tabular(label: str) -> str:
    body = EXPERIMENTS.read_text()
    start = body.index("\\label{" + label + "}")
    return body[start : body.index("\\end{tabular}", start)]


def data_rows(label: str) -> list[list[str]]:
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
    """
    rows: list[list[str]] = []
    group = ""
    for line in tabular(label).splitlines():
        multirow = re.search(
            r"\\multirow\{\d+\}\{\*\}\{((?:[^{}]|\{[^{}]*\})*)\}", line
        )
        if multirow:
            group = _strip(multirow.group(1))
            line = line[multirow.end() :]
        if "&" not in line or "rule" in line:
            continue
        cells = [_strip(c) for c in line.split("\\\\")[0].split("&")]
        if not any(cells):
            continue
        if not cells[0] and group:
            cells[0] = group
        rows.append([c for c in cells if c != ""])
    return rows


@cache
def _grouped(filename: str) -> dict[tuple[tuple[str, Any], ...], tuple[Any, ...]]:
    """Runs grouped by their full identity: arm plus every config field."""
    out: dict[tuple[tuple[str, Any], ...], list[dict[str, Any]]] = defaultdict(list)
    for run in json.loads((RESULTS / filename).read_text())["runs"]:
        identity = {"arm": run["arm"], **run.get("config", {})}
        out[tuple(sorted(identity.items()))].append(run["metrics"])
    return {k: tuple(v) for k, v in out.items()}


def pick(filename: str, **want: Any) -> tuple[dict[str, Any], ...]:
    """The one cell matching ``want``. Two matches is a bug, never a mean."""
    hits = [
        metrics
        for identity, metrics in _grouped(filename).items()
        if all(dict(identity).get(field) == value for field, value in want.items())
    ]
    assert len(hits) == 1, (
        f"{len(hits)} cells in {filename} match {want}; a table cell must name "
        "exactly one run group. If a config dimension was added, name it here "
        "rather than averaging over it."
    )
    return hits[0]


def mean(metrics: tuple[dict[str, Any], ...], key: str, scale: float = 1.0) -> float:
    return statistics.fmean(float(m[key]) for m in metrics) / scale


def median_starve(metrics: tuple[dict[str, Any], ...]) -> str:
    got = sorted(
        m["poison_starve_cycle"]
        for m in metrics
        if m["poison_starve_cycle"] is not None
    )
    return "never" if not got else str(got[len(got) // 2])


# --------------------------------------------------------------------------
# tab:noise -- false-bad noise grid, 30 seeds. Cells are "cum delta / benign".
# --------------------------------------------------------------------------
NOISE_ARMS: dict[str, dict[str, Any]] = {
    "survival": {"arm": "survival", "strikes": None},
    "evict k=1": {"arm": "evict_on_negative", "strikes": 1},
    "consecutive k=2": {"arm": "evict_consecutive", "strikes": 2},
}


def _noise_cells() -> list[tuple[str, float, str]]:
    rows = data_rows("tab:noise")
    rates = [float(x) for x in rows[0][1:]]
    return [
        (row[0], rate, cell)
        for row in rows[1:]
        for rate, cell in zip(rates, row[1:], strict=True)
    ]


@pytest.mark.parametrize(("arm", "rate", "cell"), _noise_cells())
def test_noise_grid_matches_committed_runs(arm: str, rate: float, cell: str) -> None:
    """Mutation: edit any digit of tab:noise and this fires.

    At rate 0 no flake is drawn, so ``false_bad`` is not run and the column is
    the ``flip`` model at rate 0 -- identical by construction, and stated here
    rather than left for a reader to infer from a missing cell.
    """
    want: dict[str, Any] = {
        **NOISE_ARMS[arm],
        "flake_rate": rate,
        "noise_model": "false_bad" if rate > 0 else "flip",
        "cycles": 30,
        "files_per_cycle": 12,
        "resource_scale": None,
        "suspend": None,
    }
    metrics = pick("noisy.json", **want)
    printed_delta, printed_benign = (float(x) for x in cell.split("/"))
    assert printed_delta == pytest.approx(
        mean(metrics, "cum_delta", 1e6), abs=DELTA_TOL
    )
    assert printed_benign == pytest.approx(
        round(mean(metrics, "probe_benign_correct_rate"), 2), abs=RATE_TOL
    )


# --------------------------------------------------------------------------
# tab:adversary -- the paper's central table. 30 seeds, five budgets.
# --------------------------------------------------------------------------
ADVERSARY_ARMS: dict[str, dict[str, Any]] = {
    "survival": {"arm": "survival", "strikes": None, "suspend": None},
    "evict k=1": {"arm": "evict_on_negative", "strikes": 1},
    "evict k=3": {"arm": "evict_on_negative", "strikes": 3},
    "consecutive k=2": {"arm": "evict_consecutive", "strikes": 2},
    "quarantine m=3": {"arm": "quarantine", "suspend": 3},
    "bandit": {"arm": "policy_bandit"},
    "keep_everything": {"arm": "keep_everything"},
}


def _adversary_cells() -> list[tuple[str, int, str]]:
    rows = data_rows("tab:adversary")
    budgets = [int(x.split("=")[1]) for x in rows[0][1:]]
    return [
        (row[0], budget, cell)
        for row in rows[1:]
        for budget, cell in zip(budgets, row[1:], strict=True)
    ]


@pytest.mark.parametrize(("arm", "budget", "cell"), _adversary_cells())
def test_adversary_grid_matches_committed_runs(
    arm: str, budget: int, cell: str
) -> None:
    """The table the paper's central claim is read off. Mutation: drift one cell
    and the separation between counters and the ledger stops being the measured
    one, with nothing else in the repo noticing."""
    want: dict[str, Any] = {**ADVERSARY_ARMS[arm], "lie_budget": budget}
    metrics = pick("adversary.json", **want)
    printed_delta, printed_benign = (float(x) for x in cell.split("/"))
    assert printed_delta == pytest.approx(
        mean(metrics, "cum_delta", 1e6), abs=DELTA_TOL
    )
    assert printed_benign == pytest.approx(
        round(mean(metrics, "probe_benign_correct_rate"), 2), abs=RATE_TOL
    )


# --------------------------------------------------------------------------
# tab:persistence -- destroy vs persist, the axis added in #63/#64.
# --------------------------------------------------------------------------
def _persistence_cells() -> list[tuple[str, int, str, str, str]]:
    """Rows are ``arm & budget & 4 values`` once, then ``& budget & 4 values``.

    Empty cells are stripped by ``data_rows``, so a continuation row arrives
    with five entries and its budget first, while an arm's opening row arrives
    with six and its name first. Requiring six dropped twelve of the sixteen
    cells and the parse guard at the bottom of this file is what caught it --
    which is the whole argument for having a guard on the guard.
    """
    out = []
    arm = ""
    for row in data_rows("tab:persistence"):
        if row and row[0].isdigit():
            budget, values = int(row[0]), row[1:]
        elif len(row) >= 6 and row[1].isdigit():
            arm, budget, values = row[0], int(row[1]), row[2:]
        else:
            continue
        if len(values) < 4:
            continue
        out.append((arm, budget, "destroy", values[0], values[1]))
        out.append((arm, budget, "persist", values[2], values[3]))
    return out


@pytest.mark.parametrize(
    ("arm", "budget", "objective", "kill", "benign"), _persistence_cells()
)
def test_persistence_matches_committed_runs(
    arm: str, budget: int, objective: str, kill: str, benign: str
) -> None:
    """The kill column here is the one that flattered a mechanism in #63 and was
    corrected in #64, so it is worth pinning to the run that produced it."""
    metrics = pick(
        "persistence.json", arm=arm, lie_budget=budget, adversary_objective=objective
    )
    assert float(kill) == pytest.approx(mean(metrics, "poison_killed"), abs=RATE_TOL)
    assert float(benign) == pytest.approx(
        mean(metrics, "probe_benign_correct_rate"), abs=RATE_TOL
    )


# --------------------------------------------------------------------------
# tab:withholding -- suppressed rather than corrupted measurements.
# --------------------------------------------------------------------------
WITHHOLD_ARM_CONFIG: dict[str, dict[str, Any]] = {
    "survival": {"arm": "survival"},
    "survival_paced": {"arm": "survival_paced"},
    "evict_on_negative": {"arm": "evict_on_negative", "strikes": 1},
    "keep_everything": {"arm": "keep_everything"},
}


def _withholding_cells() -> list[tuple[str, int, str, str, str, str]]:
    """Same continuation-row shape as tab:persistence: an arm's opening row
    carries its name, later rows start with the budget."""
    out = []
    arm = ""
    for row in data_rows("tab:withholding"):
        if row and row[0].isdigit():
            budget, values = int(row[0]), row[1:]
        elif len(row) >= 6 and row[1].isdigit():
            arm, budget, values = row[0], int(row[1]), row[2:]
        else:
            continue
        if len(values) < 4:
            continue
        out.append((arm, budget, values[0], values[1], values[2], values[3]))
    return out


@pytest.mark.parametrize(
    ("arm", "budget", "benign", "kill", "cum", "sel_kill"), _withholding_cells()
)
def test_withholding_matches_committed_runs(
    arm: str, budget: int, benign: str, kill: str, cum: str, sel_kill: str
) -> None:
    """Both halves of the row, against two different results files.

    The selective column is the one that refutes the pacing mitigation, so
    it is pinned to the run that refuted it rather than to prose.
    """
    config = WITHHOLD_ARM_CONFIG[arm.replace("\\_", "_")]
    indiscriminate = pick(
        "withholding.json",
        lie_budget=budget,
        adversary_objective="withhold",
        cycles=60,
        **config,
    )
    assert float(benign) == pytest.approx(
        mean(indiscriminate, "probe_benign_correct_rate"), abs=RATE_TOL
    )
    assert float(kill) == pytest.approx(
        mean(indiscriminate, "poison_killed"), abs=RATE_TOL
    )
    # Cells are printed as "+25.55M" / "-6.42M"; strip the unit, keep the sign.
    assert float(cum.rstrip("M")) == pytest.approx(
        mean(indiscriminate, "cum_delta", scale=1e6), abs=0.006
    )
    selective = pick(
        "withholding_selective.json",
        lie_budget=budget,
        adversary_objective="withhold_selective",
        cycles=60,
        **config,
    )
    assert float(sel_kill) == pytest.approx(
        mean(selective, "poison_killed"), abs=RATE_TOL
    )


# --------------------------------------------------------------------------
# tab:withholding-testsuite -- the same attack on the second env family.
# --------------------------------------------------------------------------
def _withholding_testsuite_cells() -> list[tuple[str, int, str, str, str]]:
    """Same continuation-row shape as tab:withholding, one file, no sel. half."""
    out = []
    arm = ""
    for row in data_rows("tab:withholding-testsuite"):
        if row and row[0].isdigit():
            budget, values = int(row[0]), row[1:]
        elif len(row) >= 5 and row[1].isdigit():
            arm, budget, values = row[0], int(row[1]), row[2:]
        else:
            continue
        if len(values) < 3:
            continue
        out.append((arm, budget, values[0], values[1], values[2]))
    return out


@pytest.mark.parametrize(
    ("arm", "budget", "benign", "kill", "cum"), _withholding_testsuite_cells()
)
def test_withholding_testsuite_matches_committed_runs(
    arm: str, budget: int, benign: str, kill: str, cum: str
) -> None:
    """The second-family row, against the file that produced it.

    The cum delta column is in passing tests, not resource units, so it
    carries no M suffix and no scale. A mutation that reused the storage
    scale here would divide every cell by a million and still parse.
    """
    config = WITHHOLD_ARM_CONFIG[arm.replace("\\_", "_")]
    runs = pick(
        "withholding_testsuite.json",
        lie_budget=budget,
        adversary_objective="withhold",
        env_family="testsuite",
        cycles=60,
        **config,
    )
    assert float(benign) == pytest.approx(
        mean(runs, "probe_benign_correct_rate"), abs=RATE_TOL
    )
    assert float(kill) == pytest.approx(mean(runs, "poison_killed"), abs=RATE_TOL)
    assert float(cum) == pytest.approx(mean(runs, "cum_delta"), abs=COUNT_TOL)


# --------------------------------------------------------------------------
# tab:memsec -- attack class x where the defence sits. Labelled runs.
# --------------------------------------------------------------------------
MEMSEC_ATTACK = {
    "explicit": "explicit",
    "policy-conformant": "policy_conformant",
    "inert (dormant)": "inert",
}


@lru_cache(maxsize=1)
def _memsec_by_label() -> dict[str, tuple[dict[str, Any], ...]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run in json.loads((RESULTS / "memsec.json").read_text())["runs"]:
        out[run["label"]].append(run["metrics"])
    return {k: tuple(v) for k, v in out.items()}


def _memsec_rows() -> list[tuple[str, str, str, str, str, str, str]]:
    out: list[tuple[str, str, str, str, str, str, str]] = []
    for row in data_rows("tab:memsec"):
        if len(row) < 7 or row[0] not in MEMSEC_ATTACK:
            continue
        d, tpr, harm, cum, starve, alive = row[1:7]
        out.append((MEMSEC_ATTACK[row[0]], d, tpr, harm, cum, starve, alive))
    return out


@pytest.mark.parametrize(
    ("attack", "defence", "tpr", "harm", "cum", "starve", "alive"), _memsec_rows()
)
def test_memsec_rows_match_committed_runs(
    attack: str, defence: str, tpr: str, harm: str, cum: str, starve: str, alive: str
) -> None:
    """Five columns per row, including the two provenance columns (``starve``,
    ``alive@30``) that make this the one table which never needed the #65
    correction -- it was already counting poison by provenance."""
    metrics = _memsec_by_label()[f"attack={attack},defence={defence}"]
    assert float(tpr) == pytest.approx(mean(metrics, "filter_tpr"), abs=RATE_TOL)
    assert float(harm) == pytest.approx(
        mean(metrics, "damage_before_kill", 1e6), abs=DELTA_TOL
    )
    assert float(cum) == pytest.approx(mean(metrics, "cum_delta", 1e6), abs=DELTA_TOL)
    assert starve == median_starve(metrics)
    assert float(alive) == pytest.approx(
        mean(metrics, "poison_alive_final"), abs=COUNT_TOL
    )


# --------------------------------------------------------------------------
# The two SWE-Bench-CL matrices. One committed file per (arm, sequence, seed).
# --------------------------------------------------------------------------
SWEBENCH_TABLES = {
    "tab:swebench": "swebench_cl",
    "tab:swebench-long": "swebench_cl_long",
}


@cache
def _swebench_by_arm(directory: str) -> dict[str, tuple[dict[str, Any], ...]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in sorted((RESULTS / directory).glob("*.json")):
        if path.name == "MANIFEST.json":
            continue
        for run in json.loads(path.read_text())["runs"]:
            out[run["arm"]].append(run["metrics"])
    return {k: tuple(v) for k, v in out.items()}


def _swebench_rows() -> list[tuple[str, str, str, str]]:
    return [
        (directory, row[0], row[1], row[2])
        for label, directory in SWEBENCH_TABLES.items()
        for row in data_rows(label)[1:]
    ]


@pytest.mark.parametrize(("directory", "arm", "tasks", "resolve"), _swebench_rows())
def test_swebench_resolve_matches_committed_runs(
    directory: str, arm: str, tasks: str, resolve: str
) -> None:
    """The real-task leg's headline numbers, including the null the paper rests
    on. The task count is checked too: a resolve rate over the wrong denominator
    is the failure this leg is most exposed to, since cells are separate files
    and a missing one would silently shrink the denominator."""
    metrics = _swebench_by_arm(directory)[arm]
    assert len(metrics) == int(tasks), (
        f"{arm} in {directory}: paper says {tasks} tasks, committed runs have "
        f"{len(metrics)}"
    )
    measured = statistics.fmean(float(bool(m["resolved"])) for m in metrics)
    assert float(resolve) == pytest.approx(measured, abs=0.0006)


# --------------------------------------------------------------------------
# tab:wef -- Write-Execute-Forget with a local model deciding adoption.
#
# Worth a note on why this one is here. It was almost excluded on the grounds
# that a sampled model's output is not a deterministic function of committed
# data -- but that confuses *reproducing* a run with *reading* one. The run
# already happened, its per-seed metrics are committed, and the table's means
# over them are as checkable as any other. Excluding it would have been an
# assumption presented as a limitation, which is the failure this repo keeps
# finding, so it was checked instead.
# --------------------------------------------------------------------------
WEF_ARMS = {
    "keep_everything": "keep_everything_llm",
    "evict_on_negative": "evict_on_negative_llm",
    "ledger": "survival_llm",
}
WEF_COLUMNS = (
    ("E2", "wef_e2_adoption_rate", 0.006),
    ("E3", "wef_e3_externalized_cycles", 0.06),
    ("F1", "wef_f1_repair", 0.006),
    ("F2", "wef_f2_benign_preservation", 0.006),
    ("alive", "wef_poison_alive_final", COUNT_TOL),
)


@lru_cache(maxsize=1)
def _wef_by_cell() -> dict[tuple[str, str], tuple[dict[str, Any], ...]]:
    out: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for filename in ("wef-llama32.json", "wef-llama32-counter.json"):
        for run in json.loads((RESULTS / filename).read_text())["runs"]:
            out[(run["config"]["attack"], run["arm"])].append(run["metrics"])
    return {k: tuple(v) for k, v in out.items()}


def _wef_rows() -> list[tuple[str, str, tuple[str, ...]]]:
    out: list[tuple[str, str, tuple[str, ...]]] = []
    for row in data_rows("tab:wef"):
        if len(row) < 7 or row[1] not in WEF_ARMS:
            continue
        attack = MEMSEC_ATTACK.get(row[0])
        if attack is None:
            continue
        # E2, E3, F1, F2, then `alive` -- skipping `kill`, whose cell is a
        # hand-written range or annotation ("1--3", "starve 19", "never")
        # rather than one statistic. Named here so the omission is visible.
        out.append((attack, row[1], (row[2], row[3], row[4], row[5], row[7])))
    return out


@pytest.mark.parametrize(("attack", "arm", "printed"), _wef_rows())
def test_wef_rows_match_committed_runs(
    attack: str, arm: str, printed: tuple[str, ...]
) -> None:
    """Mutation: edit any of E2/E3/F1/F2/alive and this fires. These are the
    numbers behind the paper's own negative result -- that a one-line counter
    revokes poison sooner than the ledger -- so they matter more than most."""
    metrics = _wef_by_cell()[(attack, WEF_ARMS[arm])]
    for value, (name, key, tol) in zip(printed, WEF_COLUMNS, strict=True):
        assert float(value) == pytest.approx(mean(metrics, key), abs=tol), (
            f"{attack}/{arm} column {name}: paper says {value}"
        )


# --------------------------------------------------------------------------
# tab:swebench-attack -- the paper's central real-task claim, and until now
# the one table in the paper nothing checked. Its numbers have moved twice:
# once when the sympy arm landed and the burial tripling stopped replicating,
# once when the sixth world reversed the ordering. Both edits were made by
# hand from a tool's printed output into LaTeX, which is the transcription
# step every other table in this file already has a guard for.
#
# The ratio column is a mean of *per-world* ratios, not a ratio of the two
# printed means: django is 2.76 that way and 2.74 the other. They agree to
# 2dp on every other row, so a ratio-of-means check would pass here while
# encoding the wrong definition -- the same near-miss that made the headline
# parser key on the header instead of on cell position.
# --------------------------------------------------------------------------
ATTACK_SEQUENCES = {
    "django": "django_django_sequence",
    "sympy": "sympy_sympy_sequence",
}


@lru_cache(maxsize=1)
def _attack_runs() -> tuple[Any, ...]:
    from bench.swebench_cl.curve import load_dir

    return tuple(load_dir(RESULTS / "swebench_cl_adversary"))


def _attack_buried(sequence: str, arm: str, budget: int) -> dict[Any, int]:
    """Benign burial per world, read off the shipped analysis tool."""
    from bench.swebench_cl.attack import benign_buried, by_world

    worlds = by_world(list(_attack_runs()), budget, sequence)
    return {k: benign_buried(v) for k, v in worlds.items() if k[0] == arm}


def _swebench_attack_rows() -> list[tuple[str, str, str, str, str]]:
    return [
        (row[0], row[1], row[2], row[3], row[4])
        for row in data_rows("tab:swebench-attack")[1:]
    ]


@pytest.mark.parametrize(
    ("sequence", "arm", "buried", "ratio", "retained"), _swebench_attack_rows()
)
def test_swebench_attack_row_matches_committed_runs(
    sequence: str, arm: str, buried: str, ratio: str, retained: str
) -> None:
    """Mutation: swap the two sympy ratios, or restore either to its
    pre-sixth-world value, and this fires. The world count is asserted too,
    because the failure this leg is most exposed to is a cell that did not run:
    the sympy rows were means over two seeds for one release and read as means
    over three, and nothing but the caption said which.
    """
    from bench.swebench_cl.attack import retention

    sequence_id = ATTACK_SEQUENCES[sequence]
    clean = _attack_buried(sequence_id, arm, 0)
    attacked = _attack_buried(sequence_id, arm, 2)
    shared = sorted(set(clean) & set(attacked))
    assert len(shared) == 3, (
        f"{sequence}/{arm}: {len(shared)} paired worlds in the committed runs, "
        "but the table caption says three seeds; a cell is missing or unpaired"
    )

    printed = [float(n) for n in re.findall(r"-?\d+\.?\d*", buried)]
    assert len(printed) == 2, f"cannot read a b=0 -> b=2 pair from {buried!r}"
    assert statistics.fmean(clean[w] for w in shared) == pytest.approx(
        printed[0], abs=COUNT_TOL
    )
    assert statistics.fmean(attacked[w] for w in shared) == pytest.approx(
        printed[1], abs=COUNT_TOL
    )

    if ratio == "---":
        assert not any(clean[w] for w in shared), (
            f"{sequence}/{arm}: the table declines to print a ratio, which is "
            "only honest while the unattacked burial is zero"
        )
    else:
        measured = statistics.fmean(attacked[w] / clean[w] for w in shared)
        assert float(ratio.removesuffix("times")) == pytest.approx(measured, abs=0.006)

    result = retention(list(_attack_runs()), arm, 2, sequence=sequence_id)
    assert float(retained) == pytest.approx(result["retained"], abs=0.0006)


# --------------------------------------------------------------------------
# Guards on the guards. Without these, a restructured table silently
# parametrises zero cases and every test above passes vacuously.
# --------------------------------------------------------------------------
EXPECTED_CELLS: dict[str, tuple[Callable[[], Sequence[object]], int]] = {
    "noise": (_noise_cells, 15),
    "adversary": (_adversary_cells, 35),
    "persistence": (_persistence_cells, 16),
    "memsec": (_memsec_rows, 7),
    "swebench": (_swebench_rows, 10),
    "swebench-attack": (_swebench_attack_rows, 6),
    "wef": (_wef_rows, 9),
}


@pytest.mark.parametrize("name", sorted(EXPECTED_CELLS))
def test_every_table_still_parses(name: str) -> None:
    """Mutation: reformat a table so the parser matches nothing. Every check
    above would pass on an empty parameter list, which is the failure mode that
    makes a green suite worthless."""
    collect, expected = EXPECTED_CELLS[name]
    found = len(collect())
    assert found == expected, (
        f"parsed {found} cells from the {name} table, expected {expected}. If the "
        "table changed shape, update the parser and re-verify the numbers by "
        "hand before trusting this file again."
    )


# How many printed numbers each parametrised check compares.
NUMBERS_PER_CHECK = {
    "noise": 2,
    "adversary": 2,
    "persistence": 2,
    "memsec": 5,
    "swebench": 2,
    "swebench-attack": 4,
    "wef": 5,
}


def _unprinted(name: str) -> int:
    """Cells a check verifies that are not numbers, so the tally stays honest.

    ``tab:swebench-attack`` prints ``---`` rather than a ratio for the arm that
    buries nothing, and that cell is checked (the dash is only honest while the
    denominator is zero) but must not be counted as a printed number in a
    sentence whose whole purpose is not over-claiming.
    """
    if name != "swebench-attack":
        return 0
    return sum(1 for row in _swebench_attack_rows() if row[3] == "---")


def test_reproduce_md_states_the_real_coverage() -> None:
    """``reproduce.md`` quotes this file's coverage, so compute it, don't claim it.

    Both figures in that sentence were wrong when first written -- invented from
    a rough mental tally rather than counted, which is precisely the defect this
    whole file exists to catch, committed while writing the catcher. So the doc's
    numbers are now derived here and the sentence cannot drift from the code.
    """
    checks = sum(len(collect()) for collect, _ in EXPECTED_CELLS.values())
    numbers = sum(
        len(EXPECTED_CELLS[name][0]()) * per - _unprinted(name)
        for name, per in NUMBERS_PER_CHECK.items()
    )
    doc = (ROOT / "paper" / "reproduce.md").read_text()
    claim = f"{checks} checks covering {numbers}\nprinted numbers"
    assert claim.replace("\n", " ") in " ".join(doc.split()), (
        f"paper/reproduce.md should say '{checks} checks covering {numbers} "
        "printed numbers'; update it to the counted figures."
    )


# --------------------------------------------------------------------------
# tab:rent -- the price of standing still, against bench/results/rent.json.
# --------------------------------------------------------------------------
RENT_FLOOR_ARMS: dict[str, dict[str, Any]] = {
    "survival_paced": {"arm": "survival_paced"},
    "evict_on_negative": {"arm": "evict_on_negative", "strikes": 1},
    "quarantine": {"arm": "quarantine", "suspend": 3},
    "keep_everything": {"arm": "keep_everything"},
}
RENT_COLUMNS = (0.0, 0.25, 0.5, 0.75, 1.0)


def _rent_cells() -> list[tuple[int, str, float, str]]:
    """(cycles, row, rent, printed cell), one case per number in the table."""
    out: list[tuple[int, str, float, str]] = []
    for row in data_rows("tab:rent"):
        if len(row) != 2 + len(RENT_COLUMNS) or not row[0].split()[0].isdigit():
            continue  # the header row has the same width as a data row
        horizon, name, values = row[0], row[1], row[2:]
        cycles = int(horizon.split()[0])
        out.extend(
            (cycles, name, rent, value)
            for rent, value in zip(RENT_COLUMNS, values, strict=True)
        )
    return out


@pytest.mark.parametrize(("cycles", "row", "rent", "cell"), _rent_cells())
def test_rent_table_matches_committed_runs(
    cycles: int, row: str, rent: float, cell: str
) -> None:
    """Every cell, and for the floor row every arm that claims to be in it.

    The caption asserts the four non-ledger arms are "identical to the last
    byte" at each rent, which is the whole reason the table prints one row
    instead of four. Checking a single representative would let that
    collapse be wrong while the table still read as correct, so the floor
    row is checked once per arm and the strictness is exact equality
    between them, not the 2dp tolerance the printed cell gets.
    """
    common = {
        "cycles": cycles,
        "lie_budget": 12,
        "hold_cost": rent,
        "env_family": "storage_rent",
        "adversary_objective": "withhold",
    }
    if row == "survival":
        got = mean(pick("rent.json", **common, arm="survival"), "cum_delta", 1e6)
        assert float(cell) == pytest.approx(got, abs=DELTA_TOL)
        return
    assert row == "do-nothing floor", row
    exact = {
        name: mean(pick("rent.json", **common, **config), "cum_delta")
        for name, config in RENT_FLOOR_ARMS.items()
    }
    assert len(set(exact.values())) == 1, (
        f"the floor row claims four identical arms at rent {rent}, {cycles} "
        f"cycles; they are {exact}"
    )
    assert float(cell) == pytest.approx(next(iter(exact.values())) / 1e6, abs=DELTA_TOL)


def test_rent_zero_column_reproduces_the_published_withholding_file() -> None:
    """The canary the sweep rests on, asserted across the whole zero column.

    Every claim in the rent section is a comparison against rent 0, and
    that column is only meaningful if it IS the published storage family
    rather than a re-run that resembles it. RentedStorageEnv delegates to
    StorageEnv at zero rent precisely so this can be exact, so the
    tolerance here is zero: any drift means the harness moved and the
    whole sweep is measuring two things at once.
    """
    arms = {"survival": {"arm": "survival"}, **RENT_FLOOR_ARMS}
    checked = 0
    for cycles in (30, 60):
        for budget in (0, 12):
            for name, config in arms.items():
                rented = pick(
                    "rent.json",
                    **config,
                    cycles=cycles,
                    lie_budget=budget,
                    hold_cost=0.0,
                    env_family="storage_rent",
                    adversary_objective="withhold",
                )
                published = pick(
                    "withholding.json",
                    **config,
                    cycles=cycles,
                    lie_budget=budget,
                    adversary_objective="withhold",
                )
                for key in ("cum_delta", "probe_benign_correct_rate", "poison_killed"):
                    assert mean(rented, key) == mean(published, key), (
                        f"{name} at {cycles} cycles, budget {budget}: the "
                        f"zero-rent column has drifted from withholding.json "
                        f"on {key}"
                    )
                checked += 1
    assert checked == 20


# --------------------------------------------------------------------------
# tab:rent-lying -- the same axis, the other attacker.
# --------------------------------------------------------------------------
RENT_LYING_ARMS: dict[str, dict[str, Any]] = {
    "survival": {"arm": "survival"},
    "evict_on_negative": {"arm": "evict_on_negative", "strikes": 1},
    "quarantine": {"arm": "quarantine", "suspend": 3},
    "keep_everything": {"arm": "keep_everything"},
}


def _rent_lying_cells() -> list[tuple[str, float, str]]:
    out: list[tuple[str, float, str]] = []
    for row in data_rows("tab:rent-lying"):
        if len(row) != 1 + len(RENT_COLUMNS) or row[0] not in RENT_LYING_ARMS:
            continue  # the header row is the same width
        out.extend(
            (row[0], rent, value)
            for rent, value in zip(RENT_COLUMNS, row[1:], strict=True)
        )
    return out


@pytest.mark.parametrize(("arm", "rent", "cell"), _rent_lying_cells())
def test_rent_lying_table_matches_committed_runs(
    arm: str, rent: float, cell: str
) -> None:
    """Budget 2 at 60 cycles, the interior where a liar actually operates.

    The caption's claim that ``survival_paced`` is identical to
    ``survival`` in every cell is why the table has four rows instead of
    five, so it is asserted here rather than trusted: an omitted row that
    was quietly different would read as a tidier table.
    """
    common = {
        "cycles": 60,
        "lie_budget": 2,
        "hold_cost": rent,
        "env_family": "storage_rent",
        "adversary_objective": "destroy",
    }
    got = mean(pick("rent_lying.json", **common, **RENT_LYING_ARMS[arm]), "cum_delta")
    assert float(cell) == pytest.approx(got / 1e6, abs=DELTA_TOL)
    if arm == "survival":
        paced = mean(
            pick("rent_lying.json", **common, arm="survival_paced"), "cum_delta"
        )
        assert paced == got, (
            "the caption omits survival_paced as identical to survival; at "
            f"rent {rent} they are {paced} and {got}"
        )


def test_lying_and_withholding_agree_wherever_the_attacker_does_nothing() -> None:
    """At budget 0 the wrapper adds no behaviour, so two objectives must agree.

    This crosses two files produced by two suites under two objectives,
    which makes it a stronger canary than either file's own zero-rent
    column: a harness change that moved both files identically would slip
    past a within-file check and fail here only if it moved them
    differently -- and a change to the adversary that leaked behaviour
    into budget 0 would fail here and nowhere else.
    """
    arms = {"survival_paced": {"arm": "survival_paced"}, **RENT_LYING_ARMS}
    checked = 0
    for cycles in (30, 60):
        for rent in RENT_COLUMNS:
            for config in arms.values():
                common = {
                    "cycles": cycles,
                    "lie_budget": 0,
                    "hold_cost": rent,
                    "env_family": "storage_rent",
                    **config,
                }
                lying = pick("rent_lying.json", **common, adversary_objective="destroy")
                held = pick("rent.json", **common, adversary_objective="withhold")
                for key in ("cum_delta", "probe_benign_correct_rate", "poison_killed"):
                    assert mean(lying, key) == mean(held, key), (
                        f"budget 0 differs between objectives at {cycles} "
                        f"cycles, rent {rent}, on {key}"
                    )
                checked += 1
    assert checked == 50


# --------------------------------------------------------------------------
# sec:rent's second-family paragraph -- prose numbers, no table to parse.
# --------------------------------------------------------------------------
def _rent_testsuite(arm: str, cycles: int, budget: int, rent: float) -> float:
    config = {"survival": {"arm": "survival"}, **RENT_LYING_ARMS}[arm]
    return mean(
        pick(
            "rent_testsuite.json",
            **config,
            cycles=cycles,
            lie_budget=budget,
            hold_cost=rent,
            env_family="testsuite_rent",
            adversary_objective="withhold",
        ),
        "cum_delta",
    )


def test_second_family_rent_paragraph_matches_committed_runs() -> None:
    """The paragraph cites its numbers in prose, so check them as prose.

    Every figure \\S sec:rent states about the test-suite family: the
    unattacked pair it opens with, the lead widening, the counters being
    identical rather than merely close, the flatness at 30 cycles, and
    the budget-12 cell that ends below zero. A table would have been
    checked by the parser above; prose has to be enumerated, and the
    alternative is the class of unenforced claim this file exists for.
    """
    assert _rent_testsuite("evict_on_negative", 60, 0, 0.0) == pytest.approx(
        178.00, abs=DELTA_TOL
    )
    assert _rent_testsuite("survival", 60, 0, 0.0) == pytest.approx(121.33, abs=0.01)

    # "the counter's lead going 56.67 -> 69.27"
    lead = [
        _rent_testsuite("evict_on_negative", 60, 0, r)
        - _rent_testsuite("survival", 60, 0, r)
        for r in (0.0, 1.0)
    ]
    assert lead[0] == pytest.approx(56.67, abs=0.01)
    assert lead[1] == pytest.approx(69.27, abs=0.01)

    # "identical -- not approximately, identically -- across all five rents"
    for arm in ("evict_on_negative", "quarantine", "keep_everything"):
        for cycles in (30, 60):
            for budget in (0, 12):
                values = {_rent_testsuite(arm, cycles, budget, r) for r in RENT_COLUMNS}
                assert len(values) == 1, (arm, cycles, budget, sorted(values))

    # "at 30 cycles ... every arm flat, the ledger paying exactly zero"
    assert len({_rent_testsuite("survival", 30, 0, r) for r in RENT_COLUMNS}) == 1

    # "rent erases that by 0.25 and drives it negative by 1.0"
    assert _rent_testsuite("survival", 60, 12, 0.0) == pytest.approx(
        65.00, abs=DELTA_TOL
    )
    assert _rent_testsuite("survival", 60, 12, 0.25) < _rent_testsuite(
        "keep_everything", 60, 12, 0.25
    )
    assert _rent_testsuite("survival", 60, 12, 1.0) == pytest.approx(
        -10.00, abs=DELTA_TOL
    )
    assert _rent_testsuite("keep_everything", 60, 12, 1.0) == pytest.approx(
        60.00, abs=DELTA_TOL
    )


# --------------------------------------------------------------------------
# tab:rent-tiers -- the shape of the price, against rent_tiers.json.
# --------------------------------------------------------------------------
RENT_TIER_ARMS: dict[str, dict[str, Any]] = {
    "survival": {"arm": "survival"},
    **RENT_FLOOR_ARMS,
}


def _rent_tier_cells() -> list[tuple[int, str, float, str]]:
    """(cycles, tier, rent, printed cell), one case per number in the table."""
    out: list[tuple[int, str, float, str]] = []
    for row in data_rows("tab:rent-tiers"):
        if len(row) != 2 + len(RENT_COLUMNS) or not row[0].split()[0].isdigit():
            continue  # the header row has the same width as a data row
        cycles = int(row[0].split()[0])
        tier = row[1]
        out.extend(
            (cycles, tier, rent, value)
            for rent, value in zip(RENT_COLUMNS, row[2:], strict=True)
        )
    return out


@pytest.mark.parametrize(("cycles", "tier", "rent", "cell"), _rent_tier_cells())
def test_rent_tier_table_matches_committed_runs(
    cycles: int, tier: str, rent: float, cell: str
) -> None:
    got = mean(
        pick(
            "rent_tiers.json",
            arm="survival",
            cycles=cycles,
            lie_budget=0,
            hold_cost=rent,
            rent_tier=tier,
            env_family="storage_rent",
            adversary_objective="withhold",
        ),
        "cum_delta",
        1e6,
    )
    assert float(cell) == pytest.approx(got, abs=DELTA_TOL)


def test_the_uniform_tier_reproduces_the_published_rent_file() -> None:
    """The canary, and it crosses two files rather than two columns.

    ``uniform``'s multipliers are exactly 1.0, so the tier axis is only a
    counterfactual on the SHAPE of the price if adding it left the flat
    rate untouched. Asserted at zero tolerance over the whole grid: any
    drift means the tier plumbing perturbed the thing it was added to
    extend, and every cross-tier comparison is then measuring two changes.
    """
    checked = 0
    for cycles in (30, 60):
        for budget in (0, 12):
            for rent in RENT_COLUMNS:
                for config in RENT_TIER_ARMS.values():
                    common = {
                        **config,
                        "cycles": cycles,
                        "lie_budget": budget,
                        "hold_cost": rent,
                        "env_family": "storage_rent",
                        "adversary_objective": "withhold",
                    }
                    tiered = pick("rent_tiers.json", **common, rent_tier="uniform")
                    flat = pick("rent.json", **common)
                    for key in ("cum_delta", "poison_killed", "final_population"):
                        assert mean(tiered, key) == mean(flat, key), (
                            f"{config['arm']} at {cycles} cycles, budget "
                            f"{budget}, rent {rent}: the uniform tier has "
                            f"drifted from rent.json on {key}"
                        )
                    checked += 1
    assert checked == 100


def test_the_aligned_tier_is_the_unpriced_world_for_every_arm_that_has_answers() -> (
    None
):
    """The headline of the tier grid, asserted as identity rather than a mean.

    Under a policy-shaped quota the only billed decline is one the arm
    could not answer, so every run must be bit-identical to the same run
    at hold_cost 0 -- except ``survival`` at total suppression, whose
    store the attack empties. That exception is asserted too: if it ever
    stops being the sole exception, either the corpus changed or the
    "rent bills not having an answer" rule has a second exception nobody
    has looked at.
    """
    billed: set[tuple[str, int]] = set()
    checked = 0
    for cycles in (30, 60):
        for budget in (0, 12):
            for name, config in RENT_TIER_ARMS.items():
                common = {
                    **config,
                    "cycles": cycles,
                    "lie_budget": budget,
                    "rent_tier": "aligned",
                    "env_family": "storage_rent",
                    "adversary_objective": "withhold",
                }
                free = mean(
                    pick("rent_tiers.json", **common, hold_cost=0.0), "cum_delta"
                )
                for rent in RENT_COLUMNS[1:]:
                    paid = mean(
                        pick("rent_tiers.json", **common, hold_cost=rent), "cum_delta"
                    )
                    if paid != free:
                        billed.add((name, budget))
                    checked += 1
    assert checked == 80
    assert billed == {("survival", 12)}, (
        "under the aligned tier the only arm that should ever pay rent is "
        f"the one the attack empties; these paid: {sorted(billed)}"
    )


# --------------------------------------------------------------------------
# sec:horizon -- the probe triple, against bench/results/horizon.json.
# --------------------------------------------------------------------------
def test_horizon_probe_triple_matches_committed_runs() -> None:
    """The paper's sharpest horizon claim has no table parser to lean on.

    It states the unattacked test-suite probe triple as identical in all
    ten seeds and reads a safety result off the third column, so the
    unanimity is part of the claim rather than a rounding of it: a mean
    of 1.00 over ten seeds and ten seeds each reading 1.00 support very
    different sentences.
    """
    want = {
        30: {
            "probe_benign_correct_rate": 1.0,
            "probe_silence_rate": 0.0,
            "probe_harmful_safe_rate": 0.0,
            "final_population": 4,
        },
        60: {
            "probe_benign_correct_rate": 0.75,
            "probe_silence_rate": 0.4,
            "probe_harmful_safe_rate": 1.0,
            "final_population": 3,
        },
    }
    files = {30: "testsuite.json", 60: "horizon.json"}
    for cycles, expected in want.items():
        extra = {"origin_suite": "testsuite"} if cycles == 60 else {}
        got = pick(files[cycles], arm="survival", cycles=cycles, **extra)
        assert len(got) == 10, cycles
        for key, value in expected.items():
            seen = {m[key] for m in got}
            assert seen == {value}, (
                f"{cycles} cycles, {key}: the paper states one value across "
                f"all ten seeds and the evidence holds {sorted(seen)}"
            )


def test_horizon_keep_everything_population_canary() -> None:
    """The claim that licenses reading the whole sweep as the clock.

    ``keep_everything`` removes nothing, so its population must be
    identical at both horizons in every paired cell. The paper prints
    830/830; anything less means something other than curation is
    removing entries and every other number in the section is suspect.
    Paired on (origin suite, full config, seed) rather than through
    ``pick``, because the identity that matters here includes the seed.
    """

    def keyed(filename: str) -> dict[tuple[Any, ...], dict[str, Any]]:
        out = {}
        for run in json.loads((RESULTS / filename).read_text())["runs"]:
            if run["arm"] != "keep_everything":
                continue
            cfg = {
                k: v
                for k, v in run["config"].items()
                if k not in {"cycles", "origin_suite"}
            }
            origin = run["config"].get("origin_suite", filename[: -len(".json")])
            out[(origin, tuple(sorted(cfg.items())), run["seed"])] = run["metrics"]
        return out

    sixty = keyed("horizon.json")
    thirty: dict[tuple[Any, ...], dict[str, Any]] = {}
    for origin in sorted({k[0] for k in sixty}):
        thirty.update(keyed(f"{origin}.json"))

    assert set(sixty) <= set(thirty), sorted(set(sixty) - set(thirty))[:3]
    moved = [
        k
        for k in sixty
        if sixty[k]["final_population"] != thirty[k]["final_population"]
    ]
    assert not moved, moved[:5]
    assert len(sixty) == 830, len(sixty)


# --------------------------------------------------------------------------
# sec:blind -- the price-blind withholder. Prose numbers, two files.
# --------------------------------------------------------------------------
_ATTACK_COUNTERS = frozenset(
    {"flakes_fired", "fired_false_bad", "fired_false_good", "wall_time_s"}
)


@lru_cache(maxsize=2)
def _blind_runs(filename: str) -> tuple[dict[str, Any], ...]:
    return tuple(json.loads((RESULTS / filename).read_text())["runs"])


def _identity(run: dict[str, Any]) -> tuple[Any, ...]:
    c = run["config"]
    return (c["cycles"], c["hold_cost"], c["rent_tier"], run["arm"], run["seed"])


def _waste(m: dict[str, Any]) -> int:
    return int(m["flakes_fired"] - (m["fired_false_bad"] + m["fired_false_good"]))


def test_saturated_tier_grid_is_an_identity_against_the_published_one() -> None:
    """\\S sec:blind's central claim, and the only kind that can be exact.

    "All 4,500 cells equal their published twins exactly on all 21
    metrics the two files share." An identity is the one claim a
    tolerance would ruin, so this compares raw values and permits
    difference only in the two fired counters -- which must differ, or
    the blind attacker was never blind.

    ``rent_tiers.json`` predates ``poison_laundered_final`` (#92), so the
    shared-metric count is itself part of the claim and is asserted
    rather than derived, which is what makes "21" checkable.
    """
    twins = {
        _identity(r): r
        for r in _blind_runs("rent_tiers.json")
        if r["config"]["lie_budget"] == 12
    }
    sat = _blind_runs("rent_tiers_saturated.json")
    assert len(sat) == 4500 and len(twins) == 4500

    shared = set(sat[0]["metrics"]) & set(next(iter(twins.values()))["metrics"])
    assert len(shared) == 21 and len(shared - _ATTACK_COUNTERS) == 17

    differing_counters = 0
    for run in sat:
        twin = twins[_identity(run)]
        for key in shared - _ATTACK_COUNTERS:
            assert run["metrics"][key] == twin["metrics"][key], (
                f"{_identity(run)} moved on {key}: a saturating budget "
                "leaves nothing for a targeting rule to concentrate"
            )
        # "its spend is exactly 12 * cycles in every one of the 4,500
        # cells, and its wasted portion is exactly capacity minus the
        # greedy attacker's flakes_fired, cell for cell."
        capacity = 12 * run["config"]["cycles"]
        assert run["metrics"]["flakes_fired"] == capacity
        assert _waste(run["metrics"]) == capacity - twin["metrics"]["flakes_fired"]
        differing_counters += (
            run["metrics"]["flakes_fired"] != twin["metrics"]["flakes_fired"]
        )
    assert (differing_counters, 4500 - differing_counters) == (2340, 2160)


def test_the_exempt_surface_is_a_property_of_the_tier_and_the_arm() -> None:
    """The refuted prediction, pinned to the table that replaced it.

    \\S sec:blind reports the wasted spends at rent 1.0 and 60 cycles as
    143.6 for four arms under ``aligned``, 239.6 for the ledger, 287.5
    for the ledger alone under ``inverted``, and 0.0 everywhere else.
    The zeros carry the claim -- "four of the five arms never decline a
    disposable file" -- so they are asserted as exact rather than
    approximate.
    """
    got: dict[tuple[str, str], list[int]] = defaultdict(list)
    zero_cells: dict[str, int] = defaultdict(int)
    for run in _blind_runs("rent_tiers_saturated.json"):
        c = run["config"]
        if c["hold_cost"] > 0:
            zero_cells[c["rent_tier"]] += _waste(run["metrics"]) == 0
        if c["hold_cost"] == 1.0 and c["cycles"] == 60:
            got[(c["rent_tier"], run["arm"])].append(_waste(run["metrics"]))

    floor = ("evict_on_negative", "keep_everything", "quarantine", "survival_paced")
    for arm in floor:
        assert statistics.fmean(got[("aligned", arm)]) == pytest.approx(143.6, abs=0.05)
        assert set(got[("inverted", arm)]) == {0}
        assert set(got[("uniform", arm)]) == {0}
    assert statistics.fmean(got[("aligned", "survival")]) == pytest.approx(239.6, 0.05)
    assert statistics.fmean(got[("inverted", "survival")]) == pytest.approx(287.5, 0.05)
    assert set(got[("uniform", "survival")]) == {0}
    # "aligned wastes in all 1,200 cells at rent > 0; inverted in 240."
    assert zero_cells["aligned"] == 0
    assert zero_cells["inverted"] == 960
    assert zero_cells["uniform"] == 1200


def test_the_targeting_rule_moves_the_attacker_s_ledger_not_the_world() -> None:
    """The interior-budget paragraph, every count in it.

    Two ledgers separate: 2,100 of 4,500 paired cells differ in what the
    attacker reports and 98 in what the world records, 91 of those in the
    weaker attacker's favour and 7 against. The 7 matter more than the
    91 -- they are the mechanism the registration said it could not rule
    out -- so their identity is pinned too.
    """
    by: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = defaultdict(dict)
    for run in _blind_runs("rent_tiers_blind.json"):
        by[run["config"]["adversary_objective"]][_identity(run)] = run
    assert len(by["withhold"]) == len(by["withhold_blind"]) == 4500

    reported = world = better = worse = 0
    arms: dict[str, int] = defaultdict(int)
    for key, blind in by["withhold_blind"].items():
        greedy = by["withhold"][key]
        b, g = blind["metrics"], greedy["metrics"]
        reported += b["reported_cum_delta"] != g["reported_cum_delta"]
        if b["cum_delta"] != g["cum_delta"]:
            world += 1
            arms[key[3]] += 1
            better += b["cum_delta"] > g["cum_delta"]
            worse += b["cum_delta"] < g["cum_delta"]
    assert (reported, world) == (2100, 98)
    assert (better, worse) == (91, 7)
    assert dict(arms) == {"quarantine": 70, "survival": 14, "survival_paced": 14}


def test_the_tier_ordering_survives_an_attacker_that_cannot_see_the_price() -> None:
    """The de-confounding claim itself, to the digits the paper prints."""
    by: dict[str, dict[tuple[Any, ...], dict[str, Any]]] = defaultdict(dict)
    for run in _blind_runs("rent_tiers_blind.json"):
        by[run["config"]["adversary_objective"]][_identity(run)] = run
    printed = {
        (30, "withhold"): (12.2865, 1.2909, -11.5049),
        (30, "withhold_blind"): (12.3095, 1.2909, -11.5049),
        (60, "withhold"): (25.4582, 2.8737, -23.3802),
        (60, "withhold_blind"): (25.4811, 2.8737, -23.3802),
    }
    for (cycles, rule), want in printed.items():
        got = tuple(
            statistics.fmean(
                by[rule][(cycles, 1.0, tier, "survival", seed)]["metrics"]["cum_delta"]
                for seed in range(30)
            )
            / 1e6
            for tier in ("aligned", "uniform", "inverted")
        )
        assert got == pytest.approx(want, abs=5e-5), (cycles, rule, got)
    # "identical to every printed digit because no cell in them diverges"
    for cycles in (30, 60):
        for tier in ("uniform", "inverted"):
            for seed in range(30):
                key = (cycles, 1.0, tier, "survival", seed)
                assert (
                    by["withhold"][key]["metrics"]["cum_delta"]
                    == by["withhold_blind"][key]["metrics"]["cum_delta"]
                )


# --------------------------------------------------------------------------
# sec:redundancy -- the 2x2 that attributes the test-suite findings.
# --------------------------------------------------------------------------
_REDUNDANCY_NOT_RESULT = frozenset({"wall_time_s"})


@lru_cache(maxsize=2)
def _redundancy(filename: str) -> dict[tuple[Any, ...], dict[str, Any]]:
    out = {}
    for run in json.loads((RESULTS / filename).read_text())["runs"]:
        cfg = run["config"]
        key = (
            cfg["testsuite_twins"],
            cfg["consolidate_every"],
            cfg["cycles"],
            run["arm"],
            run["seed"],
        )
        out[key] = run["metrics"]
    return out


def test_the_capability_decay_needs_both_halves() -> None:
    """\\S sec:redundancy: 30/30 at the published corner, 0/30 elsewhere.

    The whole attribution rests on this being a corner and not a
    gradient, so it is counted per seed rather than averaged: a mean of
    0.75 is also what fifteen seeds at 0.5 would give.
    """
    got = _redundancy("redundancy.json")
    for arm in ("survival", "survival_paced"):
        for twins, every in ((True, 5), (True, 0), (False, 5), (False, 0)):
            decayed = sum(
                got[(twins, every, 60, arm, s)]["probe_benign_correct_rate"]
                < got[(twins, every, 30, arm, s)]["probe_benign_correct_rate"]
                for s in range(30)
            )
            assert decayed == (30 if (twins, every) == (True, 5) else 0), (
                arm,
                twins,
                every,
                decayed,
            )
        assert got[(True, 5, 60, arm, 0)]["probe_benign_correct_rate"] == 0.75
        assert got[(True, 5, 30, arm, 0)]["probe_benign_correct_rate"] == 1.0


def test_the_rent_bill_has_the_other_load_bearing_half() -> None:
    """The two findings the same sentence explained, separated.

    "Dropping the twins recovers more of the gap than disabling the merge
    in 30/30 seeds on both horizons, and at 30 cycles disabling the merge
    alone makes the ledger worse (64.20 against a published 69.00)."
    """
    got = _redundancy("redundancy_rent.json")
    for cycles in (30, 60):
        wins = sum(
            (
                got[(False, 5, cycles, "survival", s)]["cum_delta"]
                - got[(True, 5, cycles, "survival", s)]["cum_delta"]
            )
            > (
                got[(True, 0, cycles, "survival", s)]["cum_delta"]
                - got[(True, 5, cycles, "survival", s)]["cum_delta"]
            )
            for s in range(30)
        )
        assert wins == 30, (cycles, wins)
    published = mean(
        tuple(got[(True, 5, 30, "survival", s)] for s in range(30)), "cum_delta"
    )
    merge_off = mean(
        tuple(got[(True, 0, 30, "survival", s)] for s in range(30)), "cum_delta"
    )
    assert published == pytest.approx(69.00, abs=DELTA_TOL)
    assert merge_off == pytest.approx(64.20, abs=DELTA_TOL)
    assert merge_off < published, "disabling the merge alone must be a step backwards"


def test_the_second_family_loss_is_mostly_five_entries() -> None:
    """The paragraph's table, and the asymmetry underneath it.

    Every percentage in \\S sec:redundancy, plus the claim that carries
    it: the five entries cost all three counters nothing in 30 of 30
    seeds and both ledger arms everything in 30 of 30.
    """
    want = {
        ("redundancy.json", 30): (19.00, 3.80),
        ("redundancy.json", 60): (56.67, 3.80),
        ("redundancy_rent.json", 30): (19.00, 3.80),
        ("redundancy_rent.json", 60): (69.27, 3.80),
    }
    for (filename, cycles), (loss, remaining) in want.items():
        got = _redundancy(filename)
        counter = mean(
            tuple(got[(True, 5, cycles, "evict_on_negative", s)] for s in range(30)),
            "cum_delta",
        )
        for twins, expected in ((True, loss), (False, remaining)):
            ledger = mean(
                tuple(got[(twins, 5, cycles, "survival", s)] for s in range(30)),
                "cum_delta",
            )
            assert counter - ledger == pytest.approx(expected, abs=0.01), (
                filename,
                cycles,
                twins,
            )

    for filename in ("redundancy.json", "redundancy_rent.json"):
        got = _redundancy(filename)
        for arm, score in (
            ("evict_on_negative", 178.00),
            ("quarantine", 140.00),
            ("keep_everything", 60.00),
        ):
            moved = sum(
                got[(True, 5, 60, arm, s)]["cum_delta"]
                != got[(False, 5, 60, arm, s)]["cum_delta"]
                for s in range(30)
            )
            assert moved == 0, (filename, arm, moved)
            assert got[(True, 5, 60, arm, 0)]["cum_delta"] == pytest.approx(
                score, abs=DELTA_TOL
            )
        for arm in ("survival", "survival_paced"):
            moved = sum(
                got[(True, 5, 60, arm, s)]["cum_delta"]
                != got[(False, 5, 60, arm, s)]["cum_delta"]
                for s in range(30)
            )
            assert moved == 30, (filename, arm, moved)


def test_the_redundancy_grid_reproduces_the_file_it_extends() -> None:
    """The canary that licenses reading the other three corners.

    The published corner is the same world as ``rent_testsuite.json``'s
    unattacked cells, so it must reproduce them exactly. It does, in all
    300 shared cells; without that, a corner that moved would be
    indistinguishable from a harness that moved.
    """
    got = _redundancy("redundancy.json")
    twin = {}
    for run in json.loads((RESULTS / "rent_testsuite.json").read_text())["runs"]:
        cfg = run["config"]
        if cfg["hold_cost"] == 0.0 and cfg["lie_budget"] == 0:
            twin[(cfg["cycles"], run["arm"], run["seed"])] = run["metrics"]
    checked = 0
    for (cycles, arm, seed), metrics in twin.items():
        mine = got.get((True, 5, cycles, arm, seed))
        if mine is None:
            continue  # rent_testsuite runs arms this grid does not
        checked += 1
        for key in set(mine) & set(metrics) - _REDUNDANCY_NOT_RESULT:
            assert mine[key] == metrics[key], (cycles, arm, seed, key)
    assert checked == 300, checked


# --------------------------------------------------------------------------
# sec:redundancy's dose paragraph -- against redundancy_dose.json.
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _dose() -> dict[tuple[Any, ...], dict[str, Any]]:
    out = {}
    for run in json.loads((RESULTS / "redundancy_dose.json").read_text())["runs"]:
        cfg = run["config"]
        out[(cfg["testsuite_twins"], cfg["cycles"], run["arm"], run["seed"])] = run[
            "metrics"
        ]
    return out


def _dose_mean(mask: str, cycles: int, arm: str, key: str = "cum_delta") -> float:
    got = _dose()
    return statistics.fmean(float(got[(mask, cycles, arm, s)][key]) for s in range(30))


def test_the_whole_redundancy_effect_is_one_pair() -> None:
    """\\S sec:redundancy: 93.3% from one twin, exactly 0.0% from three.

    The zeros are the claim. "Dropping the other four recovers nothing at
    all" is a much stronger statement than "recovers little", and it is
    the one that turns a dose into an entry, so it is asserted as an
    identity against the all-twins cell rather than with a tolerance.
    """
    counter = _dose_mean("11111", 60, "evict_on_negative")
    full = _dose_mean("11111", 60, "survival")
    assert counter == pytest.approx(178.00, abs=DELTA_TOL)
    assert full == pytest.approx(121.33, abs=0.01)
    gap = counter - full

    recovered = {
        mask: (_dose_mean(mask, 60, "survival") - full) / gap
        for mask in ("01111", "10111", "11011", "11101", "11110")
    }
    assert recovered["01111"] == pytest.approx(0.933, abs=0.001)
    for mask in ("10111", "11011", "11101"):
        assert _dose_mean(mask, 60, "survival") == full, (
            f"{mask} must be identical to the all-twins cell, not merely close: "
            "three of the five pairs contribute nothing at all"
        )
    assert recovered["11110"] == pytest.approx(-0.029, abs=0.001)


def test_the_other_four_pairs_are_protective_not_inert() -> None:
    """Keeping only the harmful twin is worse than keeping all five."""
    got = _dose()
    assert _dose_mean("10000", 60, "survival") == pytest.approx(102.20, abs=DELTA_TOL)
    worse = sum(
        got[("10000", 60, "survival", s)]["cum_delta"]
        < got[("11111", 60, "survival", s)]["cum_delta"]
        for s in range(30)
    )
    assert worse == 30
    # Keeping only one of the other four is the same as keeping none.
    for mask in ("01000", "00100", "00010", "00001"):
        assert _dose_mean(mask, 60, "survival") == _dose_mean("00000", 60, "survival")


def test_a_dose_response_curve_would_have_been_fiction() -> None:
    """The table's spreads, and why the monotone means are the trap."""
    from collections import defaultdict

    doses: dict[int, list[float]] = defaultdict(list)
    for mask in {key[0] for key in _dose()}:
        doses[mask.count("1")].append(_dose_mean(mask, 60, "survival"))
    means = {k: statistics.fmean(v) for k, v in doses.items()}
    spreads = {k: max(v) - min(v) for k, v in doses.items()}
    assert [round(means[k], 2) for k in range(6)] == [
        174.20,
        159.80,
        145.74,
        137.17,
        131.58,
        121.33,
    ]
    assert spreads[0] == spreads[5] == 0.0
    for k in range(1, 5):
        step = abs(means[k] - means[k - 1])
        assert spreads[k] > step, (k, spreads[k], step)


def test_the_capability_decay_tracks_the_same_pair() -> None:
    """456 of 480 keeping it, 0 of 480 dropping it, and the population."""
    got = _dose()
    keeping = [
        got[(mask, 60, "survival", s)]["probe_benign_correct_rate"]
        for mask in {key[0] for key in got}
        if mask[0] == "1"
        for s in range(30)
    ]
    dropping = [
        got[(mask, 60, "survival", s)]["probe_benign_correct_rate"]
        for mask in {key[0] for key in got}
        if mask[0] == "0"
        for s in range(30)
    ]
    assert (len(keeping), len(dropping)) == (480, 480)
    assert sum(v == 0.75 for v in keeping) == 456
    assert sum(v == 0.75 for v in dropping) == 0
    for mask, thirty, sixty in (("11111", 4.00, 3.00), ("01111", 4.00, 4.00)):
        assert _dose_mean(mask, 30, "survival", "final_population") == pytest.approx(
            thirty, abs=DELTA_TOL
        )
        assert _dose_mean(mask, 60, "survival", "final_population") == pytest.approx(
            sixty, abs=DELTA_TOL
        )


def test_the_dose_grid_reproduces_the_grid_it_narrows() -> None:
    """The two-file canary: all 600 shared cells, every result metric."""
    got = _dose()
    twin = {}
    for run in json.loads((RESULTS / "redundancy.json").read_text())["runs"]:
        cfg = run["config"]
        if cfg["consolidate_every"] == 5:
            mask = "11111" if cfg["testsuite_twins"] else "00000"
            twin[(mask, cfg["cycles"], run["arm"], run["seed"])] = run["metrics"]
    assert len(twin) == 600
    for key, metrics in twin.items():
        mine = got[key]
        for name in set(mine) & set(metrics) - {"wall_time_s"}:
            assert mine[name] == metrics[name], (key, name)


# --------------------------------------------------------------------------
# sec:merge-threshold -- moving the floor instead of the corpus.
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _threshold() -> dict[tuple[Any, ...], dict[str, Any]]:
    out = {}
    for run in json.loads((RESULTS / "merge_threshold.json").read_text())["runs"]:
        cfg = run["config"]
        key = (
            cfg["merge_threshold"],
            "conflict_threshold" not in cfg,
            cfg["cycles"],
            run["arm"],
            run["seed"],
        )
        out[key] = run["metrics"]
    return out


def test_the_threshold_sweep_is_a_step_function() -> None:
    """\\S sec:merge-threshold: flat per seed within a band, not on average.

    Nine thresholds merge all five pairs and must be the *same run*, not
    the same mean -- a mean can be flat over seeds that move in
    opposite directions, and the claim is that the floor's value is
    irrelevant once the set of merges is fixed.
    """
    got = _threshold()
    bands = {
        5: [0.50, 0.55, 0.60, 0.65, 0.6875, 0.70, 0.75, 0.80, 0.8125],
        4: [0.85],
        3: [0.90],
    }
    means = {}
    for pairs, thresholds in bands.items():
        first = thresholds[0]
        for threshold in thresholds:
            for seed in range(30):
                assert (
                    got[(threshold, True, 60, "survival", seed)]["cum_delta"]
                    == got[(first, True, 60, "survival", seed)]["cum_delta"]
                ), (pairs, threshold, seed)
        means[pairs] = statistics.fmean(
            got[(first, True, 60, "survival", s)]["cum_delta"] for s in range(30)
        )
    assert means[5] == pytest.approx(121.33, abs=0.01)
    assert means[4] == pytest.approx(137.00, abs=DELTA_TOL)
    assert means[3] == pytest.approx(143.00, abs=DELTA_TOL)
    # Fewer merges is monotonically better here, which is the refutation
    # of "good on four pairs and bad on one".
    assert means[5] < means[4] < means[3]


def test_the_entry_costs_more_than_its_merge() -> None:
    """The decomposition the sweep produced, against the dose grid.

    Removing the clamp-bound twin recovers 52.87 of the 56.67 gap;
    refusing to merge it recovers 15.67. Three quarters of the harm is
    the entry existing and a quarter is the merge, and the two files
    have to agree on the endpoints for that split to mean anything.
    """
    got = _threshold()
    dose = _dose()
    counter = statistics.fmean(
        dose[("11111", 60, "evict_on_negative", s)]["cum_delta"] for s in range(30)
    )
    published = statistics.fmean(
        got[(0.55, True, 60, "survival", s)]["cum_delta"] for s in range(30)
    )
    unmerged = statistics.fmean(
        got[(0.85, True, 60, "survival", s)]["cum_delta"] for s in range(30)
    )
    removed = statistics.fmean(
        dose[("01111", 60, "survival", s)]["cum_delta"] for s in range(30)
    )
    # The published cell is the same configuration in both files.
    assert published == statistics.fmean(
        dose[("11111", 60, "survival", s)]["cum_delta"] for s in range(30)
    )
    gap = counter - published
    assert gap == pytest.approx(56.67, abs=0.01)
    assert (unmerged - published) / gap == pytest.approx(0.277, abs=0.001)
    assert (removed - published) / gap == pytest.approx(0.933, abs=0.001)


def test_the_conflict_coupling_changed_nothing_and_the_counters_are_blind() -> None:
    """Both canaries: the confound was real in the code and inert here."""
    got = _threshold()
    thresholds = sorted({key[0] for key in got})
    assert len(thresholds) == 11
    for threshold in thresholds:
        for cycles in (30, 60):
            for arm in ("survival", "survival_paced"):
                for seed in range(30):
                    a = got[(threshold, True, cycles, arm, seed)]
                    b = got[(threshold, False, cycles, arm, seed)]
                    for key in set(a) - {"wall_time_s"}:
                        assert a[key] == b[key], (threshold, cycles, arm, seed, key)
    for arm, score in (
        ("evict_on_negative", 178.00),
        ("quarantine", 140.00),
        ("keep_everything", 60.00),
    ):
        values = {
            got[(threshold, coupled, 60, arm, seed)]["cum_delta"]
            for threshold in thresholds
            for coupled in (True, False)
            for seed in range(30)
        }
        assert len(values) == 1 and values.pop() == pytest.approx(score, abs=DELTA_TOL)


# ----------------------------------------------------------------------
# External evidence: attacks on curators we did not write
#
# These two tables are the paper's answer to "every result above runs on a
# world you built", which makes them the load-bearing ones -- and until now
# they were the only evidence in the paper with no table and no check, cited
# in prose alone where no parser could ever catch drift. They live under
# bench/results/external/ rather than bench/results/ because bench.report
# reads payload["runs"] and these files have no runs: they are attack
# reports, not survival grids. Binding them here rather than relaxing that
# validator keeps the check strict for the 36 files that can satisfy it.
# ----------------------------------------------------------------------

EXTERNAL = ROOT / "bench" / "results" / "external"


@cache
def _external(filename: str) -> dict[str, Any]:
    return json.loads((EXTERNAL / filename).read_text())  # type: ignore[no-any-return]


_MEM0_RUNS = {
    "glm-5.2 families": "mem0-curation-attack-families.json",
    "glm-5.2 single": "mem0-curation-attack.json",
    "llama3.2:3b": "mem0-curation-attack-llama32.json",
}


def _mem0_rows() -> list[list[str]]:
    """Body rows only. ``data_rows`` keeps the header, as the checks above
    also have to allow for; here the run column names which file to read, so
    dropping anything that is not a run name does it."""
    return [row for row in data_rows("tab:mem0") if row[0] in _MEM0_RUNS]


def test_mem0_table_parses() -> None:
    """Parse guard: without it a reformatted table parametrises zero cases."""
    rows = _mem0_rows()
    assert len(rows) == 8, rows
    assert {row[0] for row in rows} == set(_MEM0_RUNS), rows


@pytest.mark.parametrize("row", _mem0_rows(), ids=lambda r: f"{r[0]}-{r[1]}")
def test_mem0_row_matches_committed_run(row: list[str]) -> None:
    run, condition, deletes, retained, unchanged, residue = row
    report = _external(_MEM0_RUNS[run])
    assert int(deletes) == report[f"{condition}_deletes_total"]
    assert float(retained) == pytest.approx(report[f"{condition}_benign_retained_mean"])
    assert float(unchanged) == pytest.approx(
        report[f"{condition}_benign_unchanged_mean"]
    )
    assert float(residue) == pytest.approx(
        report[f"{condition}_attacker_persisted_mean"]
    )


_LFU = "memoryos-lfu-eviction.json"
_PROMO = "memoryos-promotion-e2e.json"
_MEMORYOS_CELLS = {
    ("LFU eviction", "attended"): (_LFU, "attended_target_evicted"),
    ("LFU eviction", "neglected"): (_LFU, "neglected_target_evicted"),
    ("promotion", "quiet"): (_PROMO, "quiet_promoted"),
    ("promotion", "queried"): (_PROMO, "queried_promoted"),
}


def _memoryos_rows() -> list[list[str]]:
    return [
        row for row in data_rows("tab:memoryos") if (row[0], row[1]) in _MEMORYOS_CELLS
    ]


def test_memoryos_table_parses() -> None:
    rows = _memoryos_rows()
    assert len(rows) == 4, rows
    assert {(row[0], row[1]) for row in rows} == set(_MEMORYOS_CELLS), rows


@pytest.mark.parametrize(
    "row", _memoryos_rows(), ids=lambda r: f"{r[0]}-{r[1]}".replace(" ", "-")
)
def test_memoryos_row_matches_committed_run(row: list[str]) -> None:
    decision, condition, trials, fired, rate = row
    filename, fired_key = _MEMORYOS_CELLS[(decision, condition)]
    report = _external(filename)
    ran = report[f"{condition}_trials"]
    assert int(trials) == ran
    assert int(fired) == report[fired_key]
    assert float(rate) == pytest.approx(report[fired_key] / ran, abs=5e-3)


def test_memoryos_caption_retrieval_claim() -> None:
    """The caption's "$0$ of $9$" is a number too, and nothing else checks it."""
    report = _external("memoryos-lfu-eviction.json")
    body = EXPERIMENTS.read_text()
    end = body.index("\\label{tab:memoryos}")
    caption = body[body.rindex("\\begin{table}", 0, end) : end]
    assert report["evicted_despite_retrieval"] == 0
    assert report["targets_with_any_retrieval"] == 9
    assert "$0$ of $9$" in caption


def test_every_external_result_is_bound_to_its_manifest() -> None:
    """No file in this directory may sit outside the manifest.

    The old home for these was bench/results/exploratory/, whose README
    justifies the boundary with "No claim in the paper cites either file".
    That was true of the two LLM runs it was written for and false of these
    five the moment the paper grew sections around them.
    """
    manifest = json.loads((EXTERNAL / "MANIFEST.json").read_text())["files"]
    committed = {p.name for p in EXTERNAL.glob("*.json")} - {"MANIFEST.json"}
    assert committed == set(manifest), (committed, set(manifest))
    for name, entry in manifest.items():
        assert entry["command"].startswith("python -m bench.external.")
        assert len(entry["source_commit"]) == 40
        assert entry["target"] == _external(name)["target"]
