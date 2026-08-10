# Phase 2: mechanism depth — design spec

- **Date:** 2026-08-10
- **Status:** approved design, pre-implementation
- **Scope:** Phase 2 of the four-phase programme (Phase 1 shipped as `feat/operator-surface`, 23 commits, unmerged)
- **Target release:** 0.7.0

## 1. Goal

Make **removal by disuse** legible. It is the one property a counter cannot
replicate, and the Aug-3 benchmarks left it as the ledger's only real edge — but
today it is invisible: an operator cannot see how close an entry is to starving,
and the economics panel has to estimate the upkeep it reports.

Three deliverables, deliberately small. **Add no new selection knob** — upkeep
already *is* the disuse policy, and a second way to say the same thing is how a
mechanism gets two sources of truth.

## 2. Two independent tracks, not one stack

Phase 1 is unmerged on `feat/operator-surface`, and PRs #33/#34 target `main`.
Stacking everything would make a three-deep chain. The work splits cleanly
because it does not overlap on a single file:

- **Track A** — `ticks_to_starvation` + exact upkeep. Branches from
  `feat/operator-surface` (it extends Phase 1's `economics()` and `state()`).
- **Track B** — the organic PRs. Stays on the existing `feat/organic-memory`
  and `feat/organic-memory-phase2` branches, which touch only
  `darwin_memo/organic/` and docs. Merges to `main` independently.

Neither track blocks the other, and neither needs the other to merge first.

## 3. Track A1 — `ticks_to_starvation` as one definition

Today it is computed inline in `darwin_memo/ui.py`'s `state()` as
`energy / upkeep`. CLI and MCP cannot reach it, so the number an operator sees in
the browser has no terminal equivalent.

Promote it to a store-level helper so all three surfaces read one definition.
It answers the operator's actual question — *how long has this entry got?* —
and it is the number that makes the 20-tick cliff visible before it bites.

Edge cases that must be decided in the helper, not per-caller: `upkeep <= 0`
(no starvation is possible; the answer is "never", not a division), and a pinned
entry (whose balance floors at zero rather than dying, so it also never starves).
`ui.py` drops its inline arithmetic and calls the helper; `top`/`why` gain the
field.

## 4. Track A2 — exact upkeep in the tick event

`economics()` currently estimates upkeep as `Σ(population_t × upkeep)` and
flags `upkeep_exact: false`. The estimate is wrong by exactly the amount pinned
entries have forgiven at the zero floor.

`MemoryStore.charge_upkeep` has **seven callers** (`survival.py`, `ledger.py`,
three in `bench/`, two in `tests/`), so changing its return type would ripple
through all of them for one number. Instead it records what it actually deducted
on the store, and `Ledger.tick()` puts that figure in the tick event it already
writes. `economics()` prefers the logged value and sets `upkeep_exact: true`;
when the field is absent — every log written before this release — it falls back
to the estimate exactly as now. The dashboard's "estimated" marker then
disappears on new runs without any frontend change.

## 5. Track B — the organic PRs, and the invariant that gates #34

**#33 (associative graph)** merges. Additive, opt-in, zero-dep default backend,
and it powers a related-entries view in the drawer later.

**#34 (activation + gist↔detail)** merges **only** with the invariant defended
by tests: *activation must never influence retention.*

The evidence for the invariant is this repo's own `salience_matched` arm:
usage-importance as a retention signal **shields consulted poison** — kill rate
falls to 0.20 against random's 0.80, because it cannot distinguish "used" from
"useful". An activation signal that fed retention would reintroduce exactly that.

The invariant currently holds **by construction and is undefended**:
`activation.py` is a pure in-memory id→float map plus a surfacing helper, its
docstring says it "never feeds the energy ledger and never keeps a dead entry
alive", and nothing outside `organic/` references it. Phase 1 taught that a
documented property is not a defended one — three of its tests were proven
decorative by mutation. So this gets two tests, not a comment:

1. **Structural.** No module in the selection path — `store`, `ledger`,
   `survival`, `consolidate` — imports or references activation. Crude, exact,
   and the right shape for an architectural rule: it fails the moment someone
   wires the two together, which is the failure we care about.
2. **Behavioural.** Run selection twice over identical seeds, once with a
   poisoned entry's activation pinned at maximum. It must die on the same cycle
   both times. This is the property the structural test cannot prove: that
   activation *cannot* shield an entry even if something did read it.

Each test must be shown to fail against a deliberately-wired violation before it
is trusted.

## 6. Out of scope, and one flag

No new selection knob. No changes to selection mechanics. No frontend work
beyond `ui.py` calling the new helper.

**Flag:** a local `feat/organic-memory-phase3` branch exists with no PR —
"spreading activation + Hebbian reweighting". Hebbian reweighting is precisely
where the §5 invariant would be violated if the reweighting touched retention
rather than surfacing. Whatever Phase 3 becomes, it inherits both tests.

## 7. Verification

- `ticks_to_starvation` agrees across `darwin-memo top`, the MCP tool and
  `/api/state` on the same store — one definition, three surfaces.
- On a store with pinned entries, logged upkeep and the old estimate differ, and
  the logged one matches the sum of energy actually deducted.
- An old event log (no upkeep field) still reports `upkeep_exact: false` and the
  same number it reports today — no regression for existing stores.
- Both invariant tests fail against a deliberately-wired violation.
- The Phase 1 acceptance gate still holds: `darwin-memo doctor` reports clean on
  the healthy 30-cycle demo store and `starvation_cliff` on the never-earning one.
