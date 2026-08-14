# Mechanism Depth (Phase 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make removal by disuse legible — one shared definition of how long an entry has left, and an exact upkeep figure instead of an estimate — and merge the organic-memory layer behind a defended invariant.

**Architecture:** Two independent tracks that share no files. Track A extends Phase 1's reporting surface on `feat/mechanism-depth` (branched from the unmerged `feat/operator-surface`). Track B adds the missing invariant tests to the existing organic-memory branches, which target `main` separately.

**Tech Stack:** Python 3.10+ stdlib only. No new dependencies.

## Global Constraints

- **Python floor 3.10** (`requires-python = ">=3.10"`). No `match`, no PEP 695 generics.
- **Zero new Python runtime dependencies.** `dependencies = []` stays empty.
- **mypy strict** over `darwin_memo` and `tests`. Complete annotations; `tests` may use untyped defs.
- **ruff** line-length 88, `select = ["E", "F", "W", "I", "UP", "B", "SIM", "RUF"]`.
- **Coverage gate `fail_under = 80`** over `darwin_memo`. Baseline entering this phase: **428 passed, 3 skipped, 91.52%**.
- **No new selection knob.** Upkeep already *is* the disuse policy. Nothing in this phase may change selection mechanics, credit assignment, or death conditions.
- **Backwards compatible with existing stores and logs.** Event logs written before this release lack the new field; every reader must still work and must not silently report a wrong number.
- **Tooling:** nothing installed locally. `uvx ruff check <paths>`, `uvx ruff format <paths>`, `uvx --python 3.13 --with-editable . --with pytest --with hypothesis pytest`, `... mypy`. `uvx ruff` is UNPINNED and newer than this repo's baseline — scope it to files you touched and revert stray reformatting.
- **Acceptance gate inherited from Phase 1, re-check at the end of every task:** `darwin-memo doctor` must report clean/exit 0 on `/private/tmp/claude-502/-Users-rogersimoes/3f010888-d0a2-415e-92c6-76385e7d3aa1/scratchpad/demo.json` and `starvation_cliff`/exit 1 on `.../scratchpad/dead.json`. **Never mutate either store** — copy them if a task needs to write.
- **Every test must state the mutation that makes it fail, and the implementer must run that mutation.** Phase 1 shipped three tests that passed against both correct and broken implementations; this is the rule that prevents a fourth.

---

## File Structure

| File | Responsibility |
|---|---|
| `darwin_memo/store.py` (modify) | `ticks_to_starvation()` helper; `charge_upkeep` records what it deducted. |
| `darwin_memo/ledger.py` (modify) | `tick()` logs the recorded upkeep in the event it already writes. |
| `darwin_memo/observe.py` (modify) | `top_row` and `entry_life` carry the field; `economics()` prefers the logged figure. |
| `darwin_memo/ui.py` (modify) | Drops its inline arithmetic, calls the helper. |
| `tests/test_store.py`, `tests/test_observe.py`, `tests/test_ledger.py` (modify) | Regression tests per task. |
| `tests/test_organic_invariant.py` (new, Track B) | The structural and behavioural invariant tests. |

---

## Task 1: `ticks_to_starvation` as one definition

**Files:**
- Modify: `darwin_memo/store.py` (add the helper)
- Modify: `darwin_memo/observe.py` (`top_row`, `entry_life`)
- Modify: `darwin_memo/ui.py` (`state()` drops its inline arithmetic)
- Test: `tests/test_store.py`, `tests/test_observe.py`

**Interfaces:**
- Consumes: `MemoryStore.upkeep`, `MemoryEntry.energy`, `MemoryEntry.pinned`.
- Produces: `MemoryStore.ticks_to_starvation(entry: MemoryEntry) -> float | None`, returning `None` when the entry cannot starve.

- [ ] **Step 1: Write the failing tests**

```python
def test_ticks_to_starvation_is_energy_over_upkeep(store_factory):
    store = store_factory(upkeep=0.05)
    entry = store.alive()[0]
    entry.energy = 1.0
    assert store.ticks_to_starvation(entry) == pytest.approx(20.0), (
        "spawn 1.0 at upkeep 0.05 is the documented 20-tick cliff"
    )


def test_pinned_and_free_entries_never_starve(store_factory):
    """None means 'cannot starve', which is not the same as 0 ticks left."""
    store = store_factory(upkeep=0.05)
    entry = store.alive()[0]
    entry.pinned = True
    assert store.ticks_to_starvation(entry) is None, (
        "a pinned balance floors at zero instead of dying"
    )
    entry.pinned = False
    free = store_factory(upkeep=0.0)
    assert free.ticks_to_starvation(free.alive()[0]) is None, (
        "no upkeep means no starvation, and never a ZeroDivisionError"
    )
```

