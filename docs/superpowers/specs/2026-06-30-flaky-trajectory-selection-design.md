# Survival-selection of SE-agent training trajectories under flaky verification

**Status:** design, approved in principle 2026-06-30. Awaiting spec review.
**Branch:** `feat/arxiv-paper` (worktree `~/darwin-memo-paper`).
**Immediate target:** Stage 1 (cheap selection-quality gate). Stage 2 fully specified but GATED on Stage 1.

## Motivation

The 2025–2026 literature (see `docs/research/2026-06-30-self-improvement-landscape.md`,
24 primary sources) converged on: learning that moves real-benchmark numbers
lives in **weights** (rejection-sampling SFT / RLVR on verified execution) or
**tools** — not advisory context. We independently measured the same (capable
agents override injected lessons). SWE-Gym (arXiv:2412.21139) is the canonical
cheap, no-judge, no-RM recipe: rejection-sampling SFT on **491 unit-test-verified
trajectories** took a 32B coder **7%→20.6%** on SWE-bench Verified.

Every such recipe assumes a **clean** verification signal. Real test suites are
not clean: CI is **flaky** (a correct change's run intermittently reports failure)
and SWE tests are often **weak/incomplete** (an incorrect patch accidentally
passes). Both corrupt the pass/fail label that decides which trajectories enter
the SFT set. darwin-memo's one proven, unique strength — from its synthetic
suites — is **forgiveness under lying measurements**: a bounded-energy buffer with
earn-back that beats strike-counters when the signal is noisy. This is the
white space: **robust trajectory selection for SE-agent training under
realistic, two-sided verification noise.**

## Claim (hypothesis under test)

Under realistic two-sided verification noise, darwin-memo's bounded-energy
**survival selection** retains a cleaner SFT training set than the SWE-Gym-style
**single-run** pass/fail filter — and than **majority-vote** and **any-pass** —
at the same evaluation budget, and this cleaner set yields a **better SE agent
on SWE-bench** at equal budget.

Honesty up front: **pure one-sided false-negative noise is trivially solved**
("keep if any of N runs passes" perfectly separates when broken patches never
pass), so it is included only as a control. The contribution lives in the
**two-sided** regime (flaky false-neg + weak-test false-pos), where no simple
rule is optimal and a bounded accumulator can win.

## Mechanism (the core IP)

- **Unit of selection** = a candidate solution (patch + trajectory) for a task.
  Sample K candidates/task with the existing harness (BM25 retrieval +
  search/replace edits; `bench/swebench_cl/`).
- Each candidate's fail-to-pass tests are executed **N times**, producing a
  noisy pass/fail sequence (the corrupted signal). At a **fixed total eval
  budget** B (= total test executions), compare four selection rules for "keep
  this trajectory for SFT?":
  - **single-run** (N=1): keep if the one run passes — the SWE-Gym default.
  - **any-pass** (N): keep if ≥1 of N runs passes — the one-sided-noise optimum (control).
  - **majority-vote** (N): keep if ≥⌈N/2⌉ pass — the obvious robustness baseline.
  - **survival (darwin-memo)** (N): each run is a bounded credit event using the
    library's own rule, `c = credit_gain · tanh(Δ/scale)` with pass→+Δ, fail→−Δ,
    energy capped at `max_energy`, spawn at `E0`; keep if final energy > floor.
    The continuous bounded buffer with earn-back is what beats the discrete
    counters under two-sided noise (the synthetic false_bad/flip result).
- Reuse `darwin_memo.assign_credit` / the energy ledger directly — the selection
  rule is the library's existing mechanism applied to a new unit, not a
  reimplementation.
- Optional extension (NOT in Stage 1): adaptive budget — allocate more runs to
  candidates near the energy floor. Keep the core comparison at fixed N.

## Stage 1 — cheap selection-quality gate (immediate target, no GPU)

**Goal:** prove (or refute) the selection edge cheaply, before any SFT spend.

- **Tasks/env:** START on the existing pinned SWE-bench-CL tasks (41:
  pytest 19 + astropy 22) — no new dataset wiring, reuse the existing Docker
  executor with its transient-500 retry. Expand to the larger SWE-Gym pool
  (2,438 tasks, pre-built Docker runtimes) only if candidate volume proves
  insufficient for tight precision/recall curves.
- **Candidate sampling:** the existing harness runs one completion at
  temperature 0; sampling K diverse candidates/task requires temperature > 0
  (e.g. 0.8) — a one-line endpoint change, flagged for the plan.
- **Ground truth:** establish each candidate's TRUE pass/fail by running its
  tests many times (e.g., 21×) on the clean suite and taking the stable
  majority; candidates whose clean signal is itself unstable are labeled
  "intrinsically flaky" and tracked separately.
- **Noise:**
  - *Controlled sweep:* inject two-sided noise on the reported per-run signal —
    false_bad rate `p_fn` (true-pass run reports fail) and false_good rate
    `p_fp` (true-fail run reports pass) — swept independently on a grid. A
    one-sided cell (`p_fp=0`) is included as the trivially-solved control.
  - *Real validation:* a cell using genuinely flaky SWE tests (intrinsically
    flaky tasks from the ground-truth step, and/or a known flaky-test set), to
    show the effect is not a simulation artifact.
- **Metric:** treat selection as binary classification of candidates into the
  SFT set. Report **precision, recall, F1** of the retained set against TRUE
  labels, as a function of (noise rates, budget B, N), for all four rules.
  Secondary: retained-set size and true-positive yield at fixed B.
- **Gate criterion (pre-committed):** survival must **dominate the
  precision/recall frontier** over single-run AND majority-vote across the
  two-sided grid (not just one cell), and at least match any-pass where any-pass
  is optimal (the one-sided control). If it does not dominate in the two-sided
  regime, STOP and report the negative — no SFT spend.

## Stage 2 — the benchmark win (GATED on Stage 1)

- For each selection rule, take its retained trajectory set (at a fixed
  realistic two-sided noise level and budget), **rejection-sampling SFT** the
  SAME base model on each, and evaluate on **SWE-bench Verified / Lite**.
- **Claim:** survival-selected SFT > single-run-selected SFT (and ≥ majority-vote)
  at equal eval budget. Anchor to SWE-Gym's published 7%→20.6% (32B) under a
  clean signal as the reference, and report all rules' numbers under the noisy
  signal.
- **Scale path (avoids a blind big spend):** prove the trend at **14B** first
  (cheaper), spend on **32B** for the headline number only if the 14B trend
  holds. (SWE-Gym's 7B was only 7%→10% — too small loses the signal; 14B is the
  cheapest scale that should show it.)
- **No reward model, no LLM judge, no RL** — rejection-sampling SFT only.

## Components to build

1. `bench/swebench_cl/select.py` (or a `selection/` module) — the four selection
   rules over an N-run pass/fail sequence per candidate, with `survival` calling
   the library's energy ledger. Pure, unit-testable-by-running.
2. Candidate generation — reuse the existing agent harness to sample K
   candidates/task; persist (task, candidate, trajectory, patch).
3. Ground-truth + flaky-injection harness — many-run true labeling; a
   two-sided noise injector (`p_fn`, `p_fp`) with per-(seed, candidate, run)
   marks; a real-flaky cell.
4. Stage-1 metrics + report — precision/recall/F1 curves per rule vs noise/budget;
   a markdown summary; committed result JSONs bound to a manifest.
5. (Stage 2, later) SFT pipeline (cloud GPU; out of this Mac) + SWE-bench eval at
   scale (x86 box) — specified, not built until the gate passes.

## Constraints (preserved from darwin-memo's spirit)

- Conserved/verifiable signal only (test pass/fail counts); **no reward model,
  no LLM judge, no human labels** in the selection loop.
- Stage 1 is cheap (test re-runs + selection logic; linux x86 box; low-hundreds-$
  or less). Stage 2 is real cloud cost — flagged, gated, staged 14B→32B.
- Reuse the library's actual energy-ledger credit rule for `survival`; do not
  reimplement selection.

## Resource reality (decision was made with eyes open)

- Stage 1: cheap; no GPU; runs on the existing harness + an x86 runner for test
  re-runs; modest API for candidate generation.
- Stage 2: 32B SFT needs cloud multi-GPU (this Mac cannot); candidate generation
  across hundreds of tasks needs real API/compute; SWE-bench Verified eval (500
  tasks × K) wants x86 (emulation too slow). Credible 32B ≈ low-thousands-$
  all-in. 14B proof ≈ low-hundreds-$. Gated on Stage 1; staged 14B→32B.

## Success criteria

- **Stage 1 (gate):** survival dominates the precision/recall frontier over
  single-run and majority-vote across the two-sided noise grid, matches any-pass
  on the one-sided control, and the edge holds in the real-flaky cell. Either
  outcome (edge or honest null) is a reportable result.
- **Stage 2 (win):** survival-selected SFT beats single-run-selected SFT on
  SWE-bench Verified/Lite at equal budget under a realistic noisy signal — the
  measurable benchmark win that is the publishing bar.

## Honest caveats (carry into any claim)

- **SOTA drift:** SWE-Gym's 32% is already superseded (~37%+ by mid-2026). The
  claim is a *controlled head-to-head* (same base, same budget, survival vs
  single-run/majority-vote under matched noise), NOT a raw leaderboard topline —
  state it that way; re-pull the live leaderboard before any absolute "beat".
- **Pure one-sided noise is trivial** (any-pass solves it) — the contribution is
  explicitly the two-sided regime; we report the one-sided control to show we
  know the difference.
- **SWE-Gym's cheap win used teacher-generated trajectories** filtered by tests;
  the self-generated variant regressed. Our claim is about the SELECTION RULE at
  fixed trajectory source/budget, not about self-generation.
- **Not apples-to-apples across the literature** (base model, scaffold, pass@k,
  subset) — we control this by comparing rules within one fixed setup.
- **Unit-of-selection assumption:** the energy buffer's value over majority-vote
  must be demonstrated, not assumed; Stage 1 is precisely that test, and a null
  there ends the project cheaply.
