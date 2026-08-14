"""The curation-targeted attack on the SWE-Bench-CL loop.

Two properties carry the experiment. The budget has to bound the attack
at the rate it claims, and the lie has to reach the curator without ever
reaching the score -- if a corrupted measurement leaked into
``metrics.delta``, every downstream analysis would be scoring the
adversary's story instead of the harness's.
"""

from __future__ import annotations

from typing import Any

import pytest

from bench.swebench_cl import attack
from bench.swebench_cl.adversary import SETTLEMENTS_PER_CYCLE, SettlementAdversary
from bench.swebench_cl.executor import StubExecutor
from bench.swebench_cl.model import EndpointConfig
from bench.swebench_cl.runner import run_sequence

from .test_swebench_cl import GOLD_PATCH, FakeCompleter, make_task


def test_zero_budget_is_the_identity():
    a = SettlementAdversary(0)
    for d in (0.5, -0.5, 0.0, 1.0):
        assert a.report(d) == d
    assert a.fired == 0
    assert a.distortion == 0.0


def test_negative_budget_refused():
    with pytest.raises(ValueError):
        SettlementAdversary(-1)


def test_silence_is_never_lied_about():
    """A patch that failed to apply is not a measurement."""
    a = SettlementAdversary(4)
    for _ in range(10):
        assert a.report(0.0) == 0.0
    assert a.measured == 0
    assert a.fired == 0


def test_budget_bounds_lies_per_cycle():
    a = SettlementAdversary(2)
    reports = [a.report(0.5) for _ in range(SETTLEMENTS_PER_CYCLE * 3)]
    assert a.fired == 6  # two per cycle, three cycles
    assert reports[:2] == [-0.5, -0.5]  # spent greedily at the cycle head
    assert reports[2:SETTLEMENTS_PER_CYCLE] == [0.5] * (SETTLEMENTS_PER_CYCLE - 2)
    assert reports[SETTLEMENTS_PER_CYCLE] == -0.5  # budget refreshes


def test_cycle_counts_settlements_not_ticks():
    """Unmeasured tasks must not consume or refresh the budget."""
    a = SettlementAdversary(1)
    assert a.report(0.5) == -0.5  # cycle 0, budget spent
    for _ in range(50):
        a.report(0.0)  # 50 failed applies in between
    assert a.report(0.5) == 0.5  # still cycle 0: no free refresh
    assert a.fired == 1


def test_both_lie_directions_are_counted():
    a = SettlementAdversary(2)
    assert a.report(0.4) == -0.4  # a real fix blamed for a regression
    assert a.report(-0.4) == 0.4  # real damage paid for
    assert (a.false_bad, a.false_good) == (1, 1)
    assert a.distortion == pytest.approx(0.0)  # they cancel; the harm does not


def test_accounting_identity_holds():
    """reported == true + distortion, summed over the run."""
    a = SettlementAdversary(3)
    trues = [0.5, -0.25, 0.75, 0.0, -1.0, 0.125, 0.5]
    reported = [a.report(d) for d in trues]
    assert sum(reported) == pytest.approx(sum(trues) + a.distortion)


def _attacked(arm: str, lie_budget: int, n_tasks: int = 4) -> list[dict[str, Any]]:
    response = f"```diff\n{GOLD_PATCH}```\nREFLECTION: gold."
    tasks = [
        make_task(instance_id=f"acme__proj-{i}", order=i) for i in range(1, n_tasks + 1)
    ]
    return run_sequence(
        tasks,
        sequence_id="acme_proj_sequence",
        arm_name=arm,
        endpoint=EndpointConfig(model="fake"),
        executor=StubExecutor(),
        seed=0,
        completer=FakeCompleter([response]),
        lie_budget=lie_budget,
    )


def test_the_lie_settles_but_never_scores():
    """The separation the whole experiment rests on.

    Every task here resolves against the stub executor, so the true
    delta is positive throughout and the adversary reports it as damage.
    ``metrics`` must still describe the world.
    """
    runs = _attacked("memory_on", lie_budget=12)
    for run in runs:
        assert run["metrics"]["delta"] > 0, "the harness's true measurement"
        assert run["metrics"]["resolved"] is True
        assert run["adversary"]["reported_delta"] < 0, "what the curator was told"
        assert run["adversary"]["lied"] is True
    assert runs[-1]["adversary"]["false_bad"] == len(runs)
    assert runs[-1]["adversary"]["false_good"] == 0


def test_unattacked_runs_report_the_truth():
    runs = _attacked("memory_on", lie_budget=0)
    for run in runs:
        assert run["adversary"]["reported_delta"] == run["metrics"]["delta"]
        assert run["adversary"]["lied"] is False
        assert run["adversary"]["lies_fired"] == 0


def test_the_attack_starves_the_evictor_and_not_the_ledger():
    """Denial of memory, on the real-task loop.

    ``evict_on_negative`` buries every injected lesson the moment it is
    told the outcome was bad, so a lying measurement empties its store
    of exactly the lessons that worked. The ledger charges energy the
    same lessons can earn back, so they survive the same lie.
    """
    evictor = _attacked("evict_on_negative", lie_budget=12)
    ledger = _attacked("memory_on", lie_budget=12)
    assert evictor[-1]["store"]["graveyard"] > 0, "benign lessons buried by a lie"
    assert ledger[-1]["store"]["population"] > evictor[-1]["store"]["population"]


def test_poison_alive_is_reported():
    runs = _attacked("memory_on", lie_budget=0)
    assert all(r["store"]["poison_alive"] == 0 for r in runs)


# ---------------------------------------------------------------------------
# Scoring the attack
# ---------------------------------------------------------------------------


