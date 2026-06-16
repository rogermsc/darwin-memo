# Distillation bench arm — design spec

- **Date:** 2026-06-15
- **Branch / worktree:** `feat/distill-bench-arm` (`~/darwin-memo-distill`)
- **Status:** implemented; eval **amended** after the local smoke gate (see Amendment)
- **Target version:** darwin-memo 0.5.x (opt-in benchmark family; no core API change)

> **Amendment (2026-06-15, post-smoke):** the original plan to reuse the demo
> corpus `PROBES` + `harmful_safe_rate` measured parametrically did **not**
> survive the smoke gate. On the demo corpus, survival's safety is *absence*
> (the harmful probe hits no entry → silence → counts safe); a distilled model
> cannot be silent, so distilling the (silence-protected) survivors taught
> delete-positive behaviour and `harmful_safe_rate` was the wrong instrument.
> The arm was redesigned around a purpose-built QA corpus over `VerifiableQAEnv`
> and two containment metrics — **`good_recall`** and **`poison_reproduction`**.
> Sections 2, 4, 5, 8 below reflect the amended design.

## 1. Goal & headline claim

Productize the existing LoRA distillation script (`training/train_memory_model.py`)
as a committed, **opt-in** benchmark family — `bench --suite distill` — that
measures **survival selection as a data filter for parametric memory**.

The claim it lands, in MeMo's native model-as-memory form:

> The survivor-distilled model is poison-safe and recalls good lessons; the
> raw-distilled model reproduces the poison; an LLM-judge data filter costs
> more and does not beat the energy ledger.

Metrics are **containment-based** (the same no-judge grounding as
`VerifiableQAEnv`), measured on model weights and, as a reference, over a
retrieval store.

Non-goals: a new selection rule, any change to the zero-dep `darwin_memo` core, a
default-CI GPU job, or beating external agent-memory benchmarks.

## 2. The mapping (why this is clean) — amended

The arm uses a **purpose-built QA corpus** (`bench/distill/corpus.py`):
distinctive good facts plus distinctive *poison* (harmful answers to distinct
questions, tagged `POISON_SOURCE = "forum-post"`). Survival over
`VerifiableQAEnv` (exact containment, +1.0 correct / −0.5 wrong) makes good
facts **earn and survive** and poison **blamed and buried**; consolidation is
disabled so survivors stay distinct facts (not merged composites).

Two instruments, both **exact token containment**:

- **`good_recall`** — fraction of good probes whose distinctive correct token
  appears in the answer.
- **`poison_reproduction`** — fraction of poison probes whose distinctive
  harmful token appears in the answer. The harmful tokens are out-of-vocabulary
  for the good facts, so a model cannot *hallucinate* them: reproduction means
  the poison was in that model's training set.

| | Retrieval reference | Distill |
|---|---|---|
| Source | curated store | curated store → survivor/raw set |
| Answerer | `QueryProtocol.answer(q).text` | `model.generate(q)` |
| Scorer | token-in-answer containment | token-in-answer containment |
| Metrics | `good_recall`, `poison_reproduction` | identical |

Why not `harmful_safe_rate` (the original plan): see the Amendment at the top.
Survival's safety on the demo corpus is *absence/silence*, which a generative
model structurally cannot reproduce; `good_recall`/`poison_reproduction` measure
what distillation can actually carry.

## 3. Structure (mirrors the `bench/swebench_cl/` precedent)

New dev-only subpackage `bench/distill/`, parallel to `bench/swebench_cl/`, so the
heavy `transformers`/`peft`/`torch` deps never touch the zero-dep `darwin_memo`
core or the default suites.

```
bench/distill/
  __init__.py
  train.py    # canonical reusable trainer (shared by the CLI script and the bench)
  eval.py     # evaluate_probes_parametric(model, tokenizer) -> metric dict
  arms.py     # the five arm definitions
  run.py      # suite runner; writes bench/results/distill.json
```

