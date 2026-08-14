# Flaky Trajectory Selection — Stage 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run the cheap Stage 1 "selection-quality" gate: do darwin-memo's energy-buffer selection rules retain a cleaner SFT training set than single-run / majority-vote / any-pass under two-sided verification noise?

**Architecture:** A pure analysis pipeline (selection rules → two-sided noise model → precision/recall/F1 metrics → sweep+report) built and verified on SYNTHETIC labeled candidate pools with zero Docker/API spend. One task then generates a REAL labeled pool (K candidates/task, one true eval each) by reusing the existing `bench/swebench_cl` harness. The sweep runs over the real pool; a real-flaky cell validates it; the gate is evaluated and written up.

**Tech Stack:** Python 3.12 (`.venv312`, has `swebench`/`darwin_memo`) for the real-pool task; stdlib-only `python3.14` for the pure pipeline. darwin-memo's own energy ledger (`darwin_memo.assign_credit` / `MemoryStore`) for the `survival` rule. OpenAI gpt-4.1 for candidate generation; existing Docker executor for true labels.

## Global Constraints

- New analysis code is stdlib-only; `survival` MUST reuse the library's real credit rule (`darwin_memo.assign_credit` over a one-entry `MemoryStore`), not a reimplementation.
- NO reward model, NO LLM judge, NO human labels anywhere in the selection loop — only test pass/fail.
- NO pytest/TDD (project preference); verify every task by RUNNING it (synthetic pools for the pure pipeline; the real harness for the pool task) and inspecting output.
- The core noise model is TWO-SIDED: false-negative rate `p_fn` (true-pass run reports fail) and false-positive rate `p_fp` (true-fail run reports pass). A `p_fp=0` cell is the trivially-solved one-sided control.
- Selection rules are compared at a FIXED per-candidate run count N (and reported across N); metrics are computed against TRUE labels only.
- Commit after each task. Branch `feat/arxiv-paper`, do not push. API key from `~/darwin-memo-paper/.swebench-key` (`--api-key-env SWEBENCH_API_KEY`), model `gpt-4.1`, base-url `https://api.openai.com/v1`.
- Stage 2 (SFT) is OUT OF SCOPE for this plan — gated on the Stage 1 result.

---

## File Structure

- `bench/flaky_select/__init__.py` — new package.
- `bench/flaky_select/rules.py` — the four selection rules over an N-run pass/fail sequence.
- `bench/flaky_select/noise.py` — two-sided noise injector + synthetic-pool generator.
- `bench/flaky_select/metrics.py` — precision/recall/F1 of a rule's retained set vs true labels.
- `bench/flaky_select/sweep.py` — sweep driver (rules × noise grid × N × seeds → metrics) + markdown report; `__main__` CLI.
- `bench/flaky_select/candidates.py` — real candidate-pool generation (K candidates/task + one true label each) reusing the swebench_cl harness.
- `bench/results/flaky_select/` — committed result JSONs + manifest.

---

### Task 1: The four selection rules

**Files:**
- Create: `bench/flaky_select/__init__.py` (empty), `bench/flaky_select/rules.py`

**Interfaces:**
- Produces: `keep(reported: list[bool], rule: str, *, credit_gain: float = 0.6, spawn: float = 1.0, scale: float = 1.0) -> bool` and `RULES = ("single_run", "any_pass", "majority_vote", "survival")`. `reported` is the per-run reported pass(True)/fail(False) sequence for one candidate; returns whether to KEEP it for SFT.

- [ ] **Step 1: Implement `rules.py`.** `single_run` reads `reported[0]`; `any_pass` is `any`; `majority_vote` keeps iff passes ≥ ceil(N/2); `survival` runs the library's credit rule over a one-entry store and keeps iff the entry is still alive:

