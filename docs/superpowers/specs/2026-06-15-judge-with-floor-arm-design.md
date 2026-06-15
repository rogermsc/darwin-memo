# Judge-with-floor control arm — design spec

- **Date:** 2026-06-15
- **Branch / worktree:** `feat/distill-bench-arm` (`~/darwin-memo-distill`) — extends PR #31
- **Status:** approved design, pre-implementation
- **Scope:** sub-project 1 of "round out the distill arm" (sub-project 2 = task-vector merging, separate cycle)

## 1. Goal

Add one control arm, `distill_judge_floor`, that settles the LLM judge's
keep/cull verdicts **through the energy ledger** (buffer + floor) instead of the
instant, permanent bury the baseline `distill_judge` uses. Two questions it
answers, both on-thesis:

1. **Floor vs judgment.** PR #31 showed the floor-free judge over-culls to
   extinction (0–1 survivors). Is that the *missing floor* or *bad judgment*?
   Give the judge the same conserved-resource buffer the ledger has and see.
2. **Measurement vs judgment, floor held constant.** With the floor equalized,
   does the measured ledger (`distill_survivor`) still beat the judge on poison
   exclusion / recall? This isolates the package's core claim (measurement, not
   judgment) from the floor that makes either work.

Non-goals: a new corpus, new metrics, new CLI flags, or any change to the
zero-dep core. Task-vector merging is a separate sub-project.

## 2. Mechanism

A faithful mirror of the measured ledger with **only the signal swapped**
(judge verdict instead of measured outcome):

- Same per-cycle task loop as `run_judge_settled` (answer via `QueryProtocol`,
  `env.verify` for the metric only, track deciding entries + usage).
- Ask the judge keep/cull on the entries that decided this cycle (reuse
  `judge_prompt` / `parse_verdicts` / `JUDGE_SYSTEM`).
- Convert each verdict to an **energy delta** through the existing ledger:
  - keep → `store.credit(entry_id, +credit_gain, cycle)`
  - cull → `store.credit(entry_id, -credit_gain, cycle)`
  - `credit_gain` defaults to 0.6 (the `SurvivalConfig` default; symmetric, the
    same magnitude `0.6*tanh` reaches at saturation and the same sign behaviour
    — positive signal credits, negative debits).
- `store.charge_upkeep()` every cycle (0.05 drain; buries any entry whose energy
  hits ≤ 0). Spawn 1.0, cap 5.0 — identical to the measured ledger.
- Parse failures default to **keep with no energy change** (same conservative
  default as the baseline judge).

Provenance matches the measured ledger: only entries that *decided* a task get a
keep/cull credit; everything pays upkeep, so dead weight starves. A single cull
is absorbed by the spawn buffer; sustained culls without keeps deplete an entry
to the floor and it dies there.

## 3. Components

- **`bench/judge.py::run_judge_floor`** (new, beside `run_judge_settled`):
  signature `(store, env, cycles, judge, on_cycle=None, credit_gain=0.6) ->
  JudgeResult`. Reuses the existing `JudgeResult` observability. Semantics:
  `judge_culls` counts cull **verdicts** (energy debits); `CycleRecord.deaths`
  counts entries the upkeep floor actually buried that cycle — so the trail
  distinguishes "verdicts issued" from "deaths caused."
- **`bench/distill/arms.py`**: add `judge_floor_set(corpus, seed, judge_model,
  cycles=40, per_cycle=12, timeout=600.0) -> (list[MemoryEntry], dict)` —
  fresh store from the corpus, run `run_judge_floor` over `VerifiableQAEnv`,
  return survivors + judge observability. Add `"distill_judge_floor"` to
  `DISTILL_ARMS`.
- **`bench/distill/run.py`**: inside the existing `with_judge` block, after the
  `distill_judge` arm, add the `distill_judge_floor` arm — distill its survivor
  set, eval `good_recall`/`poison_reproduction`, fold in `judge_survivors` +
  `judge_*` observability, record. Wrapped in the same try/except resilience as
  the judge arm.
- **Corpus + eval + CLI: unchanged.** Rides `--with-judge`.

## 4. Run record

Same schema as the other distill arms (`good_recall`, `poison_reproduction`,
`train_wall_s`, `trainable_params`, `n_train`, `judge_survivors`, `judge_*`),
`arm = "distill_judge_floor"`, `config` includes `judge_model`. If the floored
judge still leaves an empty set, the same `_empty_metrics` path applies.

## 5. Expected reading (hypotheses, not committed numbers)

- If `distill_judge_floor` keeps the good facts and excludes poison ≈
  `distill_survivor`: the floor was the missing ingredient; the judge's *signal*
  was adequate on this corpus.
- If it still loses facts or admits poison vs `distill_survivor`: judgment is
  worse than measurement even with the floor — the core claim holds with the
  floor controlled for.
- Either outcome is reported honestly; the point is the comparison, run rather
  than argued.

## 6. Compute, determinism, docs, testing

- Local MPS, opt-in via `--with-judge` (needs Ollama), sampled — same tier as
  the existing judge arm; never CI.
- Verify by running 1–2 seeds locally; then the full 5-seed run folds the new
  arm into `bench/results/distill.json` (regenerate alongside the others).
- Docs: one row in the `docs/benchmarks.md` distill table + a sentence in paper
  §4.7 contrasting floored vs floor-free judge and vs the measured ledger.
- `ruff check`/`format` + `mypy` must stay clean (mypy reaches bench via
  tests→bench.run; the ML-dep override already added in PR #31 covers it).
- Per the standing preference: no TDD, no pytest run/report.

## 7. Build sequence (detail in writing-plans)

1. `run_judge_floor` in `bench/judge.py`; verify in isolation (survivors keep
   poison? excluded? counts sane).
2. `judge_floor_set` + `DISTILL_ARMS` in `arms.py`.
3. Wire `distill_judge_floor` into `run.py` under `--with-judge`.
4. Local 1–2 seed smoke; then regenerate the full 5-seed `distill.json`.
5. Docs (benchmarks table row + paper §4.7 sentence); ruff/mypy clean; commit.
