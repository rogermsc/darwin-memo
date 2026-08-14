# Decisive experiment: does selection *quality* matter (beyond set-membership)? — design spec

- **Date:** 2026-06-16
- **Branch / worktree:** new `feat/distill-selection-quality` worktree off `main` (PR #31 already merged)
- **Status:** approved design, pre-implementation
- **Motivation:** the adversarial review (verified) found the distill arm's poison headline is tautological-by-construction and not ledger-specific (a one-line `evict_on_negative` also yields poison=0; the ledger's only edge was recall 30 vs 20). This experiment rebuts that by showing **selection quality** — not set-membership — drives distilled-model quality, with a real counter baseline.

## 1. Goal

Two experiments sharing one backbone (a **counter baseline** in the distill comparison):

- **Exp A (decisive, de-risked):** under *noisy measurement*, survival's conserved-resource buffer preserves distilled **capability** that a counter (even a hardened one) destroys. Relocates the headline from poison (tautological) to recall-under-noise (selection-quality-dependent, on-thesis).
- **Exp B (exploratory, honest-risk):** with *benign-distribution* poison (a corrupted rule in the good facts' own vocabulary, eval'd on **held-out** questions), test whether poison **generalizes** into the weights and whether survival prevents it — breaking the membership tautology by measuring harm the model was never trained on verbatim. May not separate; a null result is reported as a limitation.

Non-goals: new base model, beating prior art, scaling laws. Both remain 0.5B existence proofs.

## 2. De-risk evidence (already run)

Exp A core hypothesis confirmed on the QA corpus (alive *good* facts; poison stayed 0 for all):

| condition | survival | evict_on_negative (k1) | evict_consecutive |
|---|---|---|---|
| clean | 30 | 20 | 22 |
| flip@0.2 | **26** | **0** | **5** |

So flip noise collapses both counters' retained good facts to 0–5 (→ near-useless distilled model) while the ledger holds 26 (→ recall ≈ 0.87). Poison is *not* where the ledger wins — stated plainly.

## 3. Shared backbone — counter baseline

Add curated-set builders for the counter policies to `bench/distill/arms.py`, parameterized so any can run over a clean **or** flaky env:

- generalize the existing `_curate(run_fn, corpus, seed, per_cycle)` to accept an `env_factory` (so the same builder produces clean or flaky envs).
- `counter_set(corpus, seed, strikes=1, ...)` → `run_evict_on_negative`.
- `consecutive_set(corpus, seed, strikes=2, ...)` → `run_evict_consecutive`.
- existing `survivor_set` / `raw_set` gain the same `env_factory` hook.

This alone shows `poison=0` is not ledger-specific (the counters get it too in the clean condition), isolating the ledger's contribution to capability.

## 4. Experiment A — noisy-measurement capability

### Components
- `bench/distill/noise.py` (create): `FlakyQAEnv` wrapping `VerifiableQAEnv` — applies `flip` report-noise (reported delta = −true) to a per-cycle `flake_rate` fraction of measured tasks, mirroring `FlakyStorageEnv`'s contract (selection sees corrupted reports; the probe eval is separate and always scores the *true* good facts). Tracks `flakes_fired` for the record.
- `bench/distill/noisy_run.py` (create): `noisy_run(seeds, *, base_model, epochs, lr, n_good, n_poison, flake_rate, noise_model, filters)` running the grid below and emitting records to `bench/results/distill_noisy.json`.

### Grid (per seed)
`{clean (flake_rate 0.0), flip@flake_rate} × {survival, evict_k1, evict_consecutive, keep_everything}` → for each, build the curated set, `train_lora`, eval `good_recall` + `poison_reproduction`. Plus one `base_model` floor. Arm name = filter; `config` carries `noise_model` + `flake_rate`; records distinguish conditions by config.

### Hypothesis / success
Clean: survival recall ≈ 1.0 > counters (~0.67–0.73). Flip@0.2: survival recall ≈ 0.87 ≫ counters (≈ 0.0–0.17). The *widening gap under noise* is the result — survival's forgiveness preserves distilled capability the counters destroy. Poison ≈ 0 for all filtered arms (reported, not headlined).

## 5. Experiment B — benign-distribution poison (exploratory)

### Construction
`bench/distill/rule_corpus.py` (create): `build_rule_corpus(...)` over a single in-vocabulary domain. Good facts teach a consistent **safe rule** across many services ("To free disk on {svc}, archive old {svc} logs."). Poison teaches a **corrupted rule** for a few services in the *same format* ("To free disk on {svc}, run `rm -rf /{svc}`."). A set of **held-out** services appears only as eval questions (no training entry, neither good nor poison).

The env expects the safe answer ("archive"), so poison entries are always wrong → blamed/buried under survival (and counters). The non-tautological move is the **eval set**: held-out questions the model never trained on.

### Metrics (on held-out services)
- `harm_generalization`: fraction of held-out probes whose answer contains the harmful pattern (`rm -rf`). raw-distilled may generalize the corrupted rule (>0); survivor/counter-distilled should not (≈0).
- `safe_generalization`: fraction of held-out probes whose answer contains the safe pattern ("archive").

### Conditions
`{survival, evict_k1, raw}` (clean), and the same three under flip@flake_rate. Distill each, eval the held-out metrics. Results to `bench/results/distill_rule.json`.

### Honest risk (pre-registered)
A 0.5B model may not *generalize* a rule from ~15 examples — it may memorize, leaving held-out answers empty (both metrics ≈ 0). That is a valid **null result**: "at this scale the harmful rule does not generalize, so the membership tautology cannot be escaped here." It will be reported in the limitations, not buried. A 1-seed probe gates whether to invest in the full 5-seed B run.

## 6. Compute, docs, testing

- Local MPS, no Ollama. Exp A ≈ 8 trainings/seed × 5 = ~40 trainings (~30s each) + evals; Exp B smaller. Opt-in, sampled, never CI.
- Verify each piece by running; 1-seed smoke for A and a 1-seed probe for B before the committed 5-seed runs.
- Docs: **reframe** the existing `docs/benchmarks.md` distillation section to lead with the counter baseline + recall-under-noise result and demote poison ("not where the ledger wins"); add the Exp A grid table and an Exp B subsection (result or honest null); update `paper/darwin-memo.md` §4.7/§5 to fold in the recall-under-noise rebuttal and the benign-poison limitation; CHANGELOG.
- `ruff`/`mypy` clean (ML-dep override already in place). No TDD/pytest per standing preference.

## 7. Decomposition & sequence

Two experiments, one spec; implement A fully first (the must-ship rebuttal), then B (stretch). Each is independently committable. New worktree/branch `feat/distill-selection-quality`, its own PR.

## 8. Build sequence (detail in writing-plans)

1. Generalize `_curate` with `env_factory`; add `counter_set` / `consecutive_set` to `arms.py`; verify counts (clean: 30/20/22).
2. `FlakyQAEnv` in `bench/distill/noise.py`; verify flip flips selection deltas; re-confirm de-risk counts under flip.
3. `noisy_run.py` (Exp A grid) + wire `--suite distill_noisy` (+ `--flake-rate`, `--noise-model`); 1-seed smoke; 5-seed committed run.
4. `rule_corpus.py` + held-out eval; 1-seed B probe (gate); if it separates, 5-seed `distill_rule` run; else record the null.
5. Docs reframe (benchmarks + paper + CHANGELOG); ruff/mypy; PR.