Read the real `MemoryEntry` and `MemoryStore` before running; if `pinned` is not a settable attribute or `store_factory` does not accept `upkeep`, adapt the test to the real API rather than changing the API.

- [ ] **Step 2: Run to verify they fail**

Run: `uvx --python 3.13 --with-editable . --with pytest --with hypothesis pytest tests/test_store.py -k starvation -v`
Expected: FAIL — `MemoryStore` has no attribute `ticks_to_starvation`.

- [ ] **Step 3: Implement the helper**

Add to `darwin_memo/store.py`, near `charge_upkeep` so the two read together:

```python
    def ticks_to_starvation(self, entry: MemoryEntry) -> float | None:
        """Ticks of upkeep this entry can still pay, or None if it cannot starve.

        The operator's actual question, and the number that makes the
        spawn/upkeep cliff visible before it bites. ``None`` is not zero:
        a pinned entry floors at zero rather than dying, and a store with
        no upkeep never starves anything.
        """
        if self.upkeep <= 0 or entry.pinned:
            return None
        return round(entry.energy / self.upkeep, 1)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uvx --python 3.13 --with-editable . --with pytest --with hypothesis pytest tests/test_store.py -k starvation -v`
Expected: 2 passed

- [ ] **Step 5: Route every surface through it**

In `darwin_memo/ui.py`'s `state()`, delete the inline `entry.energy / upkeep` arithmetic and call `store.ticks_to_starvation(entry)`. In `darwin_memo/observe.py`, add the same field to `top_row()` and to `entry_life()`'s returned dict.

The API payload keeps the key name `ticks_to_starvation` and `null` for the cannot-starve case — `ui/src/api.ts` already types it `number | null` and `LivingTable.tsx` already renders `?? "—"`, so no frontend change is needed. Verify that claim by reading both files before you rely on it.

- [ ] **Step 6: Prove one definition, three surfaces**

```python
def test_one_definition_across_cli_and_api(tmp_path):
    """top, why and /api/state must not be able to disagree."""
    memory, ledger = seeded_ledger(tmp_path)
    ledger.save(memory)
    entry = ledger.store.alive()[0]
    expected = ledger.store.ticks_to_starvation(entry)

    top = _json_out(capsys, ["top", str(memory), "--json"])
    row = next(r for r in top["entries"] if r["id"] == entry.id)
    assert row["ticks_to_starvation"] == expected

    life = entry_life(ledger, entry.id)
    assert life["ticks_to_starvation"] == expected
```

Adapt to the real `_json_out`/`seeded_ledger` helpers already in `tests/test_observe.py` (they take `capsys`; wire it through as a fixture argument).

- [ ] **Step 7: Mutation check — REQUIRED**

Change the helper to `entry.energy / self.upkeep` without the pinned guard. Confirm `test_pinned_and_free_entries_never_starve` FAILS. Revert; confirm it passes; confirm `git status` is clean. Report both observations. A test that passes either way is the defect this step exists to catch.

- [ ] **Step 8: Verify and commit**

```bash
uvx ruff format darwin_memo/store.py darwin_memo/observe.py darwin_memo/ui.py tests/
uvx ruff check darwin_memo/store.py darwin_memo/observe.py darwin_memo/ui.py tests/
uvx --python 3.13 --with-editable . --with pytest --with hypothesis mypy
uvx --python 3.13 --with-editable . --with pytest --with hypothesis pytest -q
darwin-memo doctor /private/tmp/.../scratchpad/demo.json   # clean, exit 0
git add -A && git commit -m "feat: ticks_to_starvation as one definition across surfaces"
```

---

## Task 2: exact upkeep in the tick event

**Files:**
- Modify: `darwin_memo/store.py` (`charge_upkeep` records the total)
- Modify: `darwin_memo/ledger.py` (`tick()` logs it)
- Modify: `darwin_memo/observe.py` (`economics()` prefers it)
- Test: `tests/test_ledger.py`, `tests/test_observe.py`

**Interfaces:**
- Consumes: `Task 1` unchanged.
- Produces: `MemoryStore.last_upkeep_charged: float`; a `upkeep_charged` key in every new `tick` event; `economics()["energy"]["upkeep_exact"]` becoming `True` on new logs.

- [ ] **Step 1: Write the failing tests**

