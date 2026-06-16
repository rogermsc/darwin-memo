# Organic Memory — Phase 2 (Activation + Lossless Gist↔Detail) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an in-memory `ActivationState` (recall-salience) and lossless gist↔detail surfacing to `darwin_memo.organic`, so a recalled memory expands to detail and an idle one shrinks to its gist — without touching the core.

**Architecture:** One new module `darwin_memo/organic/activation.py`: `ActivationState` (dict id→[0,1], `bump`/`decay`/`level`) plus pure surfacing functions `detail(entry)` and `surface(entry, state, threshold)`. Organic-only, in-memory, explicit recall/decay, no judge, core untouched.

**Tech Stack:** Pure Python; reuses `darwin_memo.MemoryEntry`; no new deps.

**Testing stance:** No TDD, no pytest run/report (standing preference). Verify by running. `organic/` is already omitted from the coverage gate; mypy-strict still applies (write it typed). `ruff`/`mypy` must stay clean.

**Facts:** `MemoryEntry` has `id: str`, `question: str`, `answer: str`, `sources: list[str]` (verified in `darwin_memo/types.py`). Phase 1 already shipped `darwin_memo/organic/{__init__,associative,turbovec_backend}.py` on the parent branch.

**Env:** `KMP_DUPLICATE_LIB_OK=TRUE ~/darwin-memo-organic/.venv-organic/bin/python ...` (venv carried over from Phase 1).

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `darwin_memo/organic/activation.py` | create | `ActivationState` + `detail`/`surface`. |
| `darwin_memo/organic/__init__.py` | modify | Export the new names. |
| `docs/organic.md`, `CHANGELOG.md` | modify | Phase 2 docs. |

---

## Task 1: `activation.py` + surfacing

**Files:** Create `darwin_memo/organic/activation.py`; modify `darwin_memo/organic/__init__.py`.

- [ ] **Step 1: Write `darwin_memo/organic/activation.py`**

```python
"""Activation: a fast recall-salience signal + lossless gist<->detail surfacing.

Organic-only and in-memory: the darwin-memo core is untouched. Recall (bump) and
decay are explicit calls the consumer wires, exactly like the survival loop.
Activation gates SURFACING only; it never feeds the energy ledger and never
keeps a dead entry alive. Surfacing is lossless: the MemoryEntry is never
mutated; a cold memory shows only its gist (question), a hot one its full detail.
"""

from __future__ import annotations

from darwin_memo import MemoryEntry

BUMP_TO = 1.0
DECAY_FACTOR = 0.5
SURFACE_THRESHOLD = 0.5
_PRUNE_EPSILON = 1e-3


class ActivationState:
    """In-memory id -> activation in [0, 1]. Recall raises it; idle decays it."""

    def __init__(self) -> None:
        self._levels: dict[str, float] = {}

    def bump(self, entry_id: str, to: float = BUMP_TO) -> None:
        """Recall: raise the entry's activation to ``to`` (never lowers it)."""
        self._levels[entry_id] = max(self._levels.get(entry_id, 0.0), to)

    def decay(self, factor: float = DECAY_FACTOR) -> None:
        """One idle cycle: scale every activation by ``factor``; prune ~0."""
        for entry_id in list(self._levels):
            value = self._levels[entry_id] * factor
            if value < _PRUNE_EPSILON:
                del self._levels[entry_id]
            else:
                self._levels[entry_id] = value

    def level(self, entry_id: str) -> float:
        return self._levels.get(entry_id, 0.0)


def detail(entry: MemoryEntry) -> str:
    """The full retained detail of a memory (the explicit 'remind me' surface)."""
    text = f"{entry.question} {entry.answer}"
    if entry.sources:
        text += f" (sources: {', '.join(entry.sources)})"
    return text


def surface(
    entry: MemoryEntry, state: ActivationState, threshold: float = SURFACE_THRESHOLD
) -> str:
    """Gist when the memory is cold (activation < threshold), else full detail.

    Lossless: reads only; never mutates ``entry`` or ``state``.
    """
    if state.level(entry.id) < threshold:
        return entry.question
    return detail(entry)
```

- [ ] **Step 2: Export from `darwin_memo/organic/__init__.py`.** Replace its body with:

```python
"""Organic memory: an adaptive, brain-like layer over darwin-memo (opt-in)."""

from __future__ import annotations

from .activation import ActivationState, detail, surface
from .associative import (
    AssociativeGraph,
    BruteForceBackend,
    build_graph,
    store_related,
)

__all__ = [
    "AssociativeGraph",
    "BruteForceBackend",
    "build_graph",
    "store_related",
    "ActivationState",
    "detail",
    "surface",
]
```

- [ ] **Step 3: Verify the bump→detail / decay→gist loop**

