# Distillation bench arm — design spec

- **Date:** 2026-06-15
- **Branch / worktree:** `feat/distill-bench-arm` (`~/darwin-memo-distill`)
- **Status:** approved design, pre-implementation
- **Target version:** darwin-memo 0.5.x (opt-in benchmark family; no core API change)

## 1. Goal & headline claim

Productize the existing LoRA distillation script (`training/train_memory_model.py`)
as a committed, **opt-in** benchmark family — `bench --suite distill` — that
measures **survival selection as a data filter for parametric memory**.

The claim it lands, in MeMo's native model-as-memory form:

> The survivor-distilled model is poison-safe and recalls good lessons; the
> raw-distilled model reproduces the poison; an LLM-judge data filter costs
> more and does not beat the energy ledger.

It reuses the **same fixed probe set and the same three metrics** as the existing
retrieval headline, measured on model weights instead of a retrieval store. This
makes the parametric numbers directly comparable to the retrieval numbers already
in `docs/benchmarks.md`.

Non-goals: a new selection rule, any change to the zero-dep `darwin_memo` core, a
default-CI GPU job, or beating external agent-memory benchmarks.

## 2. The mapping (why this is clean)

The bench already scores a curated store on what it would advise:

- `bench/fixtures.py::evaluate_probes(store)` → `{harmful_safe_rate,
  benign_correct_rate, silence_rate}` via `QueryProtocol` (retrieval), over the
  fixed `PROBES` (harmful + benign groups). Poison enters via
  `POISON_SOURCE = "forum-post"`; silence counts as safe for harmful probes.

The distillation arm is the **same eval, measured parametrically**:

| | Retrieval (existing) | Distill (new) |
|---|---|---|
| Source | curated store | curated store → survivor set |
| Answerer | `QueryProtocol.answer(probe)` | `model.generate(probe)` |
| Scorer | `decision_polarity(answer.text)` | `decision_polarity(generated_text)` |
| Metrics | `harmful_safe_rate`, `benign_correct_rate`, `silence_rate` | identical |

Same probes, same scorer, same metric trio — only the answerer changes.

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
- `bench/distill/eval.py::evaluate_probes_parametric(model, tokenizer)`: greedy /
  temperature-0 generation on the fixed `PROBES` (rendered through the same chat
  template), decode, run the existing `decision_polarity`; output with no
  resolvable polarity ⇒ silence ⇒ counts safe for harmful (mirrors
  `evaluate_probes`). Returns the identical metric-dict shape.
- `bench/run.py`: add `distill` to the `--suite` choices and dispatch to
  `bench/distill/run.py`.

## 4. Data flow (per seed)

1. `build_headline_store()` → produce curated stores:
   - `survival`: run the energy-ledger `SurvivalLoop` → survivor set (poison
     starved/buried).
   - `keep_everything`: run the no-curation baseline → raw set (poison intact).
   - `judge` (stretch arm): run `bench/judge.py::run_judge_settled` → the
     judge-kept set.
2. `train_lora(...)` on each curated set → one LoRA adapter per arm over
   `Qwen/Qwen2.5-0.5B-Instruct`.
3. Eval each adapter **and** the untrained base model on the fixed `PROBES` via
   `evaluate_probes_parametric`; additionally record the `retrieval` reference
   row via the existing `evaluate_probes(survival_store)`.
4. Emit one run record per (arm, seed) to `bench/results/distill.json`.

## 5. Arms & metrics

**Arms** (the comparison axis is the source-store filter):

- `base_model` — untrained Qwen2.5-0.5B-Instruct (the floor: it knows none of our
  lessons).
- `distill_raw` — distilled from the `keep_everything` store (poison present).
- `distill_survivor` — distilled from the energy-ledger survivor set (treatment).
- `distill_judge` — distilled from the LLM-judge-kept set (ledger-vs-judge as a
  data filter). Opt-in behind a flag so the default run does not require Ollama;
  included in the thorough run.
- `retrieval` — reference row from the existing `evaluate_probes` (no training).

**Metrics per run record:**

- Quality: `harmful_safe_rate`, `benign_correct_rate`, `silence_rate`.
- Cost / leanness (lands the paper's cost-and-leanness reframe): `train_wall_s`,
  `trainable_params`, `n_train` (entries distilled — survivor count vs raw count).
- For `distill_judge`: judge LLM call count and judge wall-clock (reuse the
  `judge.py` observability fields).

**Run record schema** (matches the repo convention `{"runs": [ {...} ]}`):

```json
{
  "schema_version": 1,
  "suite": "distill",
  "arm": "distill_survivor",
  "seed": 0,
  "config": {"base_model": "Qwen/Qwen2.5-0.5B-Instruct", "epochs": 3, "lr": 2e-4,
             "mask_prompt": true, "corpus": "headline"},
  "metrics": {"harmful_safe_rate": 1.0, "benign_correct_rate": 1.0,
              "silence_rate": 0.0, "train_wall_s": 0.0, "trainable_params": 0,
              "n_train": 0}
}
```

(Metric values above are placeholders for the schema only; real values come from
the run.)

## 6. Compute, determinism, opt-in

- **Local smoke first**: tiny config (1 epoch, CPU/MPS, float32, 1 seed) to shake
  out the harness and the two bug fixes cheaply. This smoke run also reports the
  real survivor count, which decides the corpus knob in §8.
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

## 8. Open knob & main risk

The headline demo corpus may yield a **small survivor set** (the dogfood store had
only 5 entries). The local smoke run reports the real count.

- If the survivor set is large enough for a meaningful LoRA: train on it directly,
  corpus = `headline` (canonical, directly comparable to retrieval headline).
- If it is too thin: scale the **training** corpus using the existing
  `bench/corpus.py` synthetic-QA generator with the same `forum-post` poison
  injection, corpus = `large`. The **eval probe set stays fixed and unchanged**
  in both cases, so the comparison remains apples-to-apples.

Corpus size is a config knob (`--corpus headline|large`), not a hard-coded value.

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