```python
def test_tick_event_records_the_upkeep_actually_charged(tmp_path):
    memory, ledger = seeded_ledger(tmp_path)
    ledger.tick()
    ledger.save(memory)
    ticks = [e for e in read_events(memory.with_suffix(".events.jsonl"))
             if e.get("event") == "tick"]
    assert ticks[-1]["upkeep_charged"] == pytest.approx(
        len(ledger.store) * ledger.store.upkeep
    ), "no pinned entries here, so charged equals the naive estimate"


def test_economics_prefers_the_logged_figure(tmp_path):
    memory, ledger = seeded_ledger(tmp_path)
    ledger.tick()
    ledger.save(memory)
    report = economics(read_events(memory.with_suffix(".events.jsonl")),
                       ledger.store)
    assert report["energy"]["upkeep_exact"] is True
    assert report["energy"]["upkeep_caveat"] == ""


def test_economics_falls_back_on_a_legacy_log(tmp_path):
    """A log written before this release must still report the old number."""
    memory, ledger = seeded_ledger(tmp_path)
    ledger.tick()
    ledger.save(memory)
    log = memory.with_suffix(".events.jsonl")
    stripped = []
    for record in read_events(log):
        record.pop("upkeep_charged", None)
        stripped.append(record)
    log.write_text("\n".join(json.dumps(r) for r in stripped) + "\n")

    report = economics(read_events(log), ledger.store)
    assert report["energy"]["upkeep_exact"] is False
    assert report["energy"]["upkeep_paid"] == pytest.approx(
        len(ledger.store) * ledger.store.upkeep
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `uvx --python 3.13 --with-editable . --with pytest --with hypothesis pytest tests/test_ledger.py tests/test_observe.py -k upkeep -v`
Expected: FAIL — `KeyError: 'upkeep_charged'`.

- [ ] **Step 3: Record the charge**

`MemoryStore.charge_upkeep` has **seven callers** (`survival.py`, `ledger.py`, `bench/suites.py`, `bench/judge.py`, `bench/swebench_cl/runner.py`, and two in `tests/`). Do NOT change its return type. Accumulate the deduction and store it:

```python
        charged = 0.0
        for entry in list(self._entries.values()):
            before = entry.energy
            entry.energy -= self.upkeep
            if entry.pinned:
                entry.energy = max(entry.energy, 0.0)
            charged += before - entry.energy
            ...
        self.last_upkeep_charged = round(charged, 6)
```

Initialise `self.last_upkeep_charged = 0.0` in `__init__` so the attribute always exists. Fold the accumulation into the existing loop rather than adding a second pass, and keep the existing dead-entry logic exactly as it is — this task must not change who dies.

- [ ] **Step 4: Log it**

In `Ledger.tick()`, add `"upkeep_charged": self.store.last_upkeep_charged` to the `stats` dict that is already built and logged. It must be read AFTER `charge_upkeep` runs.

- [ ] **Step 5: Prefer it in `economics()`**

Read `upkeep_charged` from the tick records. **All-or-nothing:** use the logged sum only when EVERY tick record carries the field; otherwise fall back to the population estimate and leave `upkeep_exact` false. A mixed log summing real and estimated figures would report a number that is neither, which is worse than an honest estimate. Set `upkeep_exact` accordingly and clear `upkeep_caveat` when exact.

- [ ] **Step 6: Run to verify they pass**

Run: `uvx --python 3.13 --with-editable . --with pytest --with hypothesis pytest tests/test_ledger.py tests/test_observe.py -v`
Expected: all pass

- [ ] **Step 7: Prove the estimate was actually wrong — REQUIRED**

The whole point is that pinned entries make the estimate wrong. Write a test with a pinned entry sitting at zero energy, tick, and assert the logged `upkeep_charged` is STRICTLY LESS than `population × upkeep`. If they are equal, the feature is measuring nothing and the task has failed — say so rather than adjusting the assertion.

- [ ] **Step 8: Mutation check — REQUIRED**

Make `charge_upkeep` record `len(self._entries) * self.upkeep` instead of the accumulated deduction. Confirm the Step-7 test FAILS. Revert; confirm it passes; confirm `git status` is clean.

- [ ] **Step 9: Verify and commit**

Full suite, ruff, mypy, and the Phase 1 acceptance gate on both demo stores. Coverage must not fall below 80.

```bash
git add -A && git commit -m "feat: log the upkeep actually charged, retiring the estimate"
```

---

## Task 3: defend the activation invariant (Track B)

**Files:**
- Create: `tests/test_organic_invariant.py`
- Branch: `feat/organic-memory-phase2` (NOT `feat/mechanism-depth` — Track B is independent)

**Interfaces:**
- Consumes: `darwin_memo/organic/activation.py` (`ActivationState`, `surface`, `detail`).
- Produces: nothing other tasks depend on.

**Context:** the invariant is *activation must never influence retention*. It holds today by construction — `activation.py` is a pure in-memory id→float map plus a surfacing helper, and nothing outside `darwin_memo/organic/` references it — but nothing defends it. The evidence for why it matters is this repo's own `salience_matched` bench arm: usage-importance used as a retention signal shields consulted poison, kill rate 0.20 against random's 0.80, because it cannot tell "used" from "useful".

- [ ] **Step 1: Check out the branch and confirm the baseline**

```bash
git worktree add /Users/rogersimoes/darwin-memo-organic feat/organic-memory-phase2
```

Confirm the suite passes there before adding anything, and record the number.

- [ ] **Step 2: Write the structural test**

```python
SELECTION_MODULES = ("store", "ledger", "survival", "consolidate")