def fake_cell(
    arm, seed, budget, n, resolved, poison_alive, graveyard, fired=0, merges=0
):
    """One cell's worth of records, carrying only the scored fields."""
    return [
        {
            "arm": arm,
            "seed": seed,
            "sequence": "acme_proj_sequence",
            "order": i,
            "config": {"lie_budget": budget},
            "metrics": {
                "resolved": i <= resolved,
                "delta": 0.5 if i <= resolved else 0.0,
            },
            "store": {
                "population": n - graveyard,
                "graveyard": graveyard,
                "poison_alive": poison_alive,
                "merges_this_tick": merges if i == 1 else 0,
            },
            "adversary": {"lies_fired": fired},
        }
        for i in range(1, n + 1)
    ]


def test_poison_entries_is_not_a_kill_rate():
    """A merge can hide many poison sources inside one live entry."""
    cell = fake_cell("memory_on", 0, 2, n=10, resolved=4, poison_alive=2, graveyard=8)
    assert attack.poison_seeded(cell) == 10
    assert attack.poison_entries_alive(cell) == 2
    assert attack.poison_eliminated(cell) is False
    clean = fake_cell("memory_on", 0, 2, n=10, resolved=4, poison_alive=0, graveyard=10)
    assert attack.poison_eliminated(clean) is True


def test_merges_are_reported_because_they_break_the_entry_count():
    """The confound that made an earlier version of this scorer wrong.

    Only survival curation consolidates, so an entry-count comparison
    across arms compares one arm that deduplicates poison against two
    that never do.
    """
    merged = fake_cell("memory_on", 0, 2, 10, 4, poison_alive=1, graveyard=9, merges=1)
    flat = fake_cell("keep_everything", 0, 2, 10, 4, poison_alive=10, graveyard=0)
    assert attack.merges(merged) == 1
    assert attack.merges(flat) == 0


def test_benign_buried_excludes_the_poison_it_killed():
    """A graveyard of 8 that holds 8 dead poison buried no benign entry."""
    cell = fake_cell("memory_on", 0, 2, n=10, resolved=4, poison_alive=2, graveyard=8)
    assert attack.benign_buried(cell) == 0
    # Same kill count, bigger graveyard: the extra dead are benign.
    worse = fake_cell("evict_on_negative", 0, 2, 10, 4, poison_alive=2, graveyard=13)
    assert attack.benign_buried(worse) == 5


def test_lie_budget_defaults_to_zero_for_pre_attack_records():
    """The clean matrices load without being rewritten."""
    run: dict[str, Any] = {"config": {}}
    assert attack.lie_budget(run) == 0


def test_retention_pairs_within_a_world():
    runs = [
        *fake_cell("memory_on", 0, 0, n=10, resolved=6, poison_alive=0, graveyard=10),
        *fake_cell(
            "memory_on", 0, 2, n=10, resolved=3, poison_alive=0, graveyard=10, fired=2
        ),
    ]
    res = attack.retention(runs, "memory_on", budget=2)
    assert res["pairs"] == 1
    assert res["resolve_clean"] == pytest.approx(0.6)
    assert res["resolve_attacked"] == pytest.approx(0.3)
    assert res["retained"] == pytest.approx(0.5)
    assert res["lies_fired"] == 2


def test_retention_refuses_an_unpaired_arm():
    runs = fake_cell("memory_on", 0, 2, n=10, resolved=3, poison_alive=0, graveyard=1)
    with pytest.raises(ValueError, match="both budget"):
        attack.retention(runs, "memory_on", budget=2)


def test_docker_guard_passes_through_non_docker_executors():
    from bench.swebench_cl.matrix import docker_alive

    assert docker_alive("stub") is True


def test_docker_guard_reports_a_missing_daemon(monkeypatch):
    """A stopped daemon must read as down, not raise.

    The guard exists because every cell bills its model calls before the
    first evaluation, so continuing past a dead daemon spends the
    matrix's API budget to produce nothing.
    """
    import subprocess as sp

    from bench.swebench_cl import matrix

    def boom(*a, **k):
        raise OSError("docker: command not found")

    monkeypatch.setattr("bench.swebench_cl.matrix.subprocess.run", boom)
    assert matrix.docker_alive("docker") is False

    def timeout(*a, **k):
        raise sp.TimeoutExpired(cmd="docker info", timeout=1)

    monkeypatch.setattr("bench.swebench_cl.matrix.subprocess.run", timeout)
    assert matrix.docker_alive("docker") is False


def test_sequence_filter_excludes_an_abandoned_run():
    """Orphan cells must not leak into the descriptive rows.

    An abandoned sequence can leave attacked cells with no controls.
    They pair with nothing, so the statistics were always safe, but they
    did move the per-arm means until the filter existed.
    """
    django = [
        *fake_cell("memory_on", 0, 0, n=10, resolved=5, poison_alive=1, graveyard=6),
        *fake_cell("memory_on", 0, 2, n=10, resolved=5, poison_alive=1, graveyard=8),
    ]
    orphan = fake_cell(
        "memory_on", 0, 2, n=10, resolved=1, poison_alive=1, graveyard=30
    )
    for r in orphan:
        r["sequence"] = "abandoned_sequence"
    runs = [*django, *orphan]

    unfiltered = attack.arm_rows(runs, budget=2)[0]
    filtered = attack.arm_rows(runs, budget=2, sequence="acme_proj_sequence")[0]
    assert unfiltered["cells"] == 2, "the orphan inflates the row"
    assert filtered["cells"] == 1
    assert filtered["benign_buried"] < unfiltered["benign_buried"]

    # Pairing was never affected: the orphan has no control to pair with.
    assert attack.retention(runs, "memory_on", budget=2)["pairs"] == 1