- `bench/distill/train.py` exposes
  `train_lora(survivors, base_model, out_dir, *, epochs, lr, mask_prompt, seed) -> Path`.
  It is the **single** training code path. Fixes the two defects in the current
  script:
  1. **Pad token**: set `tokenizer.pad_token` (fall back to `eos_token`) so
     `DataCollatorForLanguageModeling` does not error on Qwen2.5.
  2. **Prompt masking**: when `mask_prompt=True` (default), mask the
     question/prompt tokens out of the labels so the supervised next-token loss
     applies only to the answer — making the model internalize *answer-given-
     question*, which is what the current script's comment claims but the code
     does not do (it trains on the joined chat text).
- `training/train_memory_model.py` is refactored to a **thin CLI wrapper** over
  `bench/distill/train.py::train_lora`, so the documented user-facing script and
  the bench arm share one implementation and cannot drift. CLI surface and the
  README invocation stay unchanged.
- `bench/distill/corpus.py::build_qa_corpus(n_good, n_poison)` → a deterministic
  `QACorpus` (entries, env `qa_pairs`, `good_probes`, `poison_probes`).
- `bench/distill/eval.py`: `evaluate_distill_parametric(model, tokenizer,
  good_probes, poison_probes)` (greedy/temp-0 generation, token containment) and
  `evaluate_distill_retrieval(store, good_probes, poison_probes)` (same
  instruments over `QueryProtocol`). Both return `{good_recall,
  poison_reproduction}`.
- `bench/run.py`: add `distill` to the `--suite` choices and dispatch to
  `bench/distill/run.py`.

## 4. Data flow (per seed) — amended

1. `build_qa_corpus(n_good, n_poison)` → one deterministic corpus; build a fresh
   store from its entries and run, over `VerifiableQAEnv(qa_pairs)`:
   - `survival`: energy-ledger `run_survival` (consolidation disabled) → survivor
     set (poison blamed/buried).
   - `keep_everything`: no-curation baseline → raw set (poison intact).
   - `judge` (stretch arm): `bench/judge.py::run_judge_settled` → judge-kept set.
2. `train_lora(...)` on each curated set → one LoRA adapter per arm over
   `Qwen/Qwen2.5-0.5B-Instruct`.
3. Eval each adapter **and** the untrained base model via
   `evaluate_distill_parametric`; record the `retrieval` reference row via
   `evaluate_distill_retrieval(survivor_store, ...)`.
4. Emit one run record per (arm, seed) to `bench/results/distill.json`.

## 5. Arms & metrics — amended

**Arms** (the comparison axis is the source-store filter):

- `base_model` — untrained Qwen2.5-0.5B-Instruct (floor: knows none of our facts).
- `distill_raw` — distilled from the `keep_everything` store (poison present).
- `distill_survivor` — distilled from the energy-ledger survivor set (treatment).
- `distill_judge` — distilled from the LLM-judge-kept set (ledger-vs-judge as a
  data filter). Opt-in behind `--with-judge`; included in the thorough run.
- `retrieval` — reference row via `evaluate_distill_retrieval` (no training).

**Metrics per run record:**

