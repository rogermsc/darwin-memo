"""Aggregate benchmark JSON into tables, and validate runs for CI."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

from .manifest import manifest_failures
from .stats import bootstrap_ci, holm_bonferroni, paired_permutation_pvalue

_REQUIRED_METRIC_KEYS = {
    "poison_killed",
    "poison_kill_cycle",
    "damage_before_kill",
    "cum_delta",
    "cum_negative_delta",
    "tail_delta_mean",
    "final_population",
    "wall_time_s",
    "reported_cum_delta",
    "flakes_marked",
    "flakes_fired",
    "fired_false_bad",
    "fired_false_good",
    "probe_harmful_safe_rate",
    "probe_benign_correct_rate",
    "probe_silence_rate",
    "paraphrase_harmful_safe_rate",
    "paraphrase_benign_grounded_rate",
    "paraphrase_silence_rate",
}

# Not every suite is a population of memory entries walking an energy
# ledger. The SWE-Bench-CL pilot records one task per row, scored by the
# official harness; the distillation arms record one trained model per
# row and time themselves in training seconds. Asking either for flake
# counters and paraphrase probes makes its evidence permanently
# unvalidatable, which is how two committed result files came to sit
# outside the reproduction script: the script listed what happened to
# pass. A suite absent here is a storage-family suite and gets the set
# above.
_SWEBENCH_SUITE = "swebench_cl_pilot"
_SUITE_REQUIRED_METRICS: dict[str, set[str]] = {
    _SWEBENCH_SUITE: {"delta", "resolved", "wall_time_s"},
    "distill": {"poison_reproduction", "good_recall", "n_train", "train_wall_s"},
    "distill_merge": {
        "poison_reproduction",
        "recall_all",
        "n_train",
        "train_wall_s",
    },
    "distill_noisy": {
        "poison_reproduction",
        "good_recall",
        "n_train",
        "train_wall_s",
    },
    # The rule arm scores generalization to held-out services, not recall of
    # what it was trained on, so it shares no metric with the suites above.
    "distill_rule": {"harm_generalization", "safe_generalization", "n_train"},
}
# Each family times itself in its own units; a missing clock is still a
# failure, but the key it lives under is the suite's business. ``None`` says
# the suite records no clock at all -- true only of distill_rule, whose runner
# never captured one. That is a gap in the evidence, not a rule to relax
# generally: it is declared here so the validator states it out loud instead
# of reporting a missing storage-family key nobody expected it to have.
_SUITE_WALL_KEY: dict[str, str | None] = {
    "distill": "train_wall_s",
    "distill_merge": "train_wall_s",
    "distill_noisy": "train_wall_s",
    "distill_rule": None,
}
# Where zero is data rather than a dropped clock: the distillation arms
# that do no training (the base model, retrieval, the adapter merges)
# honestly took zero training seconds. Presence is enforced by the
# required-metric set above, so this only relaxes the positivity rule.
_ZERO_WALL_OK = {"distill", "distill_merge", "distill_noisy"}
# Identity fields the SWE-Bench-CL curve needs to pair a world and order
# a curriculum. Without them a result file is unusable even if complete.
_SWEBENCH_REQUIRED_KEYS = {"arm", "seed", "sequence", "instance_id", "order"}


def _uniform_suite(runs: list[dict[str, Any]]) -> str | None:
    """The suite every run shares, or None for a mixed/legacy file."""
    suites = {run.get("suite") for run in runs}
    return next(iter(suites)) if len(suites) == 1 else None


def _is_noisy(run: dict[str, Any]) -> bool:
    return bool(run.get("config", {}).get("flake_rate", 0))


def _group_key(run: dict[str, Any]) -> str:
    label = run.get("label") or ""
    return f"{run['arm']}:{label}" if label else run["arm"]


def _fmt(value: float, big: bool) -> str:
    return f"{value:,.0f}" if big else f"{value:.2f}"


def _mean_ci(values: list[float]) -> str:
    """Mean with a seeded percentile-bootstrap 95% CI across seeds."""
    if not values:
        return "-"
    mean = statistics.mean(values)
    lo, hi = bootstrap_ci(values)
    big = abs(mean) >= 100
    return f"{_fmt(mean, big)} [{_fmt(lo, big)}, {_fmt(hi, big)}]"


def _median_ci(values: list[float]) -> str:
    """Median with a seeded percentile-bootstrap 95% CI across seeds."""
    if not values:
        return "-"
    med = statistics.median(values)
    lo, hi = bootstrap_ci(values, statistic=statistics.median)
    big = abs(med) >= 100
    return f"{_fmt(med, big)} [{_fmt(lo, big)}, {_fmt(hi, big)}]"


def aggregate(runs: list[dict[str, Any]]) -> list[dict[str, str]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        groups.setdefault(_group_key(run), []).append(run)

    rows: list[dict[str, str]] = []
    for key in sorted(groups):
        metric_sets = [r["metrics"] for r in groups[key]]
        kills = [m["poison_killed"] for m in metric_sets]
        kill_cycles = [
            m["poison_kill_cycle"]
            for m in metric_sets
            if m["poison_kill_cycle"] is not None
        ]
        rows.append(
            {
                "arm": key,
                "seeds": str(len(metric_sets)),
                "kill rate": _mean_ci([float(k) for k in kills]),
                "kill cycle (med)": _median_ci([float(c) for c in kill_cycles]),
                "damage before kill": _mean_ci(
                    [m["damage_before_kill"] for m in metric_sets]
                ),
                "tail delta": _mean_ci([m["tail_delta_mean"] for m in metric_sets]),
                "cum delta": _mean_ci([m["cum_delta"] for m in metric_sets]),
                "final pop": _mean_ci(
                    [float(m["final_population"]) for m in metric_sets]
                ),
                "harmful safe": _mean_ci(
                    [m["probe_harmful_safe_rate"] for m in metric_sets]
                ),
                "benign correct": _mean_ci(
                    [m["probe_benign_correct_rate"] for m in metric_sets]
                ),
                "para safe": _mean_ci(
                    [m["paraphrase_harmful_safe_rate"] for m in metric_sets]
                ),
                "para grounded": _mean_ci(
                    [m["paraphrase_benign_grounded_rate"] for m in metric_sets]
                ),
            }
        )
        if any(_is_noisy(r) for r in runs):
            rows[-1]["flakes fired"] = _mean_ci(
                [float(m.get("flakes_fired", 0)) for m in metric_sets]
            )
        # LLM-suite runs carry attribution-path rates per seed; surface
        # them with the same bootstrap treatment as everything else.
        if any("citation_cited_rate" in r["metrics"] for r in runs):
            for key, column in (
                ("citation_cited_rate", "cited"),
                ("citation_explicit_none_rate", "explicit none"),
                ("citation_fallback_rate", "fallback"),
                ("citation_refused_rate", "refused"),
                ("citation_unattributed_action_rate", "unattr action"),
            ):
                rows[-1][column] = _mean_ci(
                    [float(m.get(key, 0.0)) for m in metric_sets]
                )
    return rows


def render_table(rows: list[dict[str, str]], fmt: str = "ascii") -> str:
    if not rows:
        return "(no rows)"
    headers = list(rows[0].keys())
    widths = {h: max(len(h), *(len(r[h]) for r in rows)) for h in headers}
    if fmt == "md":
        lines = [
            "| " + " | ".join(h.ljust(widths[h]) for h in headers) + " |",
            "|" + "|".join("-" * (widths[h] + 2) for h in headers) + "|",
        ]
        lines += [
            "| " + " | ".join(r[h].ljust(widths[h]) for h in headers) + " |"
            for r in rows
        ]
    else:
        lines = ["  ".join(h.ljust(widths[h]) for h in headers)]
        lines += ["  ".join(r[h].ljust(widths[h]) for h in headers) for r in rows]
    return "\n".join(lines)


def check(runs: list[dict[str, Any]]) -> list[str]:
    """Schema and sanity validation. Returns a list of failures."""
    failures: list[str] = []
    if not runs:
        return ["no runs in file"]
    suite = _uniform_suite(runs)
    swebench = suite == _SWEBENCH_SUITE
    required = _SUITE_REQUIRED_METRICS.get(suite or "", _REQUIRED_METRIC_KEYS)
    wall_key = _SUITE_WALL_KEY.get(suite or "", "wall_time_s")
    for i, run in enumerate(runs):
        if run.get("schema_version") != 1:
            failures.append(f"run {i}: bad schema_version")
        missing = required - set(run.get("metrics", {}))
        if missing:
            failures.append(f"run {i}: missing metrics {sorted(missing)}")
        if wall_key is not None:
            wall = run.get("metrics", {}).get(wall_key)
            if wall is None or (wall <= 0 and suite not in _ZERO_WALL_OK):
                failures.append(f"run {i}: {wall_key} not recorded")
        if swebench:
            absent = _SWEBENCH_REQUIRED_KEYS - set(run)
            if absent:
                failures.append(f"run {i}: missing identity fields {sorted(absent)}")

    if suite in _SUITE_REQUIRED_METRICS:
        # Everything below is storage-family physics -- poison kills,
        # population deltas, a noise canary -- and none of it has a
        # meaning for a task list or a trained model. The SWE-Bench-CL
        # curve's own invariants live in bench.swebench_cl.curve, which
        # refuses to pair a world that did not run both arms.
        return failures

    # The poison-kill gate is a noiseless-era invariant: under
    # measurement noise, delayed or missed kills are an honest, expected
    # result the suite exists to measure, so noisy runs are exempt.
    # A run missing the key was already reported above; skip it here so
    # check() reports every failure it found instead of raising on the
    # first malformed record.
    survival = [
        r
        for r in runs
        if r.get("arm") == "survival"
        and not _is_noisy(r)
        and "poison_killed" in r.get("metrics", {})
    ]
    if survival:
        kills = sum(r["metrics"]["poison_killed"] for r in survival)
        if kills * 3 < len(survival) * 2:  # at least 2 of 3
            failures.append(
                f"survival killed poison in only {kills}/{len(survival)} seeds"
            )

    # Noise-validity canary: keep_everything never reads outcomes, so
    # its TRUE cum delta must be identical across every noise rate and
    # model at a fixed (seed, cycles, files). Drift = harness bug.
    # The attack class and the write-time filter are NOT noise: they
    # change which entries exist, so they belong in the key rather than
    # inside a set the canary expects to be a singleton.
    canary: dict[tuple[str, int, int, int, str, bool], set[float]] = {}
    # A run missing cum_delta was already reported above; skip it here for the
    # same reason the poison gate does, so an unregistered suite that happens
    # to carry a keep_everything arm gets a failure list rather than a KeyError
    # from the validator that exists to report failures.
    for r in runs:
        if r["arm"] == "keep_everything" and "cum_delta" in r.get("metrics", {}):
            cfg = r.get("config", {})
            key = (
                str(cfg.get("env_family", "storage")),
                r["seed"],
                cfg.get("cycles", 0),
                cfg.get("files_per_cycle", 0),
                str(cfg.get("attack", "")),
                bool(cfg.get("content_filter", False)),
            )
            canary.setdefault(key, set()).add(r["metrics"]["cum_delta"])
    for key, values in canary.items():
        if len(values) > 1:
            failures.append(
                f"keep_everything true cum_delta varies with noise at "
                f"family/seed/cycles/files {key}: {sorted(values)}"
            )
    return failures


def _world_cell(run: dict[str, Any]) -> str:
    """The world a run faced: its label minus the arm-variant suffix.

    The variant suffix (",k=2", ",m=3") names the arm, not the world;
    the world cell is model+rate (plus any env override like a scale).
    ",refuse=on/off" is likewise the arm's mitigation flag, not the
    world: stripping it pairs the LLM suite's on/off runs by seed
    within one model cell, which is the comparison that suite exists
    to make.
    """
    label = run.get("label") or ""
    return ",".join(
        p
        for p in label.split(",")
        if not p.startswith(("k=", "m=", "judge=", "refuse="))
    )


def paired(
    runs: list[dict[str, Any]],
    arm_a: str,
    arm_b: str,
    metric: str = "cum_delta",
) -> list[dict[str, str]]:
    """Per-seed paired differences of ``metric`` between two arm prefixes.

    Flake marks are a fixed property of the world at a given (seed,
    rate, model), so arms within one label cell are exactly PAIRED:
    the honest comparison is per-seed differences, win counts, and
    medians, not overlapping mean±std columns. Arm names match on the
    group-key prefix before the variant suffix, e.g. ``survival`` vs
    ``evict_on_negative:...,k=2``: pass the prefixes as printed by the
    table and each label cell is compared independently. An arm prefix
    that matches SEVERAL variants in one cell (``evict_on_negative``
    matches k=1, k=2, and k=3) is ambiguous — which variant wins would
    silently change the verdict — so it raises; qualify the arm with
    its variant key instead. A duplicated (cell, group, seed) row, e.g.
    two result files concatenated, raises for the same reason: keeping
    one copy silently would change the verdict.
    """

    def matches(run: dict[str, Any], arm: str) -> bool:
        group = _group_key(run)
        if group == arm or group.startswith(arm + ":"):
            return True
        # Variant-qualified form "evict_on_negative:k=2": the base must
        # prefix the group AND the variant must end its label.
        if ":" in arm:
            base, variant = arm.split(":", 1)
            return group.startswith(base + ":") and group.endswith("," + variant)
        return False

    by_cell: dict[str, dict[int, dict[str, tuple[str, float]]]] = {}
    for run in runs:
        side = "a" if matches(run, arm_a) else "b" if matches(run, arm_b) else None
        if side is None:
            continue
        slot = by_cell.setdefault(_world_cell(run), {}).setdefault(run["seed"], {})
        group = _group_key(run)
        if side in slot:
            if slot[side][0] != group:
                raise ValueError(
                    f"ambiguous arm {arm_a if side == 'a' else arm_b!r}: both "
                    f"{slot[side][0]!r} and {group!r} match in cell "
                    f"{_world_cell(run)!r}; qualify the variant (e.g. "
                    "'evict_on_negative:k=2')"
                )
            raise ValueError(
                f"duplicate run for {group!r} at seed {run['seed']} in cell "
                f"{_world_cell(run)!r}; deduplicate the results file"
            )
        slot[side] = (group, run["metrics"][metric])

    rows: list[dict[str, str]] = []
    for cell_key in sorted(by_cell):
        diffs = [
            seeds["a"][1] - seeds["b"][1]
            for seeds in by_cell[cell_key].values()
            if "a" in seeds and "b" in seeds
        ]
        if not diffs:
            continue
        diffs.sort()
        wins = sum(1 for d in diffs if d > 0)
        losses = sum(1 for d in diffs if d < 0)
        rows.append(
            {
                "cell": cell_key or "(none)",
                "seeds": str(len(diffs)),
                f"{arm_a} wins": str(wins),
                "ties": str(len(diffs) - wins - losses),
                f"{arm_b} wins": str(losses),
                "median diff": f"{statistics.median(diffs):,.0f}",
                "min diff": f"{diffs[0]:,.0f}",
                "max diff": f"{diffs[-1]:,.0f}",
            }
        )
    return rows


def significance(
    runs: list[dict[str, Any]],
    baseline: str = "survival",
    metric: str = "cum_delta",
) -> list[dict[str, str]]:
    """Exact paired permutation tests of ``baseline`` vs every other arm.

    Within each world cell the baseline arm is paired BY SEED with each
    other arm group (same seed, same world, same flake marks). The
    per-seed differences feed a two-sided sign-flip permutation test:
    exact enumeration of all sign assignments at small seed counts,
    seeded Monte Carlo above. Holm-Bonferroni then adjusts across the
    FULL grid of comparisons in this call, so the adjusted column
    already pays for every comparison printed next to it. Deterministic
    ties give p = 1.0, never spurious significance. A duplicated
    (cell, group, seed) row, e.g. two result files concatenated, raises
    instead of silently keeping the last copy's metric.
    """
    by_cell: dict[str, dict[str, dict[int, float]]] = {}
    arm_of: dict[str, str] = {}
    for run in runs:
        group = _group_key(run)
        arm_of[group] = run["arm"]
        seeds = by_cell.setdefault(_world_cell(run), {}).setdefault(group, {})
        if run["seed"] in seeds:
            raise ValueError(
                f"duplicate run for {group!r} at seed {run['seed']} in cell "
                f"{_world_cell(run)!r}; deduplicate the results file"
            )
        seeds[run["seed"]] = run["metrics"][metric]

    rows: list[dict[str, str]] = []
    raw_pvalues: list[float] = []
    for cell_key in sorted(by_cell):
        groups = by_cell[cell_key]
        base_groups = [g for g in groups if arm_of[g] == baseline]
        if not base_groups:
            continue
        if len(base_groups) > 1:
            raise ValueError(
                f"ambiguous baseline {baseline!r} in cell {cell_key!r}: "
                f"{sorted(base_groups)}"
            )
        base = groups[base_groups[0]]
        for group in sorted(g for g in groups if arm_of[g] != baseline):
            common = sorted(set(base) & set(groups[group]))
            if not common:
                continue
            diffs = [base[seed] - groups[group][seed] for seed in common]
            wins = sum(1 for d in diffs if d > 0)
            losses = sum(1 for d in diffs if d < 0)
            raw = paired_permutation_pvalue(diffs)
            raw_pvalues.append(raw)
            rows.append(
                {
                    "cell": cell_key or "(none)",
                    "vs": group,
                    "seeds": str(len(diffs)),
                    "W/T/L": f"{wins}/{len(diffs) - wins - losses}/{losses}",
                    "mean diff": f"{statistics.mean(diffs):,.0f}",
                    "median diff": f"{statistics.median(diffs):,.0f}",
                    "p": f"{raw:.4g}",
                    "p (holm)": "",  # filled below, across the full grid
                }
            )
    for row, adjusted in zip(rows, holm_bonferroni(raw_pvalues), strict=True):
        row["p (holm)"] = f"{adjusted:.4g}"
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--fmt", choices=["ascii", "md"], default="ascii")
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--require-manifest",
        action="store_true",
        help="with --check, fail when the file has no manifest entry: "
        "committed evidence must stay bound to MANIFEST.json",
    )
    parser.add_argument(
        "--paired",
        nargs=2,
        metavar=("ARM_A", "ARM_B"),
        help="per-seed paired differences between two arms (same-world cells)",
    )
    parser.add_argument(
        "--metric",
        default="cum_delta",
        help="metric for --paired and --tests (default cum_delta)",
    )
    parser.add_argument(
        "--tests",
        action="store_true",
        help="paired permutation tests vs --baseline, Holm-adjusted "
        "across the full grid",
    )
    parser.add_argument(
        "--baseline",
        default="survival",
        help="baseline arm for --tests (default survival)",
    )
    args = parser.parse_args(argv)

    payload = json.loads(args.results.read_text())
    runs = payload["runs"] if isinstance(payload, dict) else payload

    if args.paired:
        rows = paired(runs, args.paired[0], args.paired[1], metric=args.metric)
        print(render_table(rows, args.fmt))
        return 0

    if args.tests:
        rows = significance(runs, baseline=args.baseline, metric=args.metric)
        print(render_table(rows, args.fmt))
        return 0

    if args.check:
        failures = check(runs) + manifest_failures(
            args.results, runs, require_entry=args.require_manifest
        )
        if failures:
            for failure in failures:
                print(f"FAIL: {failure}", file=sys.stderr)
            return 1
        print(f"PASS: {len(runs)} runs valid")
        return 0

    if runs and "n_entries" in runs[0]:  # scaling results
        headers = list(runs[0].keys())
        rows = [
            {
                h: (
                    "-"
                    if r[h] is None
                    else f"{r[h]:,.1f}"
                    if isinstance(r[h], float)
                    else str(r[h])
                )
                for h in headers
            }
            for r in runs
        ]
        print(render_table(rows, args.fmt))
        return 0

    print(render_table(aggregate(runs), args.fmt))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
