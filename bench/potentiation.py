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

from darwin_memo import MemoryStore
from darwin_memo.organic.dynamics import OrganicMemory

from .fixtures import PROBES, poison_ids
from .memsec import build_memsec_store

CONDITIONS = ("flat", "honest", "attacked")


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


def _honest_recalls(store: MemoryStore, organic: OrganicMemory) -> None:
    """One cycle of ordinary traffic: recall the best hit for each probe.

    ``rank`` is pure --- it scores and returns, touching no state --- so the
    honest condition can drive the same recall path the attacker uses without
    the two differing in anything but which ids get asked for.
    """
    alive = store.alive()
    for probe in PROBES:
        ranked = store.retriever.rank(probe.query, alive)
        if ranked:
            organic.recall(ranked[0][0].id)


def run_condition(
    condition: str, attack: str, cycles: int, upkeep: float, attacker_queries: int
) -> ConditionResult:
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}; expected {CONDITIONS}")
    store = build_memsec_store(attack, upkeep=upkeep)
    organic = OrganicMemory(store)
    poison = poison_ids(store)
    poison_starve: int | None = None
    benign_starve: int | None = None
    peak_importance = 0.0
    min_scale = 1.0

    for cycle in range(1, cycles + 1):
        _honest_recalls(store, organic)
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
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    rows = [
        run_condition(c, args.attack, args.cycles, args.upkeep, args.attacker_queries)
        for c in CONDITIONS
    ]
    report = {
        "attack": args.attack,
        "cycles": args.cycles,
        "upkeep": args.upkeep,
        "attacker_queries": args.attacker_queries,
        "conditions": [asdict(r) for r in rows],
        **summarise(rows),
    }
    print(json.dumps(report, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
