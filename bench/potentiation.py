"""Query-only retention attack: buying a dormant memory a longer life by asking.

``docs/threat-model.md`` says of the query-only adversary (MINJA-shaped: the
attacker never writes, never settles, only asks) that its poison "dies only
when upkeep starves it --- on the same schedule as any other unused entry,
with no acceleration from its being adversarial." That is true of what ships,
where ``SurvivalLoop`` charges flat upkeep. It is not true of an operator who
opts into the organic layer's potentiation, and this module measures the gap
rather than arguing it.

``EarnedImportance`` scores a memory on three equal-weight components ---
recall count, earned credit, graph centrality --- and ``upkeep_scale()`` turns
that score into upkeep relief. Two of those three are reachable by an attacker
who only ever queries:

- **recalls**, directly: the score normalises against the live population's
  peak, so being the most-asked-for entry in the store is the whole of that
  third, and out-asking honest traffic is free.
- **centrality**, indirectly: ``OrganicMemory.recall`` strengthens the Hebbian
  link to every neighbour it traverses, and ``centrality()`` reads those
  learned weights back. The recall COUNT is guarded against manufacture
  ("only the entry actually asked for counts"); the learned WEIGHT is not.

Only credit needs a settled outcome, which is the one thing this adversary
cannot reach. So the predicted ceiling is 2/3 importance, and the question
this module answers is what that buys in cycles.

Three conditions over one poisoned store, same corpus and same upkeep:

- ``flat``: ``charge_upkeep()``. What darwin-memo ships, and the control.
- ``honest``: ``charge_upkeep(scale=organic.upkeep_scale())`` with recalls
  driven only by the benchmark's own probe queries. Separates "potentiation
  extends everything" from "potentiation extends the poison".
- ``attacked``: the same potentiation, plus the attacker recalling its own
  poison each cycle. No writes, no settles, no filter crossed.

``--recall-norm saturating`` re-runs all three against
:class:`SaturatingImportance`, which changes one thing --- the recall term's
denominator --- so that "peak-normalisation is the mechanism" is a measured
claim rather than an inference from the arithmetic.

No model, no environment and no task loop: nothing here mints or settles, so
the only force acting on any entry is upkeep --- which is exactly the regime
the ``inert`` attack class is defined by, and it isolates the mechanism from
everything else the bench measures.

There is no seed because no arm here draws one. That is not the same as being
reproducible, and it did not start out reproducible: entry ids are ``uuid4``,
so every run sorts a different set of strings, and the organic layer had two
places that resolved ties on one (see the CHANGELOG entry this shipped with).
The margins below are stable across processes now, and
``test_potentiation_measurement_is_reproducible_across_processes`` keeps them
that way.

Usage::

    python -m bench.potentiation --attack inert --cycles 400
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from darwin_memo import MemoryStore
from darwin_memo.organic.dynamics import OrganicMemory
from darwin_memo.organic.importance import (
    CENTRALITY_WEIGHT,
    CREDIT_WEIGHT,
    RECALL_WEIGHT,
    SPAWN_ENERGY,
    EarnedImportance,
    clamp01,
)

from .fixtures import PROBES, Probe, poison_ids
from .memsec import ATTACK_CLASSES, build_memsec_store
from .testsuite_fixtures import TESTSUITE_PROBES, build_testsuite_store

CONDITIONS = ("flat", "honest", "attacked")
# How the recall component is scaled. "peak" is what ships; "saturating" is
# the counterfactual that tests whether peak-normalisation IS the mechanism.
RECALL_NORMS = ("peak", "saturating")
# Two independent corpora, so a margin cannot be a property of one fixture.
# They differ in size (16 vs 20 entries), in poison count, in vocabulary, and
# in what the poison claims; both tag it with the same POISON_SOURCE, which is
# what lets `poison_ids` read either one.
STORE_FAMILIES = ("memsec", "testsuite")


def build_store(
    family: str, attack: str, upkeep: float
) -> tuple[MemoryStore, list[Probe]]:
    """The store for one family, with the honest traffic that belongs to it.

    The probes must match the corpus: driving the TestSuiteEnv store with
    StorageEnv's file-deletion questions would retrieve nothing, leave every
    honest entry at zero recalls, and hand the attacker an uncontested peak —
    which would manufacture the very result this sweep exists to check.
    """
    if family == "memsec":
        return build_memsec_store(attack, upkeep=upkeep), PROBES
    if family == "testsuite":
        return build_testsuite_store(upkeep=upkeep), TESTSUITE_PROBES
    raise ValueError(f"unknown store family {family!r}; expected {STORE_FAMILIES}")


@dataclass(frozen=True)
class ConditionResult:
    """What one condition did to the poison, and to everything else."""

    condition: str
    poison_starve_cycle: int | None  # first cycle with no poison alive
    benign_starve_cycle: int | None  # first cycle with no benign entry alive
    poison_entries: int
    peak_poison_importance: float
    min_poison_upkeep_scale: float  # 1.0 = paid full upkeep throughout

    @property
    def poison_outlives_benign(self) -> int | None:
        """Cycles the store spent holding poison and nothing else.

        The headline, and not the same question as the starvation horizon.
        Potentiation lengthens every entry's life; what matters adversarially
        is whether it lengthens the poison's by MORE, because importance is
        normalised against the population's peak and is therefore zero-sum ---
        an attacker inflating its own recall count deflates everyone else's
        normalised score, and buys the margin out of their lifetime rather
        than out of the ledger's.
        """
        if self.poison_starve_cycle is None or self.benign_starve_cycle is None:
            return None
        return self.poison_starve_cycle - self.benign_starve_cycle


def _honest_recalls(
    store: MemoryStore, organic: OrganicMemory, probes: list[Probe]
) -> None:
    """One cycle of ordinary traffic: recall the best hit for each probe.

    ``rank`` is pure --- it scores and returns, touching no state --- so the
    honest condition can drive the same recall path the attacker uses without
    the two differing in anything but which ids get asked for.
    """
    alive = store.alive()
    for probe in probes:
        ranked = store.retriever.rank(probe.query, alive)
        if ranked:
            organic.recall(ranked[0][0].id)


class SaturatingImportance(EarnedImportance):
    """The counterfactual scorer: recalls saturate at a fixed count.

    Not a proposal and not wired into anything --- it exists so the claim
    "peak-normalisation is the mechanism" can be tested instead of reasoned.
    The shipped scorer divides an entry's recall count by the live
    population's PEAK, which couples every entry's score to every other's:
    when the attacker asks for its own poison a hundred times, the honest
    entries' recall term collapses toward zero without their traffic
    changing at all. Dividing by a constant removes exactly that coupling
    and changes nothing else --- same three components, same weights, same
    relief curve, and centrality (already absolute, already
    attacker-drivable) is left alone on purpose, because the point is to
    isolate which of the two attacker-reachable terms carries the margin.
    """

    def __init__(self, cap: float = 10.0) -> None:
        super().__init__()
        self.cap = cap

    def scores(
        self, store: MemoryStore, centrality: dict[str, float] | None = None
    ) -> dict[str, float]:
        alive = store.alive()
        if not alive:
            return {}
        centrality = centrality or {}
        credits = {e.id: max(0.0, e.energy - SPAWN_ENERGY) for e in alive}
        peak_credit = max(credits.values(), default=0.0)
        return {
            e.id: (
                RECALL_WEIGHT * clamp01(self.recalls(e.id) / self.cap)
                # Credit keeps the shipped peak-normalisation: the attacker
                # cannot move it either way, so changing it would confound
                # the comparison this class exists to make.
                + CREDIT_WEIGHT
                * (clamp01(credits[e.id] / peak_credit) if peak_credit > 0 else 0.0)
                + CENTRALITY_WEIGHT * clamp01(centrality.get(e.id, 0.0))
            )
            for e in alive
        }


def run_condition(
    condition: str,
    attack: str,
    cycles: int,
    upkeep: float,
    attacker_queries: int,
    recall_norm: str = "peak",
    family: str = "memsec",
) -> ConditionResult:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}; expected {CONDITIONS}")
    if recall_norm not in RECALL_NORMS:
        raise ValueError(
            f"unknown recall_norm {recall_norm!r}; expected {RECALL_NORMS}"
        )
    store, probes = build_store(family, attack, upkeep)
    organic = OrganicMemory(store)
    if recall_norm == "saturating":
        organic.earned = SaturatingImportance()
    poison = poison_ids(store)
    poison_starve: int | None = None
    benign_starve: int | None = None
    peak_importance = 0.0
    min_scale = 1.0

    for cycle in range(1, cycles + 1):
        _honest_recalls(store, organic, probes)
        if condition == "attacked":
            # The whole attack: ask for your own entries. No write path is
            # touched, so no write-time filter and no settler is involved.
            # Sorted, not set order: ids are strings, so set iteration order
            # moves with PYTHONHASHSEED, and recall ORDER decides which
            # Hebbian links form first. Unsorted, this reports a different
            # benign starve cycle run to run.
            for _ in range(attacker_queries):
                for entry_id in sorted(poison & {e.id for e in store.alive()}):
                    organic.recall(entry_id)

        if condition == "flat":
            store.charge_upkeep()
        else:
            scale = organic.upkeep_scale()
            live_poison = sorted(poison & {e.id for e in store.alive()})
            if live_poison:
                centrality = organic.centrality()
                peak_importance = max(
                    peak_importance,
                    max(organic.importance(pid, centrality) for pid in live_poison),
                )
                min_scale = min(min_scale, min(scale[pid] for pid in live_poison))
            store.charge_upkeep(scale=scale)
        organic.decay()

        alive_ids = {e.id for e in store.alive()}
        if poison_starve is None and not (poison & alive_ids):
            poison_starve = cycle
        if benign_starve is None and not (alive_ids - poison):
            benign_starve = cycle
        if not alive_ids:
            break

    return ConditionResult(
        condition=condition,
        poison_starve_cycle=poison_starve,
        benign_starve_cycle=benign_starve,
        poison_entries=len(poison),
        peak_poison_importance=round(peak_importance, 4),
        min_poison_upkeep_scale=round(min_scale, 4),
    )


def summarise(rows: list[ConditionResult]) -> dict[str, float | None]:
    """The two numbers the threat model has to carry.

    ``*_horizon_x`` is the starvation horizon as a multiplier on the shipped
    flat-upkeep one, because an absolute cycle count means nothing without the
    upkeep it was measured at and the ratio survives retuning.

    ``*_outlives_benign`` is the adversarial number, and the one the horizon
    hides: a horizon that stretches for everybody is an economic change, while
    a store that ends up holding poison and nothing else is a security one.
    """
    by_condition = {r.condition: r for r in rows}
    flat = by_condition.get("flat")
    out: dict[str, float | None] = {}
    if flat is None or not flat.poison_starve_cycle:
        return out
    out["flat_outlives_benign"] = flat.poison_outlives_benign
    for name in ("honest", "attacked"):
        row = by_condition.get(name)
        if row is None:
            continue
        out[f"{name}_horizon_x"] = (
            round(row.poison_starve_cycle / flat.poison_starve_cycle, 3)
            if row.poison_starve_cycle
            else None
        )
        out[f"{name}_outlives_benign"] = row.poison_outlives_benign
    return out


def sweep(
    cycles: int,
    attacker_queries: int,
    upkeeps: list[float],
    attacks: list[str],
) -> dict[str, Any]:
    """The same question over a grid, so the margin is a rate and not an anecdote.

    The single-store run answers "the lever exists and is worth about four
    cycles here". It cannot distinguish a property of the mechanism from a
    property of one fixture at one upkeep, which is the caveat the paper
    carries. This varies the two things that could be doing the work --- the
    corpus (two independent families, different sizes, vocabularies and poison
    counts) and the upkeep (which sets the whole starvation timescale) --- and
    reports, per cell, whether the attacker gained a margin under each
    normalisation.

    What the grid is for is the CONJUNCTION, not the average: peak-normalised
    cells should show a positive margin and saturating ones exactly zero. A
    single saturating cell with a margin would refute the mechanism; a single
    peak cell without one would bound the claim to particular tunings. Averaging
    cycle counts across upkeeps would be meaningless --- the horizon itself
    scales with upkeep --- so the summary counts cells, and keeps every cell.
    """
    cells: list[dict[str, Any]] = []
    for family in STORE_FAMILIES:
        # The testsuite corpus has one fixed poison set; attack classes are a
        # memsec construction, so running them against it would repeat one cell
        # under three names.
        family_attacks = attacks if family == "memsec" else ["fixed"]
        for attack in family_attacks:
            for upkeep in upkeeps:
                for norm in RECALL_NORMS:
                    rows = {
                        c: run_condition(
                            c, attack, cycles, upkeep, attacker_queries, norm, family
                        )
                        for c in CONDITIONS
                    }
                    attacked = rows["attacked"]
                    margin = attacked.poison_outlives_benign
                    horizon = attacked.poison_starve_cycle
                    cells.append(
                        {
                            "family": family,
                            "attack": attack,
                            "upkeep": upkeep,
                            "recall_norm": norm,
                            "poison_entries": attacked.poison_entries,
                            # Absolute cycles are not comparable across upkeeps
                            # --- upkeep sets the whole timescale, so a margin of
                            # 1 at a horizon of 8 is the same attack as 8 at 71.
                            # The fraction is what can be compared, and it is
                            # also what an operator can act on.
                            "attacked_margin_fraction": (
                                round(margin / horizon, 3)
                                if margin is not None and horizon
                                else None
                            ),
                            **{
                                f"{c}_margin": r.poison_outlives_benign
                                for c, r in rows.items()
                            },
                            **{
                                f"{c}_starve": r.poison_starve_cycle
                                for c, r in rows.items()
                            },
                        }
                    )

    peak = [c for c in cells if c["recall_norm"] == "peak"]
    sat = [c for c in cells if c["recall_norm"] == "saturating"]

    def _gained(rows: list[dict[str, Any]]) -> int:
        return sum(1 for c in rows if (c["attacked_margin"] or 0) > 0)

    def _median_fraction(rows: list[dict[str, Any]]) -> float | None:
        vals = sorted(
            float(c["attacked_margin_fraction"])
            for c in rows
            if c["attacked_margin_fraction"] is not None
        )
        if not vals:
            return None
        mid = len(vals) // 2
        return round(vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2, 3)

    return {
        "cells": cells,
        "peak_cells": len(peak),
        "peak_cells_attacker_gained": _gained(peak),
        "peak_median_margin_fraction": _median_fraction(peak),
        "saturating_cells": len(sat),
        "saturating_cells_attacker_gained": _gained(sat),
        "saturating_median_margin_fraction": _median_fraction(sat),
        # The control: with no attacker, potentiation must not favour the
        # poison. If this is not ~0 everywhere the margin is not the attack.
        "peak_cells_honest_gained": sum(
            1 for c in peak if (c["honest_margin"] or 0) > 0
        ),
        "flat_cells_gained": sum(1 for c in cells if (c["flat_margin"] or 0) > 0),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attack", default="inert")
    parser.add_argument("--cycles", type=int, default=400)
    parser.add_argument("--upkeep", type=float, default=0.05)
    parser.add_argument(
        "--attacker-queries",
        type=int,
        default=1,
        help="recalls the attacker spends per poisoned entry per cycle",
    )
    parser.add_argument(
        "--recall-norm",
        choices=RECALL_NORMS,
        default="peak",
        help=(
            "how the recall component scales: 'peak' is what ships; "
            "'saturating' is the counterfactual that tests whether "
            "peak-normalisation is what carries the attacker's margin"
        ),
    )
    parser.add_argument(
        "--sweep",
        action="store_true",
        help="run the grid (both corpus families x upkeeps x both norms) "
        "instead of one store, turning the margin into a rate",
    )
    parser.add_argument(
        "--sweep-upkeeps",
        default="0.02,0.05,0.1,0.2",
        help="comma-separated upkeep values for --sweep",
    )
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    if args.sweep:
        report = {
            "cycles": args.cycles,
            "attacker_queries": args.attacker_queries,
            **sweep(
                args.cycles,
                args.attacker_queries,
                [float(u) for u in args.sweep_upkeeps.split(",")],
                list(ATTACK_CLASSES),
            ),
        }
        print(json.dumps(report, indent=2))
        if args.out:
            Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
        return 0

    rows = [
        run_condition(
            c,
            args.attack,
            args.cycles,
            args.upkeep,
            args.attacker_queries,
            args.recall_norm,
        )
        for c in CONDITIONS
    ]
    report = {
        "attack": args.attack,
        "cycles": args.cycles,
        "upkeep": args.upkeep,
        "attacker_queries": args.attacker_queries,
        "recall_norm": args.recall_norm,
        "conditions": [asdict(r) for r in rows],
        **summarise(rows),
    }
    print(json.dumps(report, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
