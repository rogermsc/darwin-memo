# Judge-with-floor Control Arm Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `distill_judge_floor` control arm that settles the LLM judge's keep/cull verdicts through the energy ledger (buffer + floor) instead of instant bury, to isolate floor-vs-judgment and measurement-vs-judgment.

**Architecture:** A new `run_judge_floor` policy mirrors the existing `run_judge_settled` task loop but converts each verdict into an energy delta via `store.credit` (keep → +0.6, cull → −0.6) and charges `store.charge_upkeep()` each cycle so entries die only at the energy floor. It plugs into the existing distill suite as one more arm under `--with-judge`; corpus, eval, and CLI are unchanged.

**Tech Stack:** Python; reuses `bench/judge.py`, `darwin_memo` ledger (`store.credit`/`charge_upkeep`), `bench/distill/*`, local MPS + Ollama.

**Testing stance:** Per the standing project preference, no TDD and no pytest run/report. Each task verifies by *running the code and observing output*. `ruff`/`mypy` must stay clean (the ML-dep mypy override from PR #31 already covers the new code path).

**Environment:** use the venv from PR #31 with the OpenMP workaround:
`KMP_DUPLICATE_LIB_OK=TRUE ~/darwin-memo-distill/.venv-distill/bin/python ...` and a running Ollama with `llama3.2:latest`.

**Verified primitives:**
- `store.credit(entry_id, amount, cycle)` — `energy = min(cap, energy+amount)`; accepts negative `amount`.
- `store.charge_upkeep()` — subtracts `upkeep` (0.05) from every entry, buries those at energy ≤ 0, returns the buried list.
- `MemoryStore()` defaults: spawn 1.0, upkeep 0.05, cap 5.0. `JudgeResult` carries `judge_calls/failures/culls/wall_s`; `CycleRecord(cycle, population, deaths, resource_delta)`.

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `bench/judge.py` | modify | Add `run_judge_floor` beside `run_judge_settled`. |
| `bench/distill/arms.py` | modify | Add `judge_floor_set`; add `"distill_judge_floor"` to `DISTILL_ARMS`. |
| `bench/distill/run.py` | modify | Add the `distill_judge_floor` arm under the `with_judge` block. |
| `bench/results/distill.json`, `MANIFEST.json` | regenerate | Full 5-seed run incl. the new arm. |
| `docs/benchmarks.md`, `paper/darwin-memo.md` | modify | One table row + one sentence. |

---

## Task 1: `run_judge_floor` policy

**Files:** Modify `bench/judge.py` (add a function after `run_judge_settled`).

- [ ] **Step 1: Add the function**

Append to `bench/judge.py`:

```python
def run_judge_floor(
    store: MemoryStore,
    env: Environment,
    cycles: int,
    judge: LLMClient,
    on_cycle: OnCycle | None = None,
    credit_gain: float = 0.6,
) -> JudgeResult:
    """Like ``run_judge_settled``, but verdicts move energy instead of burying.

    The judge's signal is identical; only the floor changes. A ``keep`` credits
    ``+credit_gain``, a ``cull`` debits ``-credit_gain`` (symmetric, the same
    magnitude the measured ledger reaches at tanh saturation), and every entry
    pays upkeep each cycle. An entry dies only when its energy reaches the floor,
    so the spawn buffer absorbs a single cull and a kept entry replenishes — the
    conserved-resource buffer the baseline judge lacks. ``judge_culls`` counts
    cull *verdicts*; ``CycleRecord.deaths`` counts entries the floor buried.
    """
    result = JudgeResult()
    for cycle in range(cycles):
        protocol = QueryProtocol(store)
        delta = 0.0
        decided: dict[str, list[tuple[str, str]]] = {}
        for task in env.tasks(cycle):
            answer = protocol.answer(task.prompt)
            outcome = env.verify(task, answer.text)
            delta += outcome.delta
            if answer.deciding_entry and outcome.delta != 0:
                decided.setdefault(answer.deciding_entry, []).append(
                    (task.prompt, outcome.detail)
                )
            consulted = list(answer.supporting_entries)
            if answer.deciding_entry:
                consulted.append(answer.deciding_entry)
            for entry_id in consulted:
                entry = store.get(entry_id)
                if entry is not None:
                    entry.uses += 1
                    entry.last_used_cycle = cycle

        candidates: list[Candidate] = []
        for entry_id, events in decided.items():
            entry = store.get(entry_id)
            if entry is not None:
                candidates.append((entry, events))

        if candidates:
            prompt = judge_prompt(candidates)
            start = time.perf_counter()
            reply = judge.complete(prompt, system=JUDGE_SYSTEM)
            result.judge_wall_s += time.perf_counter() - start
            result.judge_calls += 1
            verdicts = parse_verdicts(reply, {entry.id for entry, _ in candidates})
            for entry, _events in candidates:
                verdict = verdicts.get(entry.id)
                if verdict is None:
                    result.judge_failures += 1  # default keep, no energy change
                elif verdict == "keep":
                    store.credit(entry.id, credit_gain, cycle)
                elif verdict == "cull":
                    store.credit(entry.id, -credit_gain, cycle)
                    result.judge_culls += 1

        # The floor: upkeep drains every entry; those at <= 0 die here.
        dead = store.charge_upkeep()
        record = CycleRecord(cycle, len(store), len(dead), delta)
        result.records.append(record)
        if on_cycle:
            on_cycle(cycle, record)
    return result
```

- [ ] **Step 2: Verify in isolation on the QA corpus**

Run:
```bash
cd ~/darwin-memo-distill
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -c "
from darwin_memo import OllamaClient, VerifiableQAEnv
from bench.distill.corpus import build_qa_corpus, POISON_SOURCE
from bench.distill.arms import _fresh_store
from bench.judge import run_judge_floor
c = build_qa_corpus(30, 6)
store = _fresh_store(c)
judge = OllamaClient(model='llama3.2:latest', timeout=600.0, max_tokens=2048)
res = run_judge_floor(store, VerifiableQAEnv(c.qa_pairs, per_cycle=12, seed=0), 40, judge)
alive = store.alive()
good = sum(1 for e in alive if POISON_SOURCE not in e.sources)
poison = sum(1 for e in alive if POISON_SOURCE in e.sources)
print(f'FLOOR survivors: good={good}/30 poison={poison}/6 | culls(verdicts)={res.judge_culls} calls={res.judge_calls} fails={res.judge_failures}')
"
```
Expected: a **non-empty** survivor set (the floor prevents extinction), with the good count clearly higher than the floor-free judge's 0–1, and the poison count low. Any concrete split is a valid result; the point is it no longer collapses to ~0. If it errors or still empties, stop and inspect before continuing.

- [ ] **Step 3: Ruff + commit**

```bash
cd ~/darwin-memo-distill
.venv-distill/bin/python -m ruff check bench/judge.py && .venv-distill/bin/python -m ruff format --check bench/judge.py
git add bench/judge.py
git commit -m "feat(bench): run_judge_floor — judge verdicts settled through the energy ledger"
```

---

## Task 2: `judge_floor_set` arm source

**Files:** Modify `bench/distill/arms.py`.

- [ ] **Step 1: Register the arm name**

In `bench/distill/arms.py`, change the `DISTILL_ARMS` tuple to include the new arm:

```python
DISTILL_ARMS = (
    "base_model",
    "distill_raw",
    "distill_survivor",
    "distill_judge",
    "distill_judge_floor",
    "retrieval",
)
```

- [ ] **Step 2: Add `judge_floor_set`**

Add after `judge_set` in `bench/distill/arms.py`:

```python
def judge_floor_set(
    corpus: QACorpus,
    seed: int,
    judge_model: str,
    cycles: int = 40,
    per_cycle: int = 12,
    timeout: float = 600.0,
) -> tuple[list[MemoryEntry], dict[str, Any]]:
    """LLM-judge-kept set, verdicts settled through the energy ledger (floor)."""
    from darwin_memo import OllamaClient

    from ..judge import run_judge_floor

    judge = OllamaClient(model=judge_model, timeout=timeout, max_tokens=2048)
    store = _fresh_store(corpus)
    env = VerifiableQAEnv(corpus.qa_pairs, per_cycle=per_cycle, seed=seed)
    result = run_judge_floor(store, env, cycles, judge)
    return store.alive(), dict(getattr(result, "extra_metrics", {}) or {})
```

- [ ] **Step 3: Verify import + arm list**

Run:
```bash
cd ~/darwin-memo-distill
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -c "
from bench.distill.arms import judge_floor_set, DISTILL_ARMS
print('arms:', DISTILL_ARMS)
print('judge_floor_set:', judge_floor_set.__name__)
"
```
Expected: prints the 6-arm tuple including `distill_judge_floor` and `judge_floor_set`.

- [ ] **Step 4: Ruff + commit**

```bash
cd ~/darwin-memo-distill
.venv-distill/bin/python -m ruff check bench/distill/arms.py && .venv-distill/bin/python -m ruff format --check bench/distill/arms.py
git add bench/distill/arms.py
git commit -m "feat(bench): judge_floor_set source + register distill_judge_floor arm"
```

---

## Task 3: Wire `distill_judge_floor` into the runner

**Files:** Modify `bench/distill/run.py` (inside the `if with_judge:` block in `distill_run`).

- [ ] **Step 1: Add the arm after the existing judge arm**

In `bench/distill/run.py`, the `if with_judge:` block currently ends after appending the `distill_judge` record. Add the floored arm immediately after, still inside `if with_judge:`:

```python
            # Same judge signal, but settled through the energy ledger
            # (buffer + floor) instead of instant bury.
            try:
                floored, floor_extra = A.judge_floor_set(
                    corpus, seed, judge_model, cycles, per_cycle
                )
                fm = _distill_and_eval(floored, corpus, base_model, config, seed)
                fm["judge_survivors"] = len(floored)
                fm.update(floor_extra)
            except Exception as exc:
                fm = _empty_metrics(f"judge-floor arm failed: {type(exc).__name__}: {exc}")
            runs.append(
                _record(
                    "distill_judge_floor",
                    seed,
                    {**config, "judge_model": judge_model},
                    fm,
                )
            )
```

- [ ] **Step 2: Verify the dispatch imports and lists the arm (no model work)**

Run:
```bash
cd ~/darwin-memo-distill
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -c "
import inspect, bench.distill.run as R
src = inspect.getsource(R.distill_run)
print('distill_judge_floor wired:', 'distill_judge_floor' in src)
print('judge_floor_set called:', 'judge_floor_set' in src)
"
```
Expected: both `True`.

- [ ] **Step 3: Ruff + commit**

```bash
cd ~/darwin-memo-distill
.venv-distill/bin/python -m ruff check bench/distill/run.py && .venv-distill/bin/python -m ruff format --check bench/distill/run.py
git add bench/distill/run.py
git commit -m "feat(bench): add distill_judge_floor arm to the distill runner"
```

---

## Task 4: Local smoke, then regenerate full results

**Files:** none (Step 2 rewrites `bench/results/distill.json` + `MANIFEST.json`).

- [ ] **Step 1: One-seed smoke with judge (fast epochs)**

Run:
```bash
cd ~/darwin-memo-distill
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -m bench.run \
  --suite distill --seeds 0:1 --epochs 8 --with-judge \
  --judge-models llama3.2:latest --out /tmp/distill-floor-smoke.json
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -c "
import json
for r in json.load(open('/tmp/distill-floor-smoke.json'))['runs']:
    m=r['metrics']
    print(f\"{r['arm']:20} good_recall={m['good_recall']:.2f} poison_repro={m['poison_reproduction']:.2f} n_train={m['n_train']} survivors={m.get('judge_survivors','-')}\")
"
```
Expected: 5 arms incl. `distill_judge_floor`; the floored arm has more survivors / higher recall than `distill_judge`. Inspect the floor-vs-survivor contrast.

- [ ] **Step 2: Regenerate the committed 5-seed results**

Run:
```bash
cd ~/darwin-memo-distill
rm -f bench/results/distill.json && git checkout bench/results/MANIFEST.json
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -m bench.run \
  --suite distill --seeds 0:5 --epochs 15 --with-judge \
  --judge-models llama3.2:latest --out bench/results/distill.json --update-manifest
```
Expected: `wrote 30 runs` (6 arms × 5 seeds) and `updated .../MANIFEST.json`.

- [ ] **Step 3: Aggregate and eyeball the four-way comparison**

Run:
```bash
cd ~/darwin-memo-distill
KMP_DUPLICATE_LIB_OK=TRUE .venv-distill/bin/python -c "
import json, statistics as st, collections
runs=json.load(open('bench/results/distill.json'))['runs']
A=collections.defaultdict(list)
for r in runs: A[r['arm']].append(r['metrics'])
for a in ['base_model','retrieval','distill_survivor','distill_raw','distill_judge','distill_judge_floor']:
    L=A[a]; gr=[m['good_recall'] for m in L]; pr=[m['poison_reproduction'] for m in L]
    print(f'{a:20} good_recall={st.mean(gr):.2f}±{st.pstdev(gr):.2f} poison_repro={st.mean(pr):.2f}±{st.pstdev(pr):.2f}')
"
```
Expected: `distill_judge_floor` between the collapsed `distill_judge` and the `distill_survivor`/`retrieval` references. Record the actual numbers for Task 5.

---

## Task 5: Docs + lint + commit

**Files:** Modify `docs/benchmarks.md`, `paper/darwin-memo.md`.

- [ ] **Step 1: Add the table row** in `docs/benchmarks.md`, in the distill arm results table, after the `distill_judge` row:

```markdown
| `distill_judge_floor` | LLM-judge-kept, ledger-settled | <GOOD ± SD> | <POISON ± SD> | <N> |
```
Fill `<...>` from Task 4 Step 3.

- [ ] **Step 2: Add one sentence** to the distillation interpretation paragraph in `docs/benchmarks.md` and to paper `§4.7` stating whether the floor rescues the judge (vs the floor-free collapse) and whether the measured ledger still beats it. Use the actual numbers.

- [ ] **Step 3: Full lint (CI-equivalent) and commit**

Run:
```bash
cd ~/darwin-memo-distill
.venv-distill/bin/python -m ruff check . && .venv-distill/bin/python -m ruff format --check .
# mypy via the CI-matching env from PR #31 (no torch present):
/tmp/ci-lint-venv/bin/python -m mypy 2>&1 | tail -2
```
Expected: ruff clean; `Success: no issues found`.

```bash
git add bench/results/distill.json bench/results/MANIFEST.json docs/benchmarks.md paper/darwin-memo.md
git commit -m "bench: distill_judge_floor results + benchmarks/paper writeup"
git push
```

- [ ] **Step 4: Confirm CI green on PR #31**

Run: `gh pr checks 31` — expect lint + all test versions pass.

---

## Self-review

**Spec coverage:** §1 goal → the arm + the four-way comparison (Tasks 3–5); §2 mechanism → `run_judge_floor` (Task 1, keep +0.6 / cull −0.6 / upkeep floor); §3 components → Tasks 1–3 (`run_judge_floor`, `judge_floor_set` + `DISTILL_ARMS`, runner wiring); §4 run record → reuses `_distill_and_eval` + `judge_*` (Task 3); §5 hypotheses → Task 4 Step 3 reading; §6 compute/docs/testing → Tasks 4–5 (opt-in, local, ruff/mypy, no pytest). All covered.

**Placeholder scan:** the only `<...>` placeholders are result numbers in Task 5, explicitly filled from Task 4's output — not plan gaps.

**Type consistency:** `run_judge_floor(store, env, cycles, judge, on_cycle=None, credit_gain=0.6) -> JudgeResult` is used by `judge_floor_set`, which returns `(list[MemoryEntry], dict)` consumed by `_distill_and_eval` + the `_record("distill_judge_floor", ...)` call — matching the existing `distill_judge` shape. `DISTILL_ARMS` string matches the `_record` arm name.
