"""Hand-checkable tests for the bench statistics, manifest, and seed scheme."""

import json
import statistics
import subprocess

import pytest

from bench.manifest import config_hash, manifest_failures, update_manifest
from bench.report import aggregate, paired, significance
from bench.stats import bootstrap_ci, holm_bonferroni, paired_permutation_pvalue

# ---------------------------------------------------------------------------
# Paired permutation test: every expected value below is enumerable by hand
# ---------------------------------------------------------------------------


def test_permutation_all_positive_diffs_exact():
    # 2^3 = 8 sign assignments; |sum| >= 6 only for +++ and ---: p = 2/8.
    assert paired_permutation_pvalue([1.0, 2.0, 3.0]) == 0.25


def test_permutation_deterministic_tie_is_p_one():
    # All-zero diffs: every assignment matches the observed statistic.
    assert paired_permutation_pvalue([0.0, 0.0, 0.0]) == 1.0


def test_permutation_cancelling_diffs_is_p_one():
    # Observed |5 - 5| = 0; every assignment is at least as extreme.
    assert paired_permutation_pvalue([5.0, -5.0]) == 1.0


def test_permutation_single_pair_cannot_be_significant():
    # n=1: both assignments give |2|, so p = 1, never 1/2.
    assert paired_permutation_pvalue([2.0]) == 1.0


def test_permutation_floor_is_identity_assignment():
    # Ten strictly positive diffs of mixed size: only the two uniform
    # assignments reach |sum|, so the exact p is 2/2^10.
    diffs = [1.0, 2.0, 0.5, 3.0, 0.7, 1.2, 2.2, 0.4, 1.9, 0.3]
    assert paired_permutation_pvalue(diffs) == 2 / 1024


def test_permutation_monte_carlo_matches_exact_and_is_seeded():
    diffs = [1.0, 2.0, -0.5, 3.0, 0.7, -1.2, 2.2, 0.4, 1.9, -0.3]
    exact = paired_permutation_pvalue(diffs)
    mc_a = paired_permutation_pvalue(diffs, exact_limit=0)
    mc_b = paired_permutation_pvalue(diffs, exact_limit=0)
    assert mc_a == mc_b, "Monte Carlo path must be seeded"
    assert abs(mc_a - exact) < 0.02
    assert mc_a >= 1 / 20_001, "+1 correction keeps Monte Carlo p above zero"


def test_permutation_rejects_empty():
    with pytest.raises(ValueError):
        paired_permutation_pvalue([])


# ---------------------------------------------------------------------------
# Bootstrap CI
# ---------------------------------------------------------------------------


def test_bootstrap_constant_values_collapse_to_a_point():
    assert bootstrap_ci([7.0, 7.0, 7.0]) == (7.0, 7.0)


def test_bootstrap_single_value_is_a_point():
    assert bootstrap_ci([3.5]) == (3.5, 3.5)


def test_bootstrap_brackets_the_statistic_and_stays_in_range():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    lo, hi = bootstrap_ci(values)
    assert min(values) <= lo <= statistics.mean(values) <= hi <= max(values)


def test_bootstrap_is_deterministic():
    values = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0]
    assert bootstrap_ci(values) == bootstrap_ci(values)


def test_bootstrap_supports_other_statistics():
    lo, hi = bootstrap_ci([1.0, 1.0, 1.0, 9.0], statistic=statistics.median)
    assert lo == 1.0 and hi <= 9.0


def test_bootstrap_rejects_empty():
    with pytest.raises(ValueError):
        bootstrap_ci([])


# ---------------------------------------------------------------------------
# Holm-Bonferroni step-down
# ---------------------------------------------------------------------------