def test_selection_path_never_references_activation():
    """An architectural rule, enforced the only way it can be.

    Activation is a recall-salience signal. If anything that decides who
    lives ever reads it, usage becomes a retention signal — and this
    repo's own salience_matched arm measured what that does: consulted
    poison gets shielded, kill rate 0.20 against random's 0.80.
    """
    import darwin_memo
    root = Path(darwin_memo.__file__).parent
    for name in SELECTION_MODULES:
        source = (root / f"{name}.py").read_text()
        assert "activation" not in source.lower(), (
            f"{name}.py references activation; retention must not see it"
        )
```

- [ ] **Step 3: Write the behavioural test**

```python
def test_activation_cannot_shield_a_poisoned_entry():
    """Pinning activation at maximum must not change who dies, or when."""
    baseline = run_selection(seed=7, activation=None)
    shielded = run_selection(seed=7, activation="max-on-poison")
    assert shielded.death_cycle == baseline.death_cycle
    assert shielded.survivors == baseline.survivors
```

Build `run_selection` from the existing bench or test helpers on that branch — reuse `StorageEnv`/`SurvivalLoop` rather than inventing a harness. The two runs must share a seed so the comparison is paired; if the loop is not deterministic under a fixed seed, say so and use several seeds with an identical-outcome assertion instead.

- [ ] **Step 4: Mutation check — REQUIRED, and this is the acceptance criterion**

Deliberately wire the violation: make a copy of `store.py`'s upkeep path read an activation level and skip the deduction for highly-activated entries. Confirm BOTH tests fail — the structural one on the reference, the behavioural one on the changed death cycle. Revert; confirm both pass; confirm `git status` is clean. Report exactly what you ran and saw for each.

If the behavioural test passes under the wired violation, it is decorative and must be strengthened before this task is done.

- [ ] **Step 5: Commit on the organic branch**

```bash
git commit -m "test: defend the invariant that activation never influences retention"
```

Do NOT merge, push, or open a PR. Report the branch state and stop.

---

## Task 4: PR disposition (needs the human's go-ahead — do not start unprompted)

**#33** (associative graph) is additive, opt-in, zero-dep by default, and targets `main`. **#34** (activation + gist↔detail) stacks on it and must not merge until Task 3's tests are on its branch.

Both merge to `main`, while Phase 1 (`feat/operator-surface`, 23 commits) is also unmerged against `main`. Whoever lands second rebases. That ordering is the human's call, not this plan's, and merging is not reversible in the way the rest of this plan is.

This task is a placeholder: surface the state, recommend an order, and wait.

---

## Verification

1. `ticks_to_starvation` agrees across `darwin-memo top --json`, `entry_life`, and `/api/state` on one store — the anti-drift property this task exists for.
2. On a store with a pinned entry at zero, `upkeep_charged` is strictly less than `population × upkeep`, and `economics()` reports `upkeep_exact: true`.
3. An event log with the field stripped still reports the old estimate and `upkeep_exact: false`.
4. Both invariant tests fail against a deliberately-wired violation and pass after revert.
5. The Phase 1 acceptance gate still holds on both demo stores, unmutated.
6. Full suite at or above the 428-passed / 91.52% baseline, coverage above the 80% gate.

## Non-goals

- No new selection knob; no change to selection mechanics, credit assignment, or death conditions.
- No frontend work beyond `ui.py` calling the helper — `api.ts` already types the field nullable.
- No merging, pushing, or PR creation without explicit approval.
- Nothing from organic Phase 3 (spreading activation, Hebbian reweighting). It inherits both invariant tests when it comes.
