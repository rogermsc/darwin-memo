# Organic memory — Phase 3 (spreading activation + Hebbian reweighting) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `dynamics.py` module to `darwin_memo/organic/` with two classes — `HebbianWeights` (learned co-recall strengths) and an `OrganicMemory` facade — so a recall *spreads* activation one hop to related memories and co-recalled links *strengthen*, while unused links fade.

**Architecture:** Purely additive on top of Phases 1–2. `HebbianWeights` is a symmetric `dict[frozenset[str], float]` of learned associations. `OrganicMemory` ties the Phase 1 `AssociativeGraph` (innate cosine), Phase 2 `ActivationState` (fast salience), and the new `HebbianWeights` (slow association) into one object: `recall()` bumps + spreads + strengthens, `related()` returns the *effective* relatedness `clamp01(cosine + learned)`, `decay()` runs two timescales (activation ×0.5, Hebbian ×0.9). No core change, no new deps, no judge; activation and learned weights gate surfacing/ranking only — never survival.

**Tech Stack:** Python 3.10+, stdlib only. Lives in `darwin_memo/organic/` (omitted from the coverage gate; still mypy-checked via `files=["darwin_memo","tests"]`).

**Standing preferences (override the skill's TDD default):** no TDD, no pytest run, no pass/fail reporting. Verification is by REPL snippet + `ruff` + `mypy`, exactly as Phases 1–2 were verified. Commit at each task; do **not** push or open the PR until the user asks.

**Reference:** spec at `docs/superpowers/specs/2026-06-16-organic-memory-phase3-design.md`. Interfaces this builds on (already in the tree):
- `darwin_memo/organic/associative.py`: `build_graph(store, embedder=None, backend=None) -> AssociativeGraph`; `AssociativeGraph.related(entry_id, k=5) -> list[tuple[str, float]]` (cosine, clamped to [0,1], self excluded); `Embedder`/`Backend` protocols.
- `darwin_memo/organic/activation.py`: `ActivationState` (`bump(id, to=1.0)` raises only, `decay(factor=0.5)`, `level(id)`), `surface(entry, state, threshold=0.5)`, `detail(entry)`.
- `darwin_memo/store.py`: `MemoryStore.add(entry)`, `MemoryStore.alive() -> list[MemoryEntry]`.

---

## File structure

- **Create:** `darwin_memo/organic/dynamics.py` — both new classes (`HebbianWeights`, `OrganicMemory`) plus module constants and a `_clamp01` helper. One file: the two classes are the Phase 3 unit and always change together.
- **Modify:** `darwin_memo/organic/__init__.py` — export the two new names.
- **Modify:** `docs/organic.md` — mark Phase 3 done, document the `OrganicMemory` facade.
- **Modify:** `CHANGELOG.md` — Unreleased / Added bullet.

---

## Task 1: `HebbianWeights` (learned co-recall strengths)

**Files:**
- Create: `darwin_memo/organic/dynamics.py`

- [ ] **Step 1: Create `dynamics.py` with the module docstring, imports, constants, helper, and `HebbianWeights`.**

```python
"""Dynamics: spreading activation + Hebbian reweighting — the moving organic memory.

Phase 3 of the organic layer. ``HebbianWeights`` records learned co-recall
strengths; ``OrganicMemory`` ties the Phase 1 associative graph (innate cosine),
Phase 2 activation (fast salience), and these learned weights (slow association)
into one adaptive object. A recall spreads activation one hop to related
memories and strengthens the links it traverses; unused links fade on decay.

Organic-only and in-memory: the darwin-memo core is untouched, there are no new
runtime deps, and there is no judge. Activation and learned weights gate
SURFACING and RANKING only — there is no code path from this module to the
energy ledger. Value is still earned only by survival.
"""

from __future__ import annotations

from darwin_memo import MemoryEntry, MemoryStore

from .activation import ActivationState
from .activation import surface as _surface
from .associative import Backend, Embedder, build_graph

SPREAD_FACTOR = 0.5
HEBB_INCREMENT = 0.25
HEBB_DECAY = 0.9
_PRUNE_EPSILON = 1e-3


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


class HebbianWeights:
    """Symmetric learned co-recall strengths in [0, 1], keyed by id pair.

    A link strengthens each time its two ids are recalled together and decays
    globally so associations that stop being used fade back toward zero.
    """

    def __init__(self) -> None:
        self._weights: dict[frozenset[str], float] = {}

    def strengthen(self, a: str, b: str, by: float = HEBB_INCREMENT) -> None:
        """Add ``by`` to the (a, b) link, clamped to 1.0. Self-links ignored."""
        if a == b:
            return
        key = frozenset({a, b})
        self._weights[key] = min(1.0, self._weights.get(key, 0.0) + by)

    def decay(self, factor: float = HEBB_DECAY) -> None:
        """One cycle of forgetting: scale every link by ``factor``; prune ~0."""
        for key in list(self._weights):
            value = self._weights[key] * factor
            if value < _PRUNE_EPSILON:
                del self._weights[key]
            else:
                self._weights[key] = value

    def weight(self, a: str, b: str) -> float:
        """Learned strength of the (a, b) link; 0.0 if none (or a == b)."""
        if a == b:
            return 0.0
        return self._weights.get(frozenset({a, b}), 0.0)

    def neighbors(self, entry_id: str) -> dict[str, float]:
        """All ids learned-linked to ``entry_id`` mapped to their weight."""
        out: dict[str, float] = {}
        for key, value in self._weights.items():
            if entry_id in key:
                (other,) = key - {entry_id}
                out[other] = value
        return out
```

- [ ] **Step 2: Verify `HebbianWeights` in a REPL.**

Run (from the worktree root `~/darwin-memo-organic`):

```bash
python -c "
from darwin_memo.organic.dynamics import HebbianWeights
h = HebbianWeights()
h.strengthen('a', 'b')                 # 0.25
h.strengthen('a', 'b')                 # 0.50 (symmetric: order-independent)
assert h.weight('b', 'a') == 0.5, h.weight('b', 'a')
h.strengthen('x', 'x')                 # self-link ignored
assert h.weight('x', 'x') == 0.0
assert h.neighbors('a') == {'b': 0.5}, h.neighbors('a')
h.decay()                              # 0.5 * 0.9 = 0.45
assert abs(h.weight('a', 'b') - 0.45) < 1e-9, h.weight('a', 'b')
for _ in range(60): h.decay()          # decays below epsilon -> pruned
assert h.neighbors('a') == {}, h.neighbors('a')
print('HebbianWeights OK')
"
```

Expected: prints `HebbianWeights OK` with no assertion error.

- [ ] **Step 3: Commit.**

```bash
git add darwin_memo/organic/dynamics.py
git commit -m "feat(organic): HebbianWeights — learned co-recall strengths (Phase 3)"
```

---

## Task 2: `OrganicMemory` facade (spreading activation + effective relatedness)

**Files:**
- Modify: `darwin_memo/organic/dynamics.py` (append the class)

- [ ] **Step 1: Append `OrganicMemory` to `dynamics.py`** (after `HebbianWeights`).

```python
class OrganicMemory:
    """The moving organic memory: graph + activation + learned weights as one.

    Builds an :class:`AssociativeGraph` over the store's living entries (innate
    cosine relatedness), a fresh :class:`ActivationState` (fast recall salience),
    and a fresh :class:`HebbianWeights` (slow learned association). A recall
    spreads activation one hop and strengthens the links it traverses; decay
    runs the two timescales. Surfacing/ranking only — never survival.
    """

    def __init__(
        self,
        store: MemoryStore,
        embedder: Embedder | None = None,
        backend: Backend | None = None,
    ) -> None:
        self.graph = build_graph(store, embedder, backend)
        self.state = ActivationState()
        self.hebbian = HebbianWeights()

    def related(self, entry_id: str, k: int = 5) -> list[tuple[str, float]]:
        """Effective relatedness: ``clamp01(cosine + learned)``, top-k.

        Takes the cosine top-``2k`` from the innate graph plus any purely
        learned neighbours (cosine treated as 0), overlays the learned weights,
        re-ranks, and returns the top ``k`` (deterministic; id breaks ties).
        """
        cosine = dict(self.graph.related(entry_id, 2 * k))
        learned = self.hebbian.neighbors(entry_id)
        candidates = set(cosine) | set(learned)
        scored = [
            (cid, _clamp01(cosine.get(cid, 0.0) + learned.get(cid, 0.0)))
            for cid in candidates
        ]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:k]

    def recall(
        self, entry_id: str, k: int = 5, spread: float = SPREAD_FACTOR
    ) -> None:
        """The reminder: light up ``entry_id``, spread a fraction of activation
        one hop to its effective neighbours, and strengthen each link traversed.
        """
        self.state.bump(entry_id)
        for nbr, eff in self.related(entry_id, k):
            self.state.bump(nbr, to=spread * eff)
            self.hebbian.strengthen(entry_id, nbr)

    def decay(self) -> None:
        """One idle cycle: activation fades fast (x0.5), learned links slow (x0.9)."""
        self.state.decay()
        self.hebbian.decay()

    def surface(self, entry: MemoryEntry) -> str:
        """Gist when cold, full detail when this entry is activated."""
        return _surface(entry, self.state)
```

- [ ] **Step 2: Verify the full loop in a REPL** — spreading raises a neighbour's activation and flips its surface toward detail; repeated co-recall lifts a learned-linked id in `related()`; `decay()` lowers both timescales.

Run (from `~/darwin-memo-organic`):

```bash
python -c "
from darwin_memo import MemoryEntry, MemoryStore
from darwin_memo.organic.dynamics import OrganicMemory

store = MemoryStore()
# Two near-identical entries (so cosine links them) + one unrelated.
store.add(MemoryEntry(id='a', question='How do I reset the cache?', answer='Run cache:clear to reset the cache.'))
store.add(MemoryEntry(id='b', question='How do I clear the cache?', answer='Run cache:clear to clear the cache.'))
store.add(MemoryEntry(id='c', question='What is the billing peg?', answer='2000 credits equal one dollar.'))
om = OrganicMemory(store)

# 1) Spreading: recall 'a' lights 'a' and spreads to its neighbour.
om.recall('a')
assert om.state.level('a') == 1.0
b = store.get('b')
assert om.state.level('b') > 0.0, 'spread should raise the neighbour'
# Surface flips toward detail only when the neighbour cleared the threshold.
print('b activation after spread:', round(om.state.level('b'), 4))
print('b surface:', om.surface(b))

# 2) Hebbian: co-recall (a,b) repeatedly -> learned(a,b) grows.
for _ in range(4):
    om.recall('a')
    om.recall('b')
w = om.hebbian.weight('a', 'b')
assert w > 0.0, 'co-recall should build a learned link'
print('learned(a,b):', round(w, 4))
rel = dict(om.related('a'))
print('related(a) incl. learned overlay:', {k: round(v, 4) for k, v in rel.items()})
assert rel.get('b', 0.0) >= dict(om.graph.related('a', 10)).get('b', 0.0), 'effective >= cosine'

# 3) Decay: both timescales drop.
before_act, before_w = om.state.level('a'), om.hebbian.weight('a', 'b')
om.decay()
assert om.state.level('a') < before_act
assert om.hebbian.weight('a', 'b') < before_w
print('OrganicMemory loop OK')
"
```

Expected: prints the activation/learned/related diagnostics and ends with `OrganicMemory loop OK`, no assertion error. (Exact magnitudes depend on the coarse HashingEmbedder; the assertions check direction, not absolute values.)

- [ ] **Step 3: Commit.**

```bash
git add darwin_memo/organic/dynamics.py
git commit -m "feat(organic): OrganicMemory facade — spreading activation + effective relatedness (Phase 3)"
```

---

## Task 3: Export the new names and run the gates

**Files:**
- Modify: `darwin_memo/organic/__init__.py`

- [ ] **Step 1: Add the Phase 3 imports and `__all__` entries.**

In `darwin_memo/organic/__init__.py`, add a `dynamics` import after the `associative` import:

```python
from .activation import ActivationState, detail, surface
from .associative import (
    AssociativeGraph,
    BruteForceBackend,
    build_graph,
    store_related,
)
from .dynamics import HebbianWeights, OrganicMemory
```

and add `"HebbianWeights"` and `"OrganicMemory"` to `__all__`, keeping it sorted:

```python
__all__ = [
    "ActivationState",
    "AssociativeGraph",
    "BruteForceBackend",
    "HebbianWeights",
    "OrganicMemory",
    "build_graph",
    "detail",
    "store_related",
    "surface",
]
```

- [ ] **Step 2: Verify the package-level import.**

Run (from `~/darwin-memo-organic`):

```bash
python -c "from darwin_memo.organic import HebbianWeights, OrganicMemory; print('exports OK')"
```

Expected: prints `exports OK`.

- [ ] **Step 3: Run lint + type gates** (the CI gates, minus pytest per standing preference).

Run (from `~/darwin-memo-organic`):

```bash
ruff check . && ruff format --check . && mypy
```

Expected: `ruff` reports `All checks passed!`, `ruff format --check` reports the files are already formatted, and `mypy` reports `Success: no issues found`. If `ruff format --check` flags `dynamics.py`, run `ruff format darwin_memo/organic/dynamics.py` and re-run the gates.

- [ ] **Step 4: Commit.**

```bash
git add darwin_memo/organic/__init__.py
git commit -m "feat(organic): export HebbianWeights + OrganicMemory (Phase 3)"
```

---

## Task 4: Docs + CHANGELOG

**Files:**
- Modify: `docs/organic.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update the Status list in `docs/organic.md`.**

Replace the Phase 2 line and the Phases 3–4 line:

```markdown
- **Phase 2 — activation + lossless gist↔detail.** A recalled memory expands
  to full detail; an idle one shrinks to its gist.
- **Phase 3 — spreading activation + Hebbian reweighting (this release).** A
  recall spreads activation one hop to related memories and strengthens the
  links it traverses; unused links fade. The `OrganicMemory` facade ties the
  graph, activation, and learned weights into one adaptive object.
- Phase 4 (earned importance/potentiation) is specced but not yet implemented.
```

- [ ] **Step 2: Add a Phase 3 usage section to `docs/organic.md`** (after the "Activation & surfacing (Phase 2)" section, before "Backends").

```markdown
## The moving memory: `OrganicMemory` (Phase 3)

`OrganicMemory` is the adaptive facade tying Phases 1–3 together. A recall
*spreads* a fraction of activation one hop to related memories (so connected
details surface), and each link a recall traverses *strengthens* (Hebbian) —
so usage, not just innate similarity, shapes what comes back. Two timescales:
activation fades fast (×0.5 per cycle), learned links fade slow (×0.9).

```python
from darwin_memo import MemoryStore
from darwin_memo.organic import OrganicMemory

om = OrganicMemory(store)          # builds graph + activation + learned weights

om.recall("entry-a")               # light a; spread one hop; strengthen links
om.related("entry-a", k=5)         # effective relatedness: clamp01(cosine + learned)
om.surface(entry)                  # gist when cold, full detail when activated
om.decay()                         # one idle cycle: activation x0.5, links x0.9
```

`related()` overlays the learned weights on the innate cosine
(`AssociativeGraph.related()` remains the pure-cosine primitive), so repeatedly
recalling two memories together lifts one in the other's neighbours even when
their cosine similarity is modest. As with activation, the learned weights gate
*surfacing and ranking only* — there is no path from this layer to the energy
ledger, and no judge.
```

- [ ] **Step 2b: Verify the docs fence balance** (the Phase 3 block nests a Python fence inside the section — make sure the outer code fences still match).

Run (from `~/darwin-memo-organic`):

```bash
python -c "n=open('docs/organic.md').read().count(chr(96)*3); print('fences:', n); assert n % 2 == 0, 'unbalanced code fences'"
```

Expected: prints an even fence count and no assertion error. (If odd, the inner Python ```` ```python ```` block needs a four-backtick wrapper around the example; switch the outer fence of the Phase 3 usage block to ```` ```` ```` four backticks.)