def test_holm_textbook_case():
    # Sorted raw: .01, .03, .04 with m=3 -> 3*.01, max(.03, 2*.03), then
    # the running max holds 1*.04 up at .06.
    assert holm_bonferroni([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_holm_clips_at_one_and_stays_monotone():
    assert holm_bonferroni([0.5, 0.6]) == [1.0, 1.0]


def test_holm_ties_share_the_conservative_adjustment():
    assert holm_bonferroni([0.02, 0.02]) == pytest.approx([0.04, 0.04])


def test_holm_empty_and_single():
    assert holm_bonferroni([]) == []
    assert holm_bonferroni([0.2]) == [0.2]


# ---------------------------------------------------------------------------
# The significance grid over fake runs
# ---------------------------------------------------------------------------


def _fake_run(arm, seed, cum, label=""):
    return {
        "arm": arm,
        "seed": seed,
        "label": label,
        "metrics": {"cum_delta": cum},
    }


def test_significance_pairs_by_seed_and_holm_adjusts_across_the_grid():
    runs = []
    for seed, value in ((0, 10.0), (1, 12.0), (2, 11.0)):
        runs.append(_fake_run("survival", seed, value))
        runs.append(_fake_run("ttl", seed, value - 9.0))  # always loses
        runs.append(_fake_run("keep_everything", seed, value))  # exact tie
    rows = significance(runs)
    by_arm = {r["vs"]: r for r in rows}
    assert by_arm["ttl"]["W/T/L"] == "3/0/0"
    assert by_arm["ttl"]["p"] == "0.25"  # 2/2^3 exact
    assert by_arm["keep_everything"]["p"] == "1"
    # Holm over the full grid of two comparisons: 2*0.25 and 1*1.0.
    assert by_arm["ttl"]["p (holm)"] == "0.5"
    assert by_arm["keep_everything"]["p (holm)"] == "1"


def test_significance_keeps_world_cells_apart():
    runs = []
    for cell in ("model=flip,rate=0.05", "model=flip,rate=0.20"):
        for seed in (0, 1):
            runs.append(_fake_run("survival", seed, 10.0, label=cell))
            runs.append(_fake_run("evict_consecutive", seed, 1.0, f"{cell},k=2"))
    rows = significance(runs)
    assert [r["cell"] for r in rows] == [
        "model=flip,rate=0.05",
        "model=flip,rate=0.20",
    ]
    assert all(r["seeds"] == "2" for r in rows)


def test_significance_rejects_duplicate_rows():
    # Two survival rows at one (cell, seed): keeping the last silently
    # would change every p-value downstream of it.
    runs = [
        _fake_run("survival", 0, 10.0),
        _fake_run("survival", 0, 11.0),
        _fake_run("ttl", 0, 1.0),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        significance(runs)


def test_paired_rejects_duplicate_rows():
    runs = [
        _fake_run("survival", 0, 10.0),
        _fake_run("ttl", 0, 1.0),
        _fake_run("ttl", 0, 2.0),
    ]
    with pytest.raises(ValueError, match="duplicate"):
        paired(runs, "survival", "ttl")


def test_aggregate_reports_bootstrap_intervals():
    metrics = {
        "poison_killed": True,
        "poison_kill_cycle": 0,
        "damage_before_kill": -10.0,
        "cum_delta": 5.0,
        "tail_delta_mean": 1.0,
        "final_population": 4,
        "probe_harmful_safe_rate": 1.0,
        "probe_benign_correct_rate": 1.0,
        "paraphrase_harmful_safe_rate": 1.0,
        "paraphrase_benign_grounded_rate": 0.5,
    }
    runs = [
        {"arm": "survival", "seed": s, "metrics": dict(metrics), "config": {}}
        for s in (0, 1)
    ]
    (row,) = aggregate(runs)
    # Constant per-seed values: every interval collapses onto the mean.
    assert row["cum delta"] == "5.00 [5.00, 5.00]"
    assert row["kill rate"] == "1.00 [1.00, 1.00]"
    assert row["kill cycle (med)"] == "0.00 [0.00, 0.00]"


# ---------------------------------------------------------------------------
# Manifest: committed results bound to suite, seeds, config hash, command
# ---------------------------------------------------------------------------


def _manifest_runs():
    return [
        {
            "suite": "headline",
            "arm": "survival",
            "seed": s,
            "config": {"cycles": 30, "files_per_cycle": 12},
            "metrics": {},
            "meta": {"darwin_memo": "0.4.0"},
        }
        for s in (0, 1)
    ]


def test_manifest_roundtrip_validates_clean(tmp_path):
    out = tmp_path / "headline.json"
    runs = _manifest_runs()
    update_manifest(out, runs, command="python -m bench.run --suite headline")
    assert manifest_failures(out, runs) == []


def test_manifest_catches_config_drift(tmp_path):
    out = tmp_path / "headline.json"
    runs = _manifest_runs()
    update_manifest(out, runs, command="cmd")
    runs[0]["config"]["cycles"] = 31
    failures = manifest_failures(out, runs)
    assert any("config_hash" in f for f in failures)


def test_manifest_catches_seed_and_count_drift(tmp_path):
    out = tmp_path / "headline.json"
    runs = _manifest_runs()
    update_manifest(out, runs, command="cmd")
    failures = manifest_failures(out, runs[:1])
    assert any("seeds" in f for f in failures)
    assert any("runs" in f for f in failures)


def test_manifest_ignores_unlisted_files(tmp_path):
    out = tmp_path / "headline.json"
    update_manifest(out, _manifest_runs(), command="cmd")
    assert manifest_failures(tmp_path / "smoke.json", []) == []
    assert manifest_failures(tmp_path / "other" / "x.json", []) == []


def test_manifest_require_entry_fails_on_missing_manifest_or_entry(tmp_path):
    out = tmp_path / "headline.json"
    runs = _manifest_runs()
    # No manifest at all: lenient passes, required fails.
    assert manifest_failures(out, runs) == []
    failures = manifest_failures(out, runs, require_entry=True)
    assert any("no MANIFEST.json" in f for f in failures)
    # Manifest exists but names only a different file.
    update_manifest(tmp_path / "other.json", runs, command="cmd")
    assert manifest_failures(out, runs) == []
    failures = manifest_failures(out, runs, require_entry=True)
    assert any("no entry" in f for f in failures)
    # Once the entry exists, required validates clean.
    update_manifest(out, runs, command="cmd")
    assert manifest_failures(out, runs, require_entry=True) == []


def test_manifest_records_source_commit(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    identity = ["-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(
        ["git", *identity, "commit", "--allow-empty", "-q", "-m", "x"],
        cwd=tmp_path,
        check=True,
    )
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    path = update_manifest(tmp_path / "h.json", _manifest_runs(), command="cmd")
    entry = json.loads(path.read_text())["files"]["h.json"]
    assert entry["source_commit"] == head
    # The manifest itself is untracked now, so a rewrite reads dirty.
    path = update_manifest(tmp_path / "h.json", _manifest_runs(), command="cmd")
    entry = json.loads(path.read_text())["files"]["h.json"]
    assert entry["source_commit"] == head + "-dirty"


def test_manifest_source_commit_unknown_outside_git(tmp_path):
    path = update_manifest(tmp_path / "x.json", _manifest_runs(), command="cmd")
    entry = json.loads(path.read_text())["files"]["x.json"]
    assert entry["source_commit"] == "unknown"


def test_config_hash_is_order_independent_and_content_sensitive():
    runs = _manifest_runs()
    assert config_hash(runs) == config_hash(list(reversed(runs)))
    changed = _manifest_runs()
    changed[1]["seed"] = 7
    assert config_hash(changed) != config_hash(runs)


def test_manifest_file_is_valid_json_with_sorted_entries(tmp_path):
    out_b = tmp_path / "b.json"
    out_a = tmp_path / "a.json"
    update_manifest(out_b, _manifest_runs(), command="cmd-b")
    path = update_manifest(out_a, _manifest_runs(), command="cmd-a")
    manifest = json.loads(path.read_text())
    assert list(manifest["files"]) == ["a.json", "b.json"]
    assert manifest["files"]["a.json"]["command"] == "cmd-a"
