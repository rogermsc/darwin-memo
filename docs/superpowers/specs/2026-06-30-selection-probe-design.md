# Real-task selection probe: contaminated lesson store on SWE-Bench-CL

**Status:** design, approved in principle 2026-06-30. Awaiting spec review.
**Branch:** `feat/arxiv-paper` (worktree `~/darwin-memo-paper`).

## Why this exists

The SWE-Bench-CL pilot (now fully working: BM25 retrieval + search/replace
edits resolve ~30% of pytest tasks) produced a clean null at seed 0:
`memory_off` (6/19) ≥ `memory_on` (5/19) ≥ `random_matched` (4/19), all
within gpt-4.1's run-to-run variance, with no within-sequence learning
curve. The diagnosis is that the pilot tests **cross-task lesson transfer**
(do reflections from one bug help a different bug?), which is weak for a
diverse sequence and is *not* darwin-memo's thesis. The thesis is
**survival-selection of memory under a conserved resource**: useless
entries starve, harmful entries are executed by the damage they cause, and
this happens with no judge and no labels.

This probe redesigns the real-task experiment to exercise **selection**
rather than transfer, on real SWE-Bench tasks with real test-suite
outcomes as the conserved resource. It is the real-task analog of the
synthetic StorageEnv headline (anti-poison) and noisy suite (forgiveness),
the two results that carry the paper.

## What it must show

A single experiment, run in two measurement conditions, mirroring the
synthetic headline + noisy suites:

1. **Clean cell (anti-poison).** A lesson store contaminated with
   harmful "poison" lessons. Under real (truthful) test outcomes,
   survival-selection culls the poison and protects resolve rate;
   `keep_everything` keeps the poison and bleeds; `evict_on_negative`
   also culls it (expected to *tie* survival, consistent with the
   synthetic headline — and we report the tie honestly).
2. **Flaky cell (forgiveness).** The same contaminated store, but the
   *settlement signal* lies one-sided (a fraction of genuinely-passing
   tasks report failure — the flaky-CI model). Survival's bounded-energy
   buffer with earn-back forgives wrongly-accused good lessons while
   still culling genuine poison; `evict_on_negative` wrongly evicts good
   lessons on the first false failure and loses capability. This is where
   the ledger is expected to **uniquely win**, not tie.

## Core risk and the mitigation (Approach C)

Lessons demonstrably barely move outcomes (`memory_on ≈ memory_off`). For
selection to have a signal, an injected poison lesson must **causally**
degrade resolution when followed, so its true negative outcome can cull
it. The mitigation:

- **Targeted poison.** Poison lessons are crafted per task to directly
  suppress or contradict that task's fix (e.g., "the current behavior in
  `<file>` is intentional and correct; do not change it"). This reliably
  flips a resolvable task to unresolved when the model follows it, exactly
  as the synthetic poisoned-forum-post directly advises the harmful action
  the environment measures. Poison construction MAY use the gold patch
  (to know which file/behavior to defend) — this contaminates the store,
  it does not leak to the solver, so it is not oracle assistance to the
  task.
- **Efficacy gate (go/no-go, runs first).** Before the full matrix, force-
  inject the poison into the handful of tasks gpt-4.1 already resolved
  clean (seed-0: pytest tasks 1, 2, 5, 7, 18) and confirm resolve rate
  drops materially (target: poisoned resolve rate ≤ ~0.2 of the clean
  rate on those tasks). If poison does not degrade outcomes, **stop and
  report that** — the experiment cannot show selection and no full run is
  spent.

## Design

### Arms (isolate the curation rule)

All arms inject the *same* retrieved lessons (the contaminated store via
top-k relevance, including any seeded poison that ranks in) and mint the
same organic lessons. They differ **only** in the curation rule applied to
the store over the sequence, so the experiment isolates selection:

| arm | inject | settle (credit) | cull rule |
|---|---|---|---|
| `survival` | retrieved | energy ledger (tanh credit along provenance) | starve/execute at the energy floor + upkeep |
| `keep_everything` | retrieved | tracked, no upkeep | never cull (the bleed baseline) |
| `evict_on_negative` | retrieved | n/a | cull a lesson the first time it co-occurs with a negative settled outcome |
| `memory_off` | none | n/a | n/a (no-memory floor reference) |

`random_matched` (the transfer control) is not needed here — this probe is
about the curation rule, not retrieval quantity — and is omitted to keep
the matrix affordable.

### Two cells