- [ ] **Step 3: Add the CHANGELOG entry.**

In `CHANGELOG.md`, under `## [Unreleased]` → `### Added`, add as the first bullet:

```markdown
- Organic memory Phase 3: spreading activation + Hebbian reweighting via a new
  `OrganicMemory` facade (`darwin_memo.organic`). A recall spreads a fraction of
  activation one hop to related memories and strengthens the links it traverses
  (`HebbianWeights`, symmetric learned co-recall strengths); `related()` returns
  the effective relatedness `clamp01(cosine + learned)`, and `decay()` runs two
  timescales (activation ×0.5, learned links ×0.9). Additive over Phases 1–2,
  core untouched; activation and learned weights gate surfacing/ranking only,
  never survival — no judge, no new runtime deps.
```

- [ ] **Step 4: Re-run the gates and commit.**

Run (from `~/darwin-memo-organic`):

```bash
ruff check . && ruff format --check . && mypy
git add docs/organic.md CHANGELOG.md
git commit -m "docs: organic-memory Phase 3 (spreading activation + Hebbian reweighting)"
```

Expected: gates pass; commit succeeds.

---

## Finishing

After Task 4, hand off to **superpowers:finishing-a-development-branch**. Standing preference: no pytest run, no pass/fail reporting; the gate substitute is the REPL checks + `ruff`/`mypy` above. Do **not** push or open the PR until the user asks. When the user asks, the PR stacks on Phase 2:

```bash
gh pr create --base feat/organic-memory-phase2 --title "Organic memory Phase 3: spreading activation + Hebbian reweighting" --body "..."
```

Retarget the PR base up the stack to `main` as the parent PRs (#33, #34) merge.

---

## Self-review (against the spec)

**Spec coverage:**
- §2 combine rule `clamp01(cosine + learned)` → Task 2 `related()`. ✓
- §2 two timescales (activation ×0.5, Hebbian ×0.9) → Task 2 `decay()`; `HEBB_DECAY=0.9` in Task 1, activation ×0.5 inherited from Phase 2. ✓
- §2 additive (Phase 1 `related()` stays pure cosine) → Task 2 uses `self.graph.related()` as the cosine primitive and overlays separately; Phase 1 file untouched. ✓
- §3 `HebbianWeights` (storage, `strengthen`/`decay`/`weight`/`neighbors`) → Task 1. ✓
- §3 `OrganicMemory` (`__init__`/`related`/`recall`/`decay`/`surface`, exposes `.graph`/`.state`/`.hebbian`) → Task 2 (all three attrs are public). ✓
- §3 constants (`SPREAD_FACTOR`, `HEBB_INCREMENT`, `HEBB_DECAY`, `_PRUNE_EPSILON`) → Task 1 module level, overridable as kwargs. ✓
- §5 invariants (core untouched, no judge, no deps, gates surfacing/ranking not survival) → module docstring + no energy import; verified by inspection. ✓
- §7 verification (recall raises neighbour activation + flips surface; co-recall lifts learned; decay lowers both; ruff/mypy) → Task 2 Step 2 + Task 3 Step 3. ✓
- §8 build sequence (dynamics.py → export → verify → docs/CHANGELOG → PR) → Tasks 1–4 + Finishing. ✓

**Placeholder scan:** none — every code step shows complete code; every run step shows the command and expected output.

**Type consistency:** `related()` returns `list[tuple[str, float]]` (matches `AssociativeGraph.related`); `recall()`/`decay()`/`surface()` signatures match the spec; `HebbianWeights` method names (`strengthen`/`decay`/`weight`/`neighbors`) are used identically in Task 1, Task 2, and the REPL checks; `_surface` alias avoids shadowing the `surface` method. Constants referenced (`SPREAD_FACTOR`, `HEBB_INCREMENT`, `HEBB_DECAY`, `_PRUNE_EPSILON`, `_clamp01`) are all defined in Task 1 Step 1.