Run:
```bash
cd ~/darwin-memo-organic
KMP_DUPLICATE_LIB_OK=TRUE .venv-organic/bin/python -c "
from darwin_memo import MemoryEntry
from darwin_memo.organic import ActivationState, surface, detail
e = MemoryEntry(question='What port does Helios use?', answer='Port 8400.', sources=['runbook'])
st = ActivationState()
print('cold  ->', repr(surface(e, st)))          # gist (question only)
st.bump(e.id)
print('recalled ->', repr(surface(e, st)))        # full detail
st.decay(); print('after 1 decay level=', round(st.level(e.id),3), '->', repr(surface(e, st)))  # 0.5 -> detail (>= threshold)
st.decay(); print('after 2 decays level=', round(st.level(e.id),3), '->', repr(surface(e, st)))  # 0.25 -> gist
print('detail() always ->', repr(detail(e)))
assert surface(e, ActivationState()) == e.question, 'cold surfaces gist'
st2 = ActivationState(); st2.bump(e.id)
assert 'Port 8400' in surface(e, st2), 'hot surfaces detail'
print('OK')
"
```
Expected: cold → just the question; recalled → full detail with sources; after 1 decay (0.5) still detail; after 2 decays (0.25) back to gist; `detail()` always full; `OK`. (Note: at exactly threshold 0.5 the rule is `< threshold` → detail, matching the print.)

- [ ] **Step 4: ruff + mypy + commit**

```bash
cd ~/darwin-memo-organic
.venv-organic/bin/python -m ruff check darwin_memo/organic/ && .venv-organic/bin/python -m ruff format --check darwin_memo/organic/
.venv-organic/bin/python -m mypy 2>&1 | tail -2
git add darwin_memo/organic/activation.py darwin_memo/organic/__init__.py
git commit -m "feat(organic): activation state + lossless gist<->detail surfacing (Phase 2)"
```
Expected: ruff clean; mypy `Success`.

---

## Task 2: Docs + PR

**Files:** Modify `docs/organic.md`, `CHANGELOG.md`.

- [ ] **Step 1: `docs/organic.md`** — under Status, mark Phase 2 done and add an "Activation & surfacing" subsection with the API and behavior:

````markdown
- **Phase 2 — activation + lossless gist↔detail (this release).** A recalled
  memory expands to full detail; an idle one shrinks to its gist.

### Activation & surfacing

```python
from darwin_memo.organic import ActivationState, surface, detail

state = ActivationState()
surface(entry, state)      # cold -> gist (question only)
state.bump(entry.id)       # recall
surface(entry, state)      # hot  -> full detail
state.decay()              # one idle cycle (x0.5); call per cycle
detail(entry)              # always the full detail (explicit expand)
```

Activation is in-memory and ephemeral (reset on load); `bump`/`decay` are
explicit calls you wire, like the survival loop. It gates *surfacing* only —
never survival — and never mutates the entry (detail is always retained).
````

- [ ] **Step 2: `CHANGELOG.md`** `[Unreleased] / Added` — bullet:

```markdown
- Organic memory Phase 2: in-memory `ActivationState` (recall-salience;
  `bump`/`decay`/`level`) plus lossless `surface(entry, state)` / `detail(entry)`
  — a recalled memory expands to detail, an idle one shrinks to its gist, with
  the entry never mutated. Organic-only, core untouched; activation gates
  surfacing, never survival.
```

- [ ] **Step 3: Full lint + push + PR (stacked on Phase 1)**

```bash
cd ~/darwin-memo-organic
.venv-organic/bin/python -m ruff check . && .venv-organic/bin/python -m ruff format --check .
.venv-organic/bin/python -m mypy 2>&1 | tail -2
git add docs/organic.md CHANGELOG.md
git commit -m "docs: organic-memory Phase 2 (activation + gist<->detail)"
git push -u origin feat/organic-memory-phase2
gh pr create --base feat/organic-memory --title "Organic memory Phase 2: activation + lossless gist<->detail" --body "Stacked on #33 (Phase 1). Adds in-memory ActivationState (bump/decay/level) and lossless surface()/detail(): a recalled memory expands to full detail, an idle one shrinks to its gist, the entry never mutated. Organic-only, core untouched, no new deps, no judge; activation gates surfacing, never survival. Retarget to main once #33 merges. Spec: docs/superpowers/specs/2026-06-16-organic-memory-phase2-design.md.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```
Expected: ruff clean, mypy `Success`, PR created with base `feat/organic-memory`.

- [ ] **Step 4: Confirm CI** — `gh pr checks <PR#>`; lint + all test versions pass (coverage unaffected — organic is omitted; no core change).

---

## Self-review

**Spec coverage:** §3 components → Task 1 (`ActivationState.bump/decay/level`, `detail`, `surface` with the exact constants 1.0/0.5/0.5/1e-3); §4 behavior → Task 1 Step 3 verification (bump→detail, 2×decay→gist, detail always); §5 invariants (core untouched, no judge, activation never feeds survival) → no core/ledger imports in `activation.py`; §7 testing/docs → Task 1 Step 3 (run, no TDD) + Task 2. All covered.

**Placeholder scan:** only `<PR#>` (the new PR number, Task 2 Step 4). No TBD/TODO; complete code in every code step.

**Type consistency:** `ActivationState.bump(entry_id, to=1.0)`, `decay(factor=0.5)`, `level(entry_id)->float`; `detail(entry)->str`; `surface(entry, state, threshold=0.5)->str` — used identically in the `__init__` exports, the verification script, and the docs. Uses `MemoryEntry.id/question/answer/sources` which exist.