```python
from __future__ import annotations
import math
from darwin_memo import MemoryEntry, MemoryStore, SurvivalConfig, assign_credit

RULES = ("single_run", "any_pass", "majority_vote", "survival")

def keep(reported: list[bool], rule: str, *, credit_gain: float = 0.6,
         spawn: float = 1.0, scale: float = 1.0) -> bool:
    if not reported:
        return False
    if rule == "single_run":
        return bool(reported[0])
    if rule == "any_pass":
        return any(reported)
    if rule == "majority_vote":
        return sum(reported) >= math.ceil(len(reported) / 2)
    if rule == "survival":
        store = MemoryStore()
        entry = store.add(MemoryEntry(question="c", answer="c", energy=spawn))
        cfg = SurvivalConfig(credit_gain=credit_gain)
        for i, passed in enumerate(reported):
            delta = 1.0 if passed else -1.0
            assign_credit(store, entry.id, [], delta, scale, cfg, i)
        got = store.get(entry.id)
        return got is not None and got.alive
    raise ValueError(f"unknown rule {rule!r}")
```

- [ ] **Step 2: Verify by running** (stdlib interpreter; the import needs `darwin_memo`, so use the venv):

Run:
```bash
PYTHONPATH=. /Users/rogersimoes/darwin-memo-paper/.venv312/bin/python -c "
from bench.flaky_select.rules import keep, RULES
# truly-good with 2 flaky fails out of 7; truly-bad with 1 flaky pass out of 7
good=[True,True,False,True,True,False,True]; bad=[False,False,True,False,False,False,False]
for r in RULES:
    print(r, 'good->', keep(good,r), 'bad->', keep(bad,r))
"
```
Expected: every rule keeps `good` and drops `bad` in this easy case; `survival` keeps `good` (buffer absorbs 2 fails) and drops `bad`. (The hard separation is what the sweep measures.)

- [ ] **Step 3: Commit** `git add bench/flaky_select/__init__.py bench/flaky_select/rules.py && git commit -m "flaky-select: four trajectory-selection rules (survival reuses energy ledger)"`

---

### Task 2: Two-sided noise model + synthetic pool + metrics

**Files:**
- Create: `bench/flaky_select/noise.py`, `bench/flaky_select/metrics.py`

**Interfaces:**
- Produces (noise.py): `report_runs(true_label: bool, n: int, p_fn: float, p_fp: float, rng: random.Random) -> list[bool]`; `synthetic_pool(n_candidates: int, true_pos_frac: float, rng: random.Random) -> list[bool]` (returns true labels).
- Produces (metrics.py): `selection_scores(true_labels: list[bool], kept: list[bool]) -> dict` with keys `precision`, `recall`, `f1`, `kept_n`, `true_pos_yield`.

- [ ] **Step 1: Implement `noise.py`.**

```python
from __future__ import annotations
import random

def report_runs(true_label: bool, n: int, p_fn: float, p_fp: float,
                rng: random.Random) -> list[bool]:
    """N reported pass/fail runs under two-sided noise.
    true-pass run flips to fail w.p. p_fn; true-fail run flips to pass w.p. p_fp."""
    out = []
    for _ in range(n):
        if true_label:
            out.append(not (rng.random() < p_fn))
        else:
            out.append(rng.random() < p_fp)
    return out

def synthetic_pool(n_candidates: int, true_pos_frac: float,
                   rng: random.Random) -> list[bool]:
    return [rng.random() < true_pos_frac for _ in range(n_candidates)]
```

- [ ] **Step 2: Implement `metrics.py`.**

```python
from __future__ import annotations

def selection_scores(true_labels: list[bool], kept: list[bool]) -> dict:
    """Quality of the retained SFT set: precision/recall/F1 of kept-vs-true."""
    tp = sum(1 for t, k in zip(true_labels, kept) if k and t)
    kept_n = sum(kept)
    pos_n = sum(true_labels)
    precision = tp / kept_n if kept_n else 0.0
    recall = tp / pos_n if pos_n else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {"precision": round(precision, 4), "recall": round(recall, 4),
            "f1": round(f1, 4), "kept_n": kept_n, "true_pos_yield": tp}
```

- [ ] **Step 3: Verify by running** (no deps beyond stdlib):

Run:
```bash
PYTHONPATH=. /opt/homebrew/bin/python3.14 -c "
import random
from bench.flaky_select.noise import report_runs, synthetic_pool
r=random.Random(0)
labels=synthetic_pool(1000,0.5,r)
# at p_fn=0.3,p_fp=0.1,n=5 a true-pos should usually still show >=1 pass
seq=report_runs(True,5,0.3,0.1,r); print('true-pos seq', seq)
from bench.flaky_select.metrics import selection_scores
print(selection_scores([True,True,False],[True,False,False]))  # p=1.0 r=0.5 f1~0.667
"
```
Expected: a plausible reported sequence; metrics dict `precision=1.0, recall=0.5, f1≈0.6667, kept_n=1, true_pos_yield=1`.

