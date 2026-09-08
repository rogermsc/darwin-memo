"""Generate the paper's figures from committed evidence, not by hand.

    python -m bench.figures --check     # fail if the committed .tex is stale
    python -m bench.figures --write     # regenerate

The paper had nine tables and no figures, and its central result -- that
mechanisms separate under a curation-targeted adversary, and that the ones
which keep capability do it by never removing anything -- is exactly the
result a table hides. Two quantities have to be read *jointly* to see it, and
``tab:adversary`` prints one of them in cells and leaves the other in prose.

A figure drawn by hand would be a number that does not trace to the evidence,
which this repo has been bitten by. So the coordinates are emitted from
``bench/results/adversary.json`` by this module, the output is committed, and
``--check`` fails if the two ever disagree. Stdlib only, like the rest of the
harness: the output is a pgfplots axis, and TeX does the drawing.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

RESULTS = Path(__file__).resolve().parent / "results"
FIGURES = Path(__file__).resolve().parent.parent / "paper" / "figures"
ADVERSARY_FIGURE = FIGURES / "adversary.tex"

# Which run group each plotted series is, keyed by the full identity so a new
# config dimension cannot be silently averaged in. Same rule as the table
# guards: ``evict_on_negative`` exists at two strike counts, and a mean over
# both is a curve that no arm ever walked.
SERIES: tuple[tuple[str, str, dict[str, Any]], ...] = (
    ("survival", "ledger", {"arm": "survival", "strikes": None, "suspend": None}),
    ("evict1", "evict-on-negative", {"arm": "evict_on_negative", "strikes": 1}),
    ("consec2", "consecutive $k{=}2$", {"arm": "evict_consecutive", "strikes": 2}),
    ("quarantine", "quarantine $m{=}3$", {"arm": "quarantine", "suspend": 3}),
    ("bandit", "bandit", {"arm": "policy_bandit"}),
    ("keep", "keep everything", {"arm": "keep_everything"}),
)
STYLE = {
    "survival": "very thick, mark=*",
    "evict1": "mark=square, densely dashed",
    "consec2": "mark=triangle, densely dashed",
    "quarantine": "mark=diamond, densely dotted",
    "bandit": "mark=o, dashdotted",
    "keep": "mark=x, loosely dotted",
}


def _groups(filename: str) -> dict[tuple[tuple[str, Any], ...], list[dict[str, Any]]]:
    out: dict[tuple[tuple[str, Any], ...], list[dict[str, Any]]] = defaultdict(list)
    for run in json.loads((RESULTS / filename).read_text())["runs"]:
        identity = {"arm": run["arm"], **run.get("config", {})}
        out[tuple(sorted(identity.items()))].append(run["metrics"])
    return out


def _series_points(want: dict[str, Any]) -> list[tuple[int, float, float]]:
    """(budget, benign capability, poison-kill rate) for one arm, budget-ordered."""
    points = []
    for identity, metrics in _groups("adversary.json").items():
        fields = dict(identity)
        if not all(fields.get(k) == v for k, v in want.items()):
            continue
        points.append(
            (
                int(fields["lie_budget"]),
                statistics.fmean(m["probe_benign_correct_rate"] for m in metrics),
                statistics.fmean(float(m["poison_killed"]) for m in metrics),
            )
        )
    budgets = [p[0] for p in points]
    if len(budgets) != len(set(budgets)):
        raise SystemExit(
            f"{want} matches more than one run group per budget; name the "
            "distinguishing config field rather than averaging over it."
        )
    return sorted(points)


def render() -> str:
    """The two-panel figure, as a self-contained pgfplots fragment."""
    panels = []
    for index, (title, ylabel, value) in enumerate(
        (
            ("benign capability retained", "benign capability", 1),
            ("poison-kill rate", "poison killed", 2),
        )
    ):
        plots = []
        for key, label, want in SERIES:
            coords = " ".join(
                f"({point[0]},{point[value]:.4f})" for point in _series_points(want)
            )
            plots.append(f"      \\addplot+[{STYLE[key]}] coordinates {{{coords}}};")
            # Only the left panel carries the legend; repeating it would waste
            # half the figure on a key the reader has already read.
            if index == 0:
                plots.append(f"      \\addlegendentry{{{label}}}")
        # Assembled as a list and joined, because a whitespace-only line inside
        # an axis option list is a paragraph break to TeX, and pgfplots fails
        # with "Paragraph ended before \\pgfplots@@environment@axis was
        # complete" -- which is exactly how the first draft of this broke.
        options = [
            "width=\\textwidth, height=0.78\\textwidth,",
            f"xlabel={{lies per cycle $b$}}, ylabel={{{ylabel}}},",
            "xmin=-0.3, xmax=8.3, ymin=-0.05, ymax=1.08,",
            "xtick={0,1,2,4,8}, ytick={0,0.25,0.5,0.75,1},",
            "tick label style={font=\\scriptsize},",
            "label style={font=\\small},",
            "grid=major, grid style={very thin, gray!25},",
        ]
        if index == 0:
            # The legend is exported by name and drawn once, full width, below
            # both panels. Kept inside the left axis it inflated that axis's
            # bounding box, so the two panels came out vertically misaligned
            # and the key was crammed under one of them.
            options.append(
                "legend style={font=\\scriptsize, legend columns=3, draw=none},"
            )
            options.append("legend to name=adversarylegend,")
        panels.append(
            "  \\begin{subfigure}[t]{0.48\\textwidth}\n"
            "  \\centering\n"
            "  \\begin{tikzpicture}\n"
            "    \\begin{axis}[\n"
            + "\n".join(f"      {opt}" for opt in options)
            + "\n    ]\n"
            + "\n".join(plots)
            + "\n    \\end{axis}\n"
            "  \\end{tikzpicture}\n"
            "  \\caption{" + title + "}\n"
            "  \\end{subfigure}"
        )
    return (
        "% GENERATED by `python -m bench.figures --write` from\n"
        "% bench/results/adversary.json. Do not edit: `--check` runs in CI and\n"
        "% fails if this file and the committed runs disagree.\n"
        "\\begin{figure*}[t]\n"
        "\\centering\n" + "\n  \\hfill\n".join(panels) + "\n"
        "\n  \\par\\vspace{0.8em}\n"
        "  \\pgfplotslegendfromname{adversarylegend}\n"
        "\\caption{The curation-targeted adversary, 30 seeds, plotted as the two\n"
        "halves the result has to be read in. \\emph{Left}: benign capability\n"
        "retained. \\emph{Right}: poison-kill rate. The counters fall on the left\n"
        "panel by $b{=}1$, which is the separation the paper is about. The figure\n"
        "exists for the other half: \\texttt{keep\\_everything} traces a flat\n"
        "$1.00$ across the left panel and a flat $0.00$ across the right, and the\n"
        "bandit holds the left panel to $b{=}4$ while giving the right one away.\n"
        "A perfect capability score beside a zero defence score is abstention, not\n"
        "defence, and either panel alone hides it. Only the ledger holds both, and\n"
        "only to its published boundary between $b{=}2$ and $b{=}4$. Generated\n"
        "from committed per-seed data by \\texttt{bench/figures.py}; CI fails if\n"
        "the two disagree.}\n"
        "\\label{fig:adversary}\n"
        "\\end{figure*}\n"
    )


COUNTER_FIGURE = FIGURES / "counter_sweep.tex"
SWEEP_K: tuple[int, ...] = (1, 2, 3, 5, 8, 12, 20)
SWEEP_BUDGET = 2


def _sweep_point(arm: str, strikes: int | None, budget: int) -> tuple[float, float]:
    """(benign capability, poison-kill) for one sweep cell."""
    for identity, metrics in _groups("counter_sweep.json").items():
        fields = dict(identity)
        if fields.get("arm") != arm or int(fields.get("lie_budget", -1)) != budget:
            continue
        if strikes is not None and fields.get("strikes") != strikes:
            continue
        if strikes is None and fields.get("strikes") is not None:
            continue
        return (
            statistics.fmean(m["probe_benign_correct_rate"] for m in metrics),
            statistics.fmean(float(m["poison_killed"]) for m in metrics),
        )
    raise SystemExit(f"no counter_sweep cell for {arm} strikes={strikes} b={budget}")


def render_counter_sweep() -> str:
    """The dial as a path through the capability/kill plane.

    Two panels would show two monotone curves and hide the thing that
    matters, which is that the counter's dial moves it AROUND the corner
    rather than into it. Plotting the two axes against each other puts the
    corner on the page as a corner, with each arm's ``k`` labelled along
    its path, so "no lifetime setting is ever in the box" is something the
    reader sees rather than something we assert.
    """
    paths = []
    # Which k to label, per shape and per side. Six of the seven lifetime
    # points sit on top of each other at (0.00, 1.00), so labelling the same
    # set on both curves stacks four labels in one spot -- which is what the
    # first version did. Each shape labels only the settings that are
    # separated on its own path.
    labelled: dict[str, tuple[tuple[int, str], ...]] = {
        "evict_on_negative": ((1, "north west"), (20, "south east")),
        "evict_consecutive": ((5, "south west"), (12, "west"), (20, "north west")),
    }
    for arm, label, style in (
        ("evict_on_negative", "lifetime strikes", "mark=square, densely dashed"),
        ("evict_consecutive", "consecutive strikes", "mark=triangle, densely dotted"),
    ):
        points = [_sweep_point(arm, k, SWEEP_BUDGET) for k in SWEEP_K]
        coords = " ".join(f"({cap:.4f},{kill:.4f})" for cap, kill in points)
        paths.append(f"      \\addplot+[{style}] coordinates {{{coords}}};")
        paths.append(f"      \\addlegendentry{{{label}}}")
        for k, anchor in labelled[arm]:
            cap, kill = points[SWEEP_K.index(k)]
            paths.append(
                f"      \\node[font=\\tiny, anchor={anchor}, inner sep=2pt] at "
                f"(axis cs:{cap:.4f},{kill:.4f}) {{$k{{=}}{k}$}};"
            )
    for arm, label, style in (
        ("survival", "ledger", "only marks, mark=*, very thick"),
        ("keep_everything", "no curation", "only marks, mark=x"),
    ):
        cap, kill = _sweep_point(arm, None, SWEEP_BUDGET)
        paths.append(
            f"      \\addplot+[{style}] coordinates {{({cap:.4f},{kill:.4f})}};"
        )
        paths.append(f"      \\addlegendentry{{{label}}}")

    options = [
        "width=0.98\\columnwidth, height=0.62\\columnwidth,",
        "xlabel={benign capability retained}, ylabel={poison-kill rate},",
        "xmin=-0.05, xmax=1.12, ymin=-0.05, ymax=1.12,",
        "xtick={0,0.25,0.5,0.75,1}, ytick={0,0.25,0.5,0.75,1},",
        "tick label style={font=\\scriptsize},",
        "label style={font=\\small},",
        "grid=major, grid style={very thin, gray!25},",
        "legend style={font=\\scriptsize, at={(0.02,0.02)}, "
        "anchor=south west, draw=none, fill=none},",
    ]
    corner = (
        "      \\draw[fill=gray!12, draw=gray!45, densely dashed]\n"
        "        (axis cs:0.9,0.9) rectangle (axis cs:1.08,1.08);\n"
        "      \\node[font=\\scriptsize, gray!60, anchor=north east] at\n"
        "        (axis cs:1.07,0.885) {the corner};"
    )
    return (
        "% GENERATED by `python -m bench.figures --write` from\n"
        "% bench/results/counter_sweep.json. Do not edit: `--check` runs in CI\n"
        "% and fails if this file and the committed runs disagree.\n"
        "\\begin{figure}[t]\n"
        "\\centering\n"
        "\\begin{tikzpicture}\n"
        "  \\begin{axis}[\n"
        + "\n".join(f"    {opt}" for opt in options)
        + "\n  ]\n"
        + corner
        + "\n"
        + "\n".join(paths)
        + "\n  \\end{axis}\n"
        "\\end{tikzpicture}\n"
        "\\caption{The strike counter's dial at $b{=}2$, 30 seeds, plotted in the\n"
        "plane it has to win in. A defence must hold both axes, so the target is\n"
        "the shaded corner. Raising $k$ walks each counter rightwards --- it keeps\n"
        "more benign memory --- but the two shapes arrive differently. The\n"
        "consecutive path enters the corner at $k{=}5$ and leaves it again by\n"
        "$k{=}12$, falling down the right edge toward no curation at all: that is\n"
        "the refutation of our pre-registered prediction, and it is why the paper\n"
        "no longer claims the corner is the ledger's alone. The lifetime path\n"
        "never enters it at any $k$ we tested, staying pinned to the top edge\n"
        "because poison keeps earning lifetime blame however high the threshold.\n"
        "The ledger sits in the corner untuned. Generated from committed per-seed\n"
        "data by \\texttt{bench/figures.py}; CI fails if the two disagree.}\n"
        "\\label{fig:countersweep}\n"
        "\\end{figure}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="regenerate the figures")
    mode.add_argument("--check", action="store_true", help="fail if any is stale")
    args = parser.parse_args(argv)

    # Every figure the paper draws, each with the result file it must agree
    # with. Adding one here is all it takes for --check to guard it too.
    figures = (
        (ADVERSARY_FIGURE, "adversary.json", render),
        (COUNTER_FIGURE, "counter_sweep.json", render_counter_sweep),
    )

    if args.write:
        FIGURES.mkdir(parents=True, exist_ok=True)
        for path, _, build in figures:
            path.write_text(build())
            print(f"wrote {path}")
        return 0

    stale = False
    for path, source, build in figures:
        if not path.exists():
            print(f"{path} is missing; run --write", file=sys.stderr)
            stale = True
            continue
        if path.read_text() != build():
            print(
                f"{path} is stale: it does not match {source}. "
                "Run `python -m bench.figures --write`.",
                file=sys.stderr,
            )
            stale = True
            continue
        print(f"{path.name} matches the committed runs")
    return 1 if stale else 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