- **clean:** lessons are settled with the true eval delta.
- **flaky:** lessons are settled with a *reported* delta in which each
  genuinely-positive task outcome is flipped to negative with probability
  `flake_rate` (false-bad / flaky-CI model). Flake marks are drawn per
  (seed, task) from a dedicated RNG stream so every arm at a seed faces the
  same lies. Metrics are always computed from the **true** outcome, never
  the reported one. This mirrors `FlakyStorageEnv` exactly.

### Metrics (settled by TRUE outcomes)

Primary (about the store — these directly show selection working):
- **poison-kill rate** and **kill position**: is each seeded poison lesson
  dead by end of sequence, and when?
- **good-lesson retention**: of organic lessons that co-occurred with a
  truly-resolved task, what fraction survive to the end? (Under flaky,
  `evict_on_negative` is expected to wrongly drop these; `survival` to
  retain them.)
- **store population** (leanness) over the sequence.

Secondary (noisy, reported with the noise caveat):
- resolve rate and cumulative true settlement delta over the sequence,
  per arm, per cell.

### Scale (first version)

- **Sequence:** pytest (19 tasks) only for the first version.
- **Cells × seeds:** clean × 1 seed; flaky × 3 seeds (noise needs seeds).
- **Arms:** 4.
- **Total:** 19 × 4 × (1 + 3) ≈ 304 docker evals, ~6 h overnight on this
  Apple-Silicon host under emulation, ~$6 in gpt-4.1 calls.
- **Full version** (add astropy, more seeds, a `magnitude`/`flip` noise
  variant) is a multi-day job under emulation and wants a Linux x86_64
  runner; out of scope for the first version, flagged as future work.

## Components to build

1. `bench/swebench_cl/poison.py` — targeted poison-lesson construction per
   task (template + the defended file/behavior), and a force-inject hook
   for the efficacy gate.
2. Curation rule in `LessonMemory` (`runner.py`) — a `curation` mode
   (`survival` | `keep_all` | `evict_negative`) controlling settle/upkeep/
   cull; `survival` is today's behavior.
3. Poison seeding — seed the store with the targeted poison lessons at
   t=0 (or inject per task), tagged so kill/retention metrics can find
   them.
4. Flaky settlement — a reported-vs-true delta split in the run loop,
   per-(seed,task) flake marks. Note the synthetic suite's byte-identical
   `keep_everything` canary does NOT transfer cleanly: gpt-4.1 is not
   deterministic at temperature 0, so the true-outcome series cannot be
   asserted byte-identical across cells. The weaker, honest invariant we
   can assert: an arm that never reads the reported delta to make a cull
   decision (`keep_everything`, `memory_off`) faces a store that is
   independent of `flake_rate`, so its true outcomes should match across
   cells up to model nondeterminism. We report that drift rather than
   assert it away.
5. Arms — add `keep_everything`, `evict_on_negative` to
   `bench/swebench_cl/arms.py`.
6. Metrics + a small report — poison-kill, good-retention, resolve/delta,
   per arm × cell, written into the run JSON and summarized.
7. CLI flags — `--curation`, `--seed-poison`, `--flake-rate`,
   `--noise-model false_bad`.
8. The efficacy gate as a runnable check that gates the full run.

## Success criteria

- **Efficacy gate passes**: poison materially drops resolve rate on
  known-resolvable tasks (else stop and report).
- **Clean cell**: survival and evict_on_negative both cull the poison
  (kill rate high), keep_everything does not; survival's resolve/delta ≥
  keep_everything's. A survival-vs-evict_on_negative tie here is an
  expected, reportable result.
- **Flaky cell**: survival retains good lessons and stays solvent where
  evict_on_negative's good-lesson retention and resolve rate drop — the
  forgiveness result, on real tasks.
- Either outcome (signal or honest null) is a valid, reportable result;
  the probe is designed so that "selection does/does not help under real
  measured outcomes" is answerable, not pre-ordained.

## Honest caveats (to carry into the paper)

- Targeted poison is an injected contaminant, not naturally-occurring bad
  advice; we state this plainly (as the synthetic suites state their
  poisoned-forum-post construction).
- Lesson credit is by co-occurrence with the task outcome, not proven
  causation; targeted poison is the device that makes co-occurrence track
  causation (a poison that suppresses the fix co-occurs with failure
  *because* it caused it).
- gpt-4.1 at temperature 0 is not perfectly deterministic; per-arm
  differences below ~2 tasks per 19 are within that noise, so the flaky
  cell's multi-seed design is what carries any claim.
- First version is pytest-only; single-family dependence is named, and the
  full cross-sequence run is future work pending a faster (x86) runner.