- [ ] **Step 4: Commit** `git add bench/flaky_select/noise.py bench/flaky_select/metrics.py && git commit -m "flaky-select: two-sided noise model + selection-quality metrics"`

---

### Task 3: Sweep driver + report (verified on synthetic pools, no Docker/API)

**Files:**
- Create: `bench/flaky_select/sweep.py`

**Interfaces:**
- Consumes: `rules.keep`, `noise.report_runs/synthetic_pool`, `metrics.selection_scores`.
- Produces: `run_sweep(true_labels, *, grid, n, seeds, ...) -> list[dict]` (one row per rule×cell×seed, mean over seeds) and a `__main__` that runs a synthetic sweep and prints a markdown table; `--pool <json>` loads real true-labels instead of synthetic.

- [ ] **Step 1: Implement `sweep.py`.** For each (rule, p_fn, p_fp, seed): draw reported runs per candidate via `report_runs`, apply `keep`, score with `selection_scores`; average over seeds; emit rows. Grid default: `p_fn ∈ {0,0.1,0.2,0.35}`, `p_fp ∈ {0,0.1,0.2}` (the `p_fp=0` column is the one-sided control), `n=5`, seeds `0..9`. CLI: `python -m bench.flaky_select.sweep [--pool path] [--n N] [--seeds a:b] [--out path]`; prints a markdown table of F1 (and precision/recall) per rule × (p_fn,p_fp), and writes rows to `--out`. Load real labels from `--pool` JSON (`[{"true_label": bool}, ...]`) when given; else synthetic (1000 candidates, true_pos_frac 0.5). [Implementer: write the full driver; keep it stdlib, deterministic per seed.]

- [ ] **Step 2: Verify by running** the synthetic sweep:

Run:
```bash
PYTHONPATH=. /opt/homebrew/bin/python3.14 -m bench.flaky_select.sweep --n 5 --seeds 0:10 --out /private/tmp/claude-502/-Users-rogersimoes/0e579aa2-1680-4396-8ac7-130d8307b056/scratchpad/flaky_sweep_synth.json
```
Expected: a markdown table; sanity checks to confirm in the output — at `p_fp=0` (one-sided control) `any_pass` has recall≈1.0 and high F1; as `p_fp` rises, `any_pass` precision collapses while `survival`/`majority_vote` hold up; `single_run` is worst overall. This is the synthetic existence-check that the pipeline discriminates the rules.

- [ ] **Step 3: Commit** `git add bench/flaky_select/sweep.py && git commit -m "flaky-select: sweep driver + markdown report (synthetic-verified)"`

---

### Task 4: Real candidate pool with true labels (Docker + API)

**Files:**
- Create: `bench/flaky_select/candidates.py`

**Interfaces:**
- Consumes: existing `bench/swebench_cl` harness (`sequence_tasks`, the agent/edit path, `DockerExecutor`).
- Produces: a pool JSON `[{"instance_id","candidate_idx","patch","true_label","clean_runs":[bool,...],"intrinsically_flaky":bool}, ...]` written under `bench/results/flaky_select/pool-<sequence>.json`.

- [ ] **Step 1: Implement `candidates.py`.** For each task in the pinned sequence: sample K candidates by calling the existing agent path at temperature > 0 (e.g. 0.8 — pass through a temperature arg to `EndpointConfig`); for each candidate, evaluate its patch with `DockerExecutor` R times (e.g. R=5) on the CLEAN suite; `true_label` = majority of the R clean runs; `intrinsically_flaky` = R runs not unanimous. Persist the pool JSON. [Implementer: reuse `build_prompt`/`edits_to_patch`/retrieval and `DockerExecutor.evaluate`; do NOT inject noise here — this establishes ground truth only.]

- [ ] **Step 2: Verify by running** a TINY real slice (1 task, K=2, R=3) to confirm the pool format and that true labels + flaky flags are produced (uses Docker + a few gpt-4.1 calls, ~$):

