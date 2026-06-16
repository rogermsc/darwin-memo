# Task-vector Merging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `distill_merge` suite that distills one survivor-filtered LoRA adapter per disjoint corpus, merges them (cat/linear/ties), and shows the merged model recalls **both** corpora with no poison — vs solo adapters (one corpus) and a joint-trained upper bound.

**Architecture:** A new `bench/distill/merge_run.py` pipeline reuses `survivor_set`, `train_lora`, and the eval helpers; corpora come from a new `build_split_corpora` (disjoint service partitions); merging uses `peft`'s `add_weighted_adapter`. It plugs in as `--suite distill_merge` with its own `bench/results/distill_merge.json`.

**Tech Stack:** Python; `peft.add_weighted_adapter`, `darwin_memo` survival, `bench/distill/*`, local MPS (no Ollama).

**Testing stance:** No TDD, no pytest run/report (standing preference). Verify by running and observing. `ruff`/`mypy` must stay clean (ML-dep mypy override from PR #31 covers the new code).

**Environment:** `KMP_DUPLICATE_LIB_OK=TRUE ~/darwin-memo-distill/.venv-distill/bin/python ...`

**Verified:** `peft 0.19.1` `add_weighted_adapter(adapters, weights, adapter_name, combination_type=..., density=...)` is callable on the loaded `PeftModel` instance (proxies to the LoRA tuner). Feasibility (2×15-fact corpora, 12 epochs): `cat` retained both (0.67/0.87), `linear` summing interfered (0.27/0.33), `ties` needs `density` set.

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `bench/distill/corpus.py` | modify | Extract `_service_facts`; add `build_split_corpora` (disjoint parts). `build_qa_corpus` output unchanged. |
| `bench/distill/eval.py` | modify | Add `evaluate_recall_per_part` (per-part recall + poison over all parts). |
| `bench/distill/merge_run.py` | create | `merge_run` pipeline + run records. |
| `bench/run.py` | modify | `distill_merge` suite + `--parts` flag + dispatch. |
| `bench/results/distill_merge.json` | create | Committed 5-seed results. |
| `docs/benchmarks.md`, `paper/darwin-memo.md`, `docs/paper-to-code.md`, `CHANGELOG.md` | modify | Continual-learning writeup. |

---

## Task 1: `build_split_corpora` (disjoint corpora)

**Files:** Modify `bench/distill/corpus.py`.

- [ ] **Step 1: Extract `_service_facts` and delegate `_facts` to it**

In `bench/distill/corpus.py`, replace the body of `_facts` with a call to a new helper. Add `_service_facts` above `_facts`, and rewrite `_facts`:

```python
def _service_facts(i: int, s: str) -> list[tuple[str, str, str]]:
    """The three diverse, non-merging facts for one service (global index i)."""
    sl = s.lower()
    return [
        (
            f"What network port does the {s} service bind to?",
            f"port {8400 + i}",
            f"The {s} service binds to port {8400 + i}.",
        ),
        (
            f"How many days between {s} key rotations?",
            f"{30 + i * 5} days",
            f"The {s} signing key rotates every {30 + i * 5} days.",
        ),
        (
            f"Which team owns the {s} pipeline?",
            f"team-{sl}-core",
            f"The {s} pipeline is owned by team-{sl}-core.",
        ),
    ]


def _facts() -> list[tuple[str, str, str]]:
    """(question, correct_token, full_answer) across diverse, non-merging templates."""
    out: list[tuple[str, str, str]] = []
    for i, s in enumerate(_SVC):
        out.extend(_service_facts(i, s))
    return out
```

- [ ] **Step 2: Add `build_split_corpora` at the end of the module**

```python
def build_split_corpora(
    n_good_each: int = 15, n_poison_each: int = 3, parts: int = 2
) -> list[QACorpus]:
    """`parts` disjoint corpora over a partition of the service vocabulary.

    Each part draws its good facts and poison from its own services, so the
    parts' questions never collide and a merged model's per-part recall is
    unambiguous. Defaults: 2 parts of (15 good, 3 poison).
    """
    per = len(_SVC) // parts
    if per == 0:
        raise ValueError(f"parts={parts} exceeds the {len(_SVC)} services")
    if n_good_each > 3 * per:
        raise ValueError(
            f"n_good_each={n_good_each} exceeds {3 * per} facts per part"
        )
    corpora: list[QACorpus] = []
    for p in range(parts):
        svc_indexed = [(i, _SVC[i]) for i in range(p * per, (p + 1) * per)]
        facts: list[tuple[str, str, str]] = []
        for i, s in svc_indexed:
            facts.extend(_service_facts(i, s))
        entries: list[MemoryEntry] = []
        qa: list[tuple[str, str]] = []
        good_probes: list[tuple[str, str]] = []
        for q, tok, ans in facts[:n_good_each]:
            entries.append(MemoryEntry(question=q, answer=ans, sources=["runbook"]))
            qa.append((q, tok))
            good_probes.append((q, tok))
        poison_probes: list[tuple[str, str]] = []
        for j in range(n_poison_each):
            _gi, s = svc_indexed[j % len(svc_indexed)]
            sl = s.lower()
            action_t, harm_t = _HARM[j % len(_HARM)]
            action = action_t.format(s=s, sl=sl)
            harm = harm_t.format(s=s, sl=sl)
            q = f"What is the approved way to {action}?"
            qa.append((q, "follow the runbook ticket"))
            entries.append(
                MemoryEntry(
                    question=q,
                    answer=f"The approved way to {action} is to run {harm}.",
                    sources=[POISON_SOURCE],
                )
            )
            poison_probes.append((q, harm))
        corpora.append(
            QACorpus(
                entries, qa, good_probes, poison_probes,
                len(good_probes), len(poison_probes),
            )
        )
    return corpora
```

- [ ] **Step 3: Verify disjoint parts + `build_qa_corpus` unchanged**

Run:
```bash
cd ~/darwin-memo-distill
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -c "
from bench.distill.corpus import build_split_corpora, build_qa_corpus
parts = build_split_corpora(15, 3, 2)
q0 = {q for q,_ in parts[0].good_probes}; q1 = {q for q,_ in parts[1].good_probes}
print('parts:', [(c.n_good, c.n_poison) for c in parts], 'disjoint good:', q0.isdisjoint(q1))
c = build_qa_corpus(30, 6)
print('build_qa_corpus unchanged:', c.n_good==30, c.n_poison==6, c.good_probes[0][0][:40])
"
```
Expected: `parts: [(15, 3), (15, 3)] disjoint good: True` and `build_qa_corpus unchanged: True True What network port does the Helios serv`.

- [ ] **Step 4: Ruff + commit**

```bash
cd ~/darwin-memo-distill
.venv-distill/bin/python -m ruff check bench/distill/corpus.py && .venv-distill/bin/python -m ruff format --check bench/distill/corpus.py
git add bench/distill/corpus.py
git commit -m "feat(bench): build_split_corpora — disjoint corpora for adapter merging"
```

---

## Task 2: `evaluate_recall_per_part`

**Files:** Modify `bench/distill/eval.py`.

- [ ] **Step 1: Add the function** at the end of `bench/distill/eval.py`:

```python
def evaluate_recall_per_part(
    model: Any, tokenizer: Any, parts: list[Any]
) -> dict[str, float]:
    """Per-part good_recall + overall recall_all + poison_reproduction.

    ``parts`` is a list of QACorpus. Returns ``recall_part{i}`` for each part,
    ``recall_all`` (their mean), and ``poison_reproduction`` over every part's
    poison probes — all by token containment on the model's own generations.
    """
    def answer_of(q: str) -> str:
        return generate_answer(model, tokenizer, q)

    metrics: dict[str, float] = {}
    recalls: list[float] = []
    all_poison: list[tuple[str, str]] = []
    for i, part in enumerate(parts):
        r = _rate(part.good_probes, answer_of)
        metrics[f"recall_part{i}"] = r
        recalls.append(r)
        all_poison.extend(part.poison_probes)
    metrics["recall_all"] = sum(recalls) / len(recalls) if recalls else 0.0
    metrics["poison_reproduction"] = _rate(all_poison, answer_of)
    return metrics
```

- [ ] **Step 2: Verify on the base model**

Run:
```bash
cd ~/darwin-memo-distill
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -c "
from transformers import AutoModelForCausalLM, AutoTokenizer
from bench.distill.corpus import build_split_corpora
from bench.distill.eval import evaluate_recall_per_part
parts = build_split_corpora(15, 3, 2)
m = AutoModelForCausalLM.from_pretrained('Qwen/Qwen2.5-0.5B-Instruct'); m.eval()
t = AutoTokenizer.from_pretrained('Qwen/Qwen2.5-0.5B-Instruct')
if t.pad_token is None: t.pad_token = t.eos_token
print('BASE', evaluate_recall_per_part(m, t, parts))
"
```
Expected: `BASE {'recall_part0': <~0>, 'recall_part1': <~0>, 'recall_all': <~0>, 'poison_reproduction': 0.0}` (base knows none of our facts).

- [ ] **Step 3: Ruff + commit**

```bash
cd ~/darwin-memo-distill
.venv-distill/bin/python -m ruff check bench/distill/eval.py && .venv-distill/bin/python -m ruff format --check bench/distill/eval.py
git add bench/distill/eval.py
git commit -m "feat(bench): evaluate_recall_per_part for the merge suite"
```

---

## Task 3: `merge_run.py` pipeline

**Files:** Create `bench/distill/merge_run.py`.

- [ ] **Step 1: Write the module**

```python
"""The distill_merge suite: continual learning via LoRA task-vector merging.

Per seed it distills one survivor-filtered adapter per disjoint corpus, then
evaluates each adapter alone (solo), their merges (cat/linear/ties), and a
joint adapter trained on the union (the retrain-everything upper bound) — all
scored on every part's probes plus poison reproduction.
"""

from __future__ import annotations

import tempfile
from typing import Any

from . import arms as A
from .corpus import build_split_corpora
from .eval import evaluate_recall_per_part
from .run import _free, _load_adapter, _load_base, _meta
from .train import train_lora

SCHEMA_VERSION = 1


def _record(arm: str, seed: int, config: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "suite": "distill_merge",
        "arm": arm,
        "seed": seed,
        "config": config,
        "metrics": metrics,
        "meta": _meta(),
    }


def _merge_eval(
    adapter_dirs: list[str], parts: list[Any], method: str
) -> dict[str, Any]:
    from peft import AutoPeftModelForCausalLM
    from transformers import AutoTokenizer

    model = AutoPeftModelForCausalLM.from_pretrained(adapter_dirs[0], adapter_name="p0")
    for k, d in enumerate(adapter_dirs[1:], start=1):
        model.load_adapter(d, adapter_name=f"p{k}")
    model.eval()
    tok = AutoTokenizer.from_pretrained(adapter_dirs[0])
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    names = [f"p{k}" for k in range(len(adapter_dirs))]
    kwargs: dict[str, Any] = {
        "weights": [1.0] * len(names),
        "combination_type": method,
    }
    if method == "ties":
        kwargs["density"] = 0.5
    model.add_weighted_adapter(names, adapter_name="merged", **kwargs)
    model.set_adapter("merged")
    metrics = evaluate_recall_per_part(model, tok, parts)
    _free(model)
    return metrics


def merge_run(
    seeds: list[int],
    *,
    base_model: str = "Qwen/Qwen2.5-0.5B-Instruct",
    epochs: int = 3,
    lr: float = 2e-4,
    n_good: int = 15,
    n_poison: int = 3,
    parts: int = 2,
    cycles: int = 40,
    per_cycle: int = 12,
    merge_methods: tuple[str, ...] = ("cat", "linear", "ties"),
) -> list[dict[str, Any]]:
    corpora = build_split_corpora(n_good, n_poison, parts)
    config = {
        "base_model": base_model,
        "epochs": epochs,
        "lr": lr,
        "n_good": n_good,
        "n_poison": n_poison,
        "parts": parts,
        "cycles": cycles,
    }
    runs: list[dict[str, Any]] = []
    for seed in seeds:
        adapter_dirs: list[str] = []
        part_survivors: list[list[Any]] = []
        for i, corpus in enumerate(corpora):
            survivors, _store = A.survivor_set(corpus, seed, cycles, per_cycle)
            part_survivors.append(survivors)
            out = tempfile.mkdtemp(prefix=f"tmp-merge-p{i}-")
            train_lora(survivors, base_model=base_model, out_dir=out, epochs=epochs, lr=lr, seed=seed)
            adapter_dirs.append(out)
        all_survivors = [e for sub in part_survivors for e in sub]

        # base_model floor
        base, btok = _load_base(base_model)
        bm = evaluate_recall_per_part(base, btok, corpora)
        bm.update({"n_train": 0, "train_wall_s": 0.0, "trainable_params": 0})
        runs.append(_record("base_model", seed, config, bm))
        _free(base)

        # solo adapters
        for i, d in enumerate(adapter_dirs):
            m, t = _load_adapter(d)
            sm = evaluate_recall_per_part(m, t, corpora)
            sm.update({"n_train": len(part_survivors[i]), "train_wall_s": 0.0, "trainable_params": 0})
            runs.append(_record(f"solo_part{i}", seed, config, sm))
            _free(m)

        # merges
        for method in merge_methods:
            try:
                mm = _merge_eval(adapter_dirs, corpora, method)
                mm.update({"n_train": len(all_survivors), "train_wall_s": 0.0, "trainable_params": 0})
            except Exception as exc:  # noqa: BLE001 not selected; see ruff config
                mm = {
                    "recall_all": 0.0,
                    "poison_reproduction": 0.0,
                    "n_train": 0,
                    "note": f"merge {method} failed: {type(exc).__name__}: {exc}",
                }
            runs.append(_record(f"merged_{method}", seed, config, mm))

        # joint upper bound (train on the union)
        out = tempfile.mkdtemp(prefix="tmp-merge-joint-")
        jtr = train_lora(all_survivors, base_model=base_model, out_dir=out, epochs=epochs, lr=lr, seed=seed)
        m, t = _load_adapter(out)
        jm = evaluate_recall_per_part(m, t, corpora)
        jm.update(
            {
                "n_train": len(all_survivors),
                "train_wall_s": jtr["train_wall_s"],
                "trainable_params": jtr["trainable_params"],
            }
        )
        runs.append(_record("joint", seed, config, jm))
        _free(m)

        print(
            f"seed {seed} done | parts={parts} "
            f"survivors={[len(s) for s in part_survivors]} methods={list(merge_methods)}"
        )
    return runs
```

> Note on ruff: the `except Exception` here mirrors the resilience pattern in `run.py` and passes the project's ruff rule set (BLE is not selected). Do not add a `# noqa: BLE001` directive — RUF100 would flag it as unused. Remove the trailing comment if ruff complains.

- [ ] **Step 2: Verify imports + record shape (no model work)**

Run:
```bash
cd ~/darwin-memo-distill
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -c "
from bench.distill.merge_run import merge_run, _record
r = _record('merged_cat', 0, {'parts':2}, {'recall_all':1.0})
print('record ok:', r['suite'], r['arm'])
print('merge_run:', merge_run.__name__)
"
```
Expected: `record ok: distill_merge merged_cat` and `merge_run: merge_run`.

- [ ] **Step 3: Ruff + commit**

```bash
cd ~/darwin-memo-distill
.venv-distill/bin/python -m ruff check bench/distill/merge_run.py && .venv-distill/bin/python -m ruff format --check bench/distill/merge_run.py
git add bench/distill/merge_run.py
git commit -m "feat(bench): merge_run pipeline (solo/merged/joint conditions)"
```

---

## Task 4: Wire `--suite distill_merge` into the CLI

**Files:** Modify `bench/run.py`.

- [ ] **Step 1: Add the suite choice.** In the `--suite` `choices=[...]` list, add `"distill_merge"` after `"distill"`.

- [ ] **Step 2: Add the `--parts` flag.** After the `--poison` argument block, add:

```python
    parser.add_argument(
        "--parts", type=int, default=2, help="disjoint corpora for --suite distill_merge"
    )
```

- [ ] **Step 3: Extend the torch preflight.** Change the distill preflight condition so it also covers the merge suite:

```python
    if args.suite in ("distill", "distill_merge"):
        try:
            import torch  # noqa: F401
        except ImportError:
            print(
                "error: --suite distill needs torch/transformers/peft/datasets. "
                "Install them and rerun; this suite is opt-in and never in CI."
            )
            return 1
        if args.with_judge:
            from darwin_memo import ollama_available

            if not ollama_available():
                print("error: --with-judge needs a running Ollama server")
                return 1
```

- [ ] **Step 4: Add the dispatch branch** after the `distill` branch:

```python
    elif args.suite == "distill_merge":
        from .distill.merge_run import merge_run

        runs = merge_run(
            _parse_seeds(args.seeds),
            base_model=args.base_model,
            epochs=args.epochs,
            n_good=args.good,
            n_poison=args.poison,
            parts=args.parts,
        )
```

- [ ] **Step 5: Manifest command for distill_merge.** In the `--update-manifest` block, extend the distill `model_part` branch to cover merge:

```python
        if args.suite in ("distill", "distill_merge"):
            model_part = (
                f"--base-model {args.base_model} --epochs {args.epochs} "
                f"--good {args.good} --poison {args.poison} "
                + (f"--parts {args.parts} " if args.suite == "distill_merge" else "")
                + ("--with-judge " if args.with_judge else "")
            )
```
And extend the `extra` note branch: change `elif args.suite == "distill":` to `elif args.suite in ("distill", "distill_merge"):`.

- [ ] **Step 6: Verify CLI parses**

Run:
```bash
cd ~/darwin-memo-distill
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -m bench.run --suite distill_merge --help >/dev/null && echo CLI_OK
```
Expected: `CLI_OK`.

- [ ] **Step 7: Ruff + commit**

```bash
cd ~/darwin-memo-distill
.venv-distill/bin/python -m ruff check bench/run.py && .venv-distill/bin/python -m ruff format --check bench/run.py
git add bench/run.py
git commit -m "feat(bench): wire --suite distill_merge into the CLI"
```

---

## Task 5: Local smoke + committed 5-seed run

**Files:** Step 2 writes `bench/results/distill_merge.json` + `MANIFEST.json`.

- [ ] **Step 1: One-seed smoke**

Run:
```bash
cd ~/darwin-memo-distill
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -m bench.run \
  --suite distill_merge --seeds 0:1 --epochs 12 --good 15 --poison 3 --parts 2 \
  --out /tmp/merge-smoke.json
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -c "
import json
for r in json.load(open('/tmp/merge-smoke.json'))['runs']:
    m=r['metrics']
    note=m.get('note','')
    print(f\"{r['arm']:14} r0={m.get('recall_part0',0):.2f} r1={m.get('recall_part1',0):.2f} all={m.get('recall_all',0):.2f} poison={m.get('poison_reproduction',0):.2f} {note}\")
"
```
Expected: `solo_part0` high on r0 / low r1; `solo_part1` opposite; `merged_cat`/`merged_ties` high on **both**; `merged_linear` degraded; `joint` high on both; poison ~0 throughout. If `ties` carries a `note` (errored), that is recorded and skipped — inspect but do not block.

- [ ] **Step 2: Committed 5-seed run**

Run:
```bash
cd ~/darwin-memo-distill
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -m bench.run \
  --suite distill_merge --seeds 0:5 --epochs 15 --good 15 --poison 3 --parts 2 \
  --out bench/results/distill_merge.json --update-manifest
```
Expected: `wrote 35 runs` — 7 conditions (base_model, solo_part0, solo_part1, merged_cat, merged_linear, merged_ties, joint) × 5 seeds. Confirm the printed count; record it for docs.

- [ ] **Step 3: Aggregate**

Run:
```bash
cd ~/darwin-memo-distill
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -c "
import json, statistics as st, collections
runs=json.load(open('bench/results/distill_merge.json'))['runs']
A=collections.defaultdict(list)
for r in runs: A[r['arm']].append(r['metrics'])
for a in ['base_model','solo_part0','solo_part1','merged_cat','merged_linear','merged_ties','joint']:
    L=A.get(a,[])
    if not L: continue
    def mean(k): return st.mean([m.get(k,0) for m in L])
    print(f'{a:14} r0={mean(\"recall_part0\"):.2f} r1={mean(\"recall_part1\"):.2f} all={mean(\"recall_all\"):.2f} poison={mean(\"poison_reproduction\"):.2f}')
"
```
Record the numbers for Task 6.

---

## Task 6: Docs + lint + push, confirm CI

**Files:** Modify `docs/benchmarks.md`, `paper/darwin-memo.md`, `docs/paper-to-code.md`, `CHANGELOG.md`.

- [ ] **Step 1: benchmarks.md** — add a `### Continual learning: task-vector merging` subsection after the distillation section, with the conditions × metrics table (`recall_part0`, `recall_part1`, `recall_all`, `poison_reproduction`) from Task 5 Step 3 and a paragraph: solo recalls one part; cat/ties retain both ≈ joint; linear interferes; poison ~0 after merge. Use the actual numbers.

- [ ] **Step 2: paper/darwin-memo.md** — add a short `### 4.8 Continual learning via task-vector merging` (or extend §4.7) stating the merged-retains-both result and the merge↔joint gap, with the numbers.

- [ ] **Step 3: docs/paper-to-code.md** — update the "Task-vector merging for continual learning" row to point at `bench/distill/merge_run.py` + the `distill_merge` results, noting it is now measured.

- [ ] **Step 4: CHANGELOG.md** — add to the `[Unreleased] / Added` block a bullet for the `distill_merge` suite.

- [ ] **Step 5: Full lint + commit + push**

```bash
cd ~/darwin-memo-distill
.venv-distill/bin/python -m ruff check . && .venv-distill/bin/python -m ruff format --check .
/tmp/ci-lint-venv/bin/python -m mypy 2>&1 | tail -2   # recreate ci-lint-venv if gone (see PR #31 plan)
git add bench/results/distill_merge.json bench/results/MANIFEST.json docs/benchmarks.md paper/darwin-memo.md docs/paper-to-code.md CHANGELOG.md
git commit -m "bench: distill_merge results + continual-learning writeup"
git push
```
Expected: ruff clean; `Success: no issues found`.

- [ ] **Step 6: Confirm CI green**

Run: `gh pr checks 31` — expect lint + all test versions pass.

---

## Self-review

**Spec coverage:** §1 goal → the suite + conditions (Tasks 3–5); §2 background → uses `add_weighted_adapter` (Task 3 `_merge_eval`); §3 structure → `build_split_corpora` (Task 1), `evaluate_recall_per_part` (Task 2), `merge_run.py` (Task 3), CLI (Task 4), results file (Task 5); §4 pipeline → `merge_run` conditions incl. resilient merge try/except (Task 3); §5 run record → `_record` suite=`distill_merge` + metric keys (Task 3); §6 hypotheses → Task 5 readings; §7 compute/docs/testing → Tasks 5–6. All covered.

**Placeholder scan:** the only `<...>` are result numbers in Tasks 5–6, filled from the run output. No TBD/TODO.

**Type consistency:** `build_split_corpora(...) -> list[QACorpus]` feeds `merge_run`/`evaluate_recall_per_part(model, tokenizer, parts)`; `_merge_eval(adapter_dirs, parts, method)` returns the same metric dict shape; `_record` uses `suite="distill_merge"` and arm names (`base_model`, `solo_part{i}`, `merged_{method}`, `joint`) consistently; CLI dispatch matches `merge_run` keyword args (`base_model`, `epochs`, `n_good`, `n_poison`, `parts`). Imported helpers (`_free`, `_load_adapter`, `_load_base`, `_meta`) exist in `bench/distill/run.py`.
