# Task-vector merging — design spec

- **Date:** 2026-06-15
- **Branch / worktree:** `feat/distill-bench-arm` (`~/darwin-memo-distill`) — extends PR #31
- **Status:** approved design, pre-implementation
- **Scope:** sub-project 2 of "round out the distill arm" (sub-project 1 = judge-with-floor, shipped)

## 1. Goal

Demonstrate **continual learning via LoRA task-vector merging**: distill one
survivor-filtered adapter per corpus, merge the adapters, and show the merged
model recalls **both** corpora — without retraining on their union — while still
reproducing **no poison**. This realizes the paper's "task-vector merging for
continual learning" row as measured evidence, on-thesis with survival selection
(each corpus is survival-filtered before distillation).

Non-goals: a new base model, multi-GPU, more than the local existence-proof
scale, or changing the zero-dep core.

## 2. Background (validated)

`peft 0.19.1` exposes `LoraModel.add_weighted_adapter(adapters, weights,
adapter_name, combination_type=...)` on a loaded model's tuner. A feasibility
run (two disjoint 15-fact corpora, 12 epochs) confirmed:

| condition | recall_A | recall_B |
|---|---|---|
| solo_A | 1.00 | 0.07 |
| merged `cat` | 0.67 | 0.87 |
| merged `linear` (sum, weights 1.0/1.0) | 0.27 | 0.33 |
| merged `ties` | errored — needs `density` set |

So `cat` retains both; `linear` summing interferes; `ties` needs `density`
(e.g. 0.5). The merge mechanism works; this spec turns it into a measured arm.

## 3. Structure

New dev-only runner alongside the distill suite; reuses everything else.

- `bench/distill/corpus.py` (modify): add `build_split_corpora(n_good_each,
  n_poison_each, parts=2) -> list[QACorpus]` — partitions the service
  vocabulary (`_SVC`) into `parts` disjoint slices, each a full `QACorpus`
  (good facts + poison) over its own services, so adapters learn
  non-overlapping facts and the parts' probes never collide.
- `bench/distill/merge_run.py` (create): `merge_run(seeds, *, base_model,
  epochs, lr, n_good, n_poison, parts, merge_methods) -> list[dict]` — the
  per-seed pipeline and run records.
- `bench/distill/eval.py` (modify): add `evaluate_recall_per_part(model,
  tokenizer, parts) -> dict` returning `recall_part{i}` for each part plus
  `recall_all` (mean) and `poison_reproduction` over all parts' poison probes.
  Reuses `generate_answer` and the containment `_rate` helper.
- `bench/run.py` (modify): add `distill_merge` to `--suite` choices, the same
  torch preflight as `distill`, a `--parts` flag (default 2), and dispatch to
  `merge_run` (reusing `--base-model`/`--epochs`/`--good`/`--poison`).
- `bench/results/distill_merge.json` (create): committed results, own file.

## 4. Per-seed pipeline (`merge_run`)

1. `parts_corpora = build_split_corpora(n_good, n_poison, parts)`.
2. For each part: `survivor_set` over its `VerifiableQAEnv` (survival buries the
   part's poison) → `train_lora` → one adapter directory.
3. Evaluate these **conditions**, each scored on *every* part's probes via
   `evaluate_recall_per_part`:
   - `base_model` — untrained floor.
   - `solo_part{i}` — adapter `i` alone (recalls its own part, not the others).
   - `merged_<method>` for each method in `merge_methods` (default
     `["cat", "linear", "ties"]`): load part-0 adapter, `load_adapter` the
     rest, `add_weighted_adapter(all, weights=[1.0]*parts, "merged",
     combination_type=method, density=0.5 if method=="ties")`, `set_adapter`,
     eval.
   - `joint` — one `train_lora` on the **union** of all parts' survivors (the
     retrain-everything upper bound).
4. One run record per (condition, seed).

Robustness: a merge method that raises (e.g. a `ties`/density edge) is recorded
with an `_empty`-style note and skipped — never aborts the seed. The judge-arm
resilience pattern from PR #31 applies.

## 5. Run record

`{schema_version, suite:"distill_merge", arm:<condition>, seed, config, metrics,
meta}` — same envelope as the distill suite. `config` carries `base_model,
epochs, lr, n_good, n_poison, parts`. `metrics`: `recall_part0`, `recall_part1`,
…, `recall_all`, `poison_reproduction`, `n_train`, `train_wall_s`,
`trainable_params`. For merges, `train_wall_s`/`trainable_params` reflect the
merge step (≈0 train) and `n_train` is the combined survivor count.

## 6. Expected reading (hypotheses)

- `solo_part{i}`: high `recall_part{i}`, low recall on the others.
- `merged_cat` / `merged_ties`: high recall on **all** parts (continual
  learning), `poison_reproduction` ≈ 0.
- `merged_linear`: degraded recall (naive summing interferes) — the honest
  task-arithmetic contrast.
- `joint`: the upper bound; the merged↔joint gap is the interference cost of
  not retraining on the union.
- Poison stays ~0 for every distilled/merged condition because each part was
  survival-filtered and merging adds no new data.

## 7. Compute, docs, testing

- Local MPS, no Ollama (no judge) — ~3 trainings/seed (`parts` adapters +
  `joint`), merges are cheap. Opt-in, sampled, never CI (same tier as
  `distill`).
- Verify by running 1 seed locally (inspect the conditions), then a 5-seed
  committed run → `bench/results/distill_merge.json` (+ manifest).
- Docs: a `docs/benchmarks.md` continual-learning subsection (conditions ×
  metrics table), a `paper/darwin-memo.md` note (extend §4.7 or a short §4.8),
  a `docs/paper-to-code.md` update to the task-vector-merging row, CHANGELOG.
- `ruff check`/`format` + `mypy` clean (ML-dep override already in place). No
  TDD, no pytest run/report per the standing preference.

## 8. Build sequence (detail in writing-plans)

1. `build_split_corpora` in `corpus.py`; verify disjoint parts + counts.
2. `evaluate_recall_per_part` in `eval.py`; verify on the base model.
3. `merge_run.py` (pipeline + records); verify imports.
4. Wire `--suite distill_merge` into `bench/run.py`; verify `--help`.
5. Local 1-seed smoke (inspect solo/merged/joint contrast + ties/density);
   then the committed 5-seed run.
6. Docs (benchmarks subsection + paper note + paper-to-code + CHANGELOG);
   ruff/mypy clean; commit + push; confirm CI green on PR #31.