Run:
```bash
set -a; source .swebench-key; set +a
PYTHONPATH=. .venv312/bin/python -m bench.flaky_select.candidates --sequence pytest-dev_pytest_sequence --max-tasks 1 --k 2 --clean-runs 3 --base-url https://api.openai.com/v1 --model gpt-4.1 --api-key-env SWEBENCH_API_KEY --out /private/tmp/.../scratchpad/pool_smoke.json
```
Expected: a pool JSON with 2 candidate records, each with a `true_label` and `clean_runs` of length 3. (Prune Docker containers first if the daemon 500s; the executor retry handles transient ones.)

- [ ] **Step 3: Commit** `git add bench/flaky_select/candidates.py && git commit -m "flaky-select: real candidate-pool generation with many-run true labels"`

---

### Task 5: Run the real sweep + real-flaky cell, evaluate the gate, write up

**Files:**
- Create: `bench/results/flaky_select/` outputs; Modify: `docs/superpowers/specs/2026-06-30-flaky-trajectory-selection-design.md` (record the Stage-1 result) or a new `docs/benchmarks` subsection.

**Interfaces:** Consumes Tasks 1–4. (Controller-run: real Docker/API; surface cost before the full pool.)

- [ ] **Step 1: Generate the full real pool** over the pinned tasks (controller decides K/R and confirms spend): `candidates.py` over pytest (and astropy) at temperature 0.8, K candidates/task, R clean runs/candidate → `bench/results/flaky_select/pool-pytest.json`.

- [ ] **Step 2: Controlled sweep on the real pool:** `python -m bench.flaky_select.sweep --pool bench/results/flaky_select/pool-pytest.json --n 5 --seeds 0:10 --out bench/results/flaky_select/sweep-pytest.json`. The noise is injected on the real true-labels (cheap, no Docker).

- [ ] **Step 3: Real-flaky cell:** for the `intrinsically_flaky` candidates, run the tests N times FOR REAL (Docker) to get genuine reported sequences, feed through `rules.keep`, and score against their true labels — the no-injection validation that the effect survives real flakiness.

- [ ] **Step 4: Evaluate the GATE (pre-committed):** survival dominates the precision/recall frontier over `single_run` AND `majority_vote` across the two-sided grid, and matches `any_pass` on the `p_fp=0` control. Decide PASS/NO-GO.

- [ ] **Step 5: Write up + commit:** record the Stage-1 result (PASS or honest null) with the F1/precision/recall tables in a `docs/benchmarks.md` "flaky trajectory selection" subsection; bind result JSONs to a manifest; commit. If PASS, the next step is the Stage 2 plan (separate); if NO-GO, report and stop.

---

## Self-Review

**Spec coverage:**
- Four selection rules incl. survival via the library ledger → Task 1. ✓
- Two-sided noise (p_fn/p_fp) + one-sided control → Task 2 (model), Task 3 (grid). ✓
- Precision/recall/F1 of retained set → Task 2 (metrics), Task 3 (sweep). ✓
- Controlled sweep + real-flaky validation cell → Task 3 (synthetic-verified driver), Task 5 steps 2–3. ✓
- Real candidate pool with many-run true labels + intrinsic-flaky tracking → Task 4. ✓
- Gate criterion (frontier dominance, match any-pass on control) → Task 5 step 4. ✓
- Cheap/no-GPU, no judge/RM, reuse harness → Global Constraints + Task 4 reuse. ✓
- Stage 2 explicitly out of scope → header + Global Constraints. ✓

**Placeholder scan:** Tasks 1–2 carry complete code; Tasks 3–5 give exact interfaces, CLIs, and verify commands with `[Implementer: ...]` notes only where the driver is mechanical glue over already-specified functions (not vague requirements). Real paths used throughout; the `/private/tmp/.../scratchpad/` ellipsis in Task 4 Step 2 is the session scratchpad dir, expanded at run time.

**Type consistency:** `keep(reported, rule, ...)` (Task 1) consumed by Task 3 sweep; `report_runs`/`synthetic_pool` (Task 2) consumed by Task 3; `selection_scores(true_labels, kept)` (Task 2) consumed by Task 3; pool JSON schema (Task 4) consumed by `sweep --pool` (Task 3 Step 1) and Task 5. Consistent.

**Cost gate:** Task 4 verifies on a tiny slice first; Task 5 Step 1 is controller-run with explicit spend confirmation before the full pool.