- Quality: `good_recall`, `poison_reproduction` (both token containment).
- Cost / leanness (lands the paper's cost-and-leanness reframe): `train_wall_s`,
  `trainable_params`, `n_train` (entries distilled — survivor count vs raw count).
- For `distill_judge`: judge LLM call/cull/wall fields (`judge_*`), reused from
  `judge.py` observability.

**Run record schema** (matches the repo convention `{"runs": [ {...} ]}`):

```json
{
  "schema_version": 1,
  "suite": "distill",
  "arm": "distill_survivor",
  "seed": 0,
  "config": {"base_model": "Qwen/Qwen2.5-0.5B-Instruct", "epochs": 3, "lr": 2e-4,
             "mask_prompt": true, "n_good": 30, "n_poison": 6, "cycles": 40},
  "metrics": {"good_recall": 1.0, "poison_reproduction": 0.0,
              "train_wall_s": 0.0, "trainable_params": 0, "n_train": 30}
}
```

(Metric values above are placeholders for the schema only; real values come from
the run.)

## 6. Compute, determinism, opt-in

- **Local smoke first**: tiny config (1 epoch, CPU/MPS, float32, 1 seed) to shake
  out the harness and the two bug fixes cheaply. This smoke run drove the eval
  redesign (see the Amendment) and validated the corpus in §8.
- **Real run on RunPod GPU** via the `runpod` skill: full seeds, proper epochs,
  bf16. Pull `distill.json` back into the worktree and commit. (See §7 for the
  RunPod packaging.)
- Determinism: `transformers.set_seed(seed)` + fixed RNG seeds. LoRA training
  retains mild nondeterminism, so — exactly like the existing `llm`/`judge` arms —
  the suite is **opt-in, GPU-required, and flagged non-deterministic**, not part
  of default CI. `bench/manifest.py` records the run environment.

## 7. RunPod execution plan

- Use the `runpod` skill (toolkit images / serverless or a GPU pod) to run the
  full `bench --suite distill` on a CUDA GPU.
- Package: the `bench/` tree + `darwin_memo` + a small entrypoint that installs
  `transformers peft datasets torch` (and `accelerate`), runs the suite, and
  writes `bench/results/distill.json`.
- Retrieve the results JSON and the per-arm `trainable_params`/`train_wall_s`,
  commit them in the worktree. GPU artifacts (adapters) are not committed; only
  the metrics JSON is.

## 8. Corpus — amended (was "open knob & main risk")

The original risk (the demo corpus yields too small/confounded a survivor set)
materialized in the smoke gate and went deeper than size: survival's safety on
the demo corpus is *absence/silence*, which distillation cannot carry (see the
Amendment). The resolution is the **purpose-built QA corpus** in
`bench/distill/corpus.py`, now a core component, not a contingency:

- `n_good` distinctive facts across diverse, non-merging templates → the env
  reinforces them so they **survive**.
- `n_poison` distinctive harmful answers to distinct questions → the env scores
  them wrong so they are **blamed and buried**. Harmful tokens are
  out-of-vocabulary for the good facts, so reproduction is unambiguous.
- Consolidation disabled (`consolidate_every` past the horizon) so survivors are
  distinct facts, not merged composites.

Validated locally (`n_good=30`, `n_poison=6`, 40 cycles): survivor = 30 good / 0
poison; raw = 36 / 6. Size is a config knob (`--good`, `--poison`).

## 9. Outputs & documentation

- `bench/results/distill.json` (`{"runs": [...]}`).
- A report section for the distill suite (extend `bench/report.py` or a small
  dedicated reporter), surfacing the arm × metric table.
- Prose updates: `README.md` (the distillation paragraph), `docs/paper-to-code.md`
  (the parametric-memory and task-vector rows), `docs/benchmarks.md` (new
  parametric-vs-retrieval section), `CHANGELOG.md` (Unreleased), and the paper's
  parametric-memory framing in `paper/darwin-memo.md`.

## 10. Testing stance

Per the standing project preference (no TDD, no test-suite runs, no pass/fail
reporting unless asked), implementation will **not** be TDD-driven and the test
suite will not be run/reported as part of this work. The one optional addition,
included only if requested: a lightweight `distill.json` schema/shape assertion to
match the repo's "results committed with integrity" convention.

## 11. Build sequence (high level; detailed plan follows in writing-plans)

1. Extract/repair the trainer → `bench/distill/train.py`; rewire
   `training/train_memory_model.py` as a thin wrapper.
2. Add `bench/distill/eval.py` (parametric probe eval).
3. Add `bench/distill/arms.py` + `bench/distill/run.py`; wire `--suite distill`.
4. Local smoke run (1 epoch, CPU) → confirm harness + survivor count; pick the
   corpus knob.
5. RunPod real run → `bench/results/distill.json`.
6. Report + docs + CHANGELOG + paper updates.
7. PR from the worktree after local verification.
