# Organic Memory — Phase 1 (Associative Graph) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in associative-graph layer to darwin-memo — one vector per memory and `related(id, k)` relevance-weighted neighbours — with a zero-dep brute-force default and an optional turbovec ANN backend, as the substrate for later organic phases.

**Architecture:** New `darwin_memo/organic/` package, fully additive (core/ledger untouched). An `AssociativeGraph` pairs a pluggable **embedder** (zero-dep `HashingEmbedder` default; real-embedder extra later) with a pluggable **backend** (`BruteForceBackend` zero-dep default; `TurbovecBackend` behind the `[organic]` extra). It is read-only w.r.t. survival — it never touches energy.

**Tech Stack:** Python; reuse `darwin_memo.retrieval.HashingEmbedder`; optional `turbovec` (Rust ANN) + `numpy`; local dev.

**Testing stance:** No TDD, no pytest suite runs/reporting (standing preference). Verify by running. The opt-in `darwin_memo/organic/` layer is **omitted from the coverage gate** (it is optional and its turbovec path can't run in default CI) — flagged in the PR for review. The spec's single allowed check (zero-dep vs turbovec **top-k agreement**) is run **manually** as a verification step, not committed as a gating test. `ruff`/`mypy` must stay clean (organic IS in mypy-strict scope).

**Key facts (verified):** `HashingEmbedder` is callable `(text: str) -> list[float]` (`darwin_memo/retrieval.py:166,182`). `darwin_memo` exports `MemoryEntry`, `MemoryStore`. Coverage `source=["darwin_memo"]`, `fail_under=80`, currently no `omit`. mypy `files=["darwin_memo","tests"]`, strict.

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `darwin_memo/organic/__init__.py` | create | Public exports: `AssociativeGraph`, `BruteForceBackend`, `build_graph`, `store_related`. |
| `darwin_memo/organic/associative.py` | create | Embedder/Backend protocols, `_cosine`, `BruteForceBackend`, `AssociativeGraph`, `build_graph`, `store_related`. |
| `darwin_memo/organic/turbovec_backend.py` | create | `TurbovecBackend` (optional, import-guarded). |
| `pyproject.toml` | modify | `organic` extra; coverage `omit` for `darwin_memo/organic/*`; mypy `ignore_missing_imports` for `turbovec`. |
| `docs/organic.md`, `README.md`, `CHANGELOG.md` | modify/create | Operator doc + README section + changelog. |

---

## Task 1: Zero-dep associative graph

**Files:** Create `darwin_memo/organic/__init__.py`, `darwin_memo/organic/associative.py`; modify `pyproject.toml` (coverage omit + organic extra).

- [ ] **Step 1: `pyproject.toml` — coverage omit + organic extra.** Under `[project.optional-dependencies]` add:

```toml
organic = ["turbovec>=0.1", "numpy>=1.24"]
```

Change `[tool.coverage.run]` from:

```toml
[tool.coverage.run]
source = ["darwin_memo"]
```
to:
```toml
[tool.coverage.run]
source = ["darwin_memo"]
omit = ["darwin_memo/organic/*"]
```

- [ ] **Step 2: Write `darwin_memo/organic/associative.py`**

```python
"""Associative graph: one vector per memory and relevance-weighted neighbours.

The substrate for the organic-memory layer. Additive and read-only w.r.t.
survival: it never touches energy. Zero-dependency by default (HashingEmbedder
+ brute-force cosine); an optional turbovec backend handles scale.
"""

from __future__ import annotations

import math
from typing import Any, Protocol

from darwin_memo import MemoryEntry, MemoryStore
from darwin_memo.retrieval import HashingEmbedder


class Embedder(Protocol):
    def __call__(self, text: str) -> list[float]: ...


class Backend(Protocol):
    def add(self, entry_id: str, vector: list[float]) -> None: ...
    def remove(self, entry_id: str) -> None: ...
    def search(
        self, vector: list[float], k: int, exclude: str | None = None
    ) -> list[tuple[str, float]]: ...


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class BruteForceBackend:
    """Exact top-k cosine over an in-memory vector dict. Zero-dep; fine at the
    demo scale darwin-memo targets."""

    def __init__(self) -> None:
        self._vectors: dict[str, list[float]] = {}

    def add(self, entry_id: str, vector: list[float]) -> None:
        self._vectors[entry_id] = vector

    def remove(self, entry_id: str) -> None:
        self._vectors.pop(entry_id, None)

    def search(
        self, vector: list[float], k: int, exclude: str | None = None
    ) -> list[tuple[str, float]]:
        scored = [
            (eid, _cosine(vector, vec))
            for eid, vec in self._vectors.items()
            if eid != exclude
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]


def _entry_text(entry: MemoryEntry) -> str:
    """Gist + detail, the text we embed for relatedness."""
    return f"{entry.question} {entry.answer}"


class AssociativeGraph:
    """Memories embedded into a vector space with relevance-weighted links."""

    def __init__(
        self, embedder: Embedder | None = None, backend: Backend | None = None
    ) -> None:
        self.embedder: Embedder = embedder or HashingEmbedder()
        self.backend: Backend = backend or BruteForceBackend()
        self._vectors: dict[str, list[float]] = {}

    def add(self, entry: MemoryEntry) -> None:
        vec = self.embedder(_entry_text(entry))
        self._vectors[entry.id] = vec
        self.backend.add(entry.id, vec)

    def remove(self, entry_id: str) -> None:
        self._vectors.pop(entry_id, None)
        self.backend.remove(entry_id)

    def related(self, entry_id: str, k: int = 5) -> list[tuple[str, float]]:
        """Up to k related memory ids with relevance in [0, 1] (cosine, clamped)."""
        vec = self._vectors.get(entry_id)
        if vec is None:
            return []
        return [
            (eid, max(0.0, min(1.0, score)))
            for eid, score in self.backend.search(vec, k, exclude=entry_id)
        ]


def build_graph(
    store: MemoryStore,
    embedder: Embedder | None = None,
    backend: Backend | None = None,
) -> AssociativeGraph:
    """Build a graph from a store's living entries."""
    graph = AssociativeGraph(embedder, backend)
    for entry in store.alive():
        graph.add(entry)
    return graph


def store_related(
    store: MemoryStore,
    entry_id: str,
    k: int = 5,
    embedder: Embedder | None = None,
    backend: Backend | None = None,
) -> list[tuple[str, float]]:
    """Convenience: related memories for one entry, built from the store."""
    return build_graph(store, embedder, backend).related(entry_id, k)
```

- [ ] **Step 3: Write `darwin_memo/organic/__init__.py`**

```python
"""Organic memory: an adaptive, brain-like layer over darwin-memo (opt-in)."""

from __future__ import annotations

from .associative import (
    AssociativeGraph,
    BruteForceBackend,
    build_graph,
    store_related,
)

__all__ = ["AssociativeGraph", "BruteForceBackend", "build_graph", "store_related"]
```

- [ ] **Step 4: Verify the zero-dep graph on a real store**

Run:
```bash
cd ~/darwin-memo-organic
KMP_DUPLICATE_LIB_OK=TRUE .venv-organic/bin/python -c "
from bench.fixtures import build_headline_store
from darwin_memo.organic import store_related, build_graph
store = build_headline_store()
ids = [e.id for e in store.alive()]
g = build_graph(store)
rel = g.related(ids[0], k=3)
print('entry:', ids[0])
print('related:', [(rid[:8], round(s, 3)) for rid, s in rel])
assert all(0.0 <= s <= 1.0 for _, s in rel), 'relevance must be in [0,1]'
assert ids[0] not in [rid for rid, _ in rel], 'must exclude self'
print('OK: related() returns clamped, self-excluded neighbours')
"
```
Expected: prints related ids with relevances in `[0, 1]`, self excluded, and `OK:`. (Uses `build_headline_store` for a ready store; the venv `.venv-organic` is created in Step 0 of Task-2 environment if not present — see note.)

> **Env note:** create the dev venv once: `python3.13 -m venv ~/darwin-memo-organic/.venv-organic && ~/darwin-memo-organic/.venv-organic/bin/python -m pip install -e ~/darwin-memo-organic` (zero-dep core import works without extras). Add `.venv-organic/` to `.gitignore`.

- [ ] **Step 5: ruff + mypy + commit**

```bash
cd ~/darwin-memo-organic
.venv-organic/bin/python -m pip install -q ruff mypy
.venv-organic/bin/python -m ruff check darwin_memo/organic/ && .venv-organic/bin/python -m ruff format --check darwin_memo/organic/
.venv-organic/bin/python -m mypy 2>&1 | tail -2   # Success expected (organic is typed)
printf '.venv-organic/\n' >> .gitignore
git add darwin_memo/organic/ pyproject.toml .gitignore
git commit -m "feat(organic): zero-dep associative graph (vector per memory, related())"
```
Expected: ruff clean; mypy `Success`.

---

## Task 2: Optional turbovec backend + agreement check

**Files:** Create `darwin_memo/organic/turbovec_backend.py`; modify `pyproject.toml` (mypy override).

- [ ] **Step 1: Check the turbovec wheel for Python 3.13**

Run:
```bash
cd ~/darwin-memo-organic
.venv-organic/bin/python -m pip install turbovec numpy 2>&1 | tail -3
.venv-organic/bin/python -c "import turbovec, numpy; print('turbovec import OK')" 2>&1 | tail -2
```
If it installs and imports → proceed normally. **If no wheel for 3.13** (build/install fails): still write the backend (import-guarded), but skip the live agreement check in Step 4 and note "turbovec path unverified locally (no 3.13 wheel); zero-dep path is the guaranteed deliverable." Do not block.

- [ ] **Step 2: mypy override for turbovec.** In `pyproject.toml`, add `turbovec` to the existing `ignore_missing_imports` override module list:

```toml
    "torch", "torch.*",
    "transformers", "transformers.*",
    "peft", "peft.*",
    "datasets", "datasets.*",
    "turbovec", "turbovec.*",
```

- [ ] **Step 3: Write `darwin_memo/organic/turbovec_backend.py`**

```python
"""Optional turbovec ANN backend for the associative graph (the [organic] extra).

turbovec quantizes vectors for memory-efficient ANN at scale. It is import-
guarded: absence falls back to BruteForceBackend. turbovec uses integer ids, so
this maps memory string ids to ints; removals are tombstoned (turbovec has no
delete) and filtered at search time.
"""

from __future__ import annotations

from typing import Any


class TurbovecBackend:
    def __init__(self, dim: int, bit_width: int = 4) -> None:
        import numpy as np
        from turbovec import IdMapIndex

        self._np = np
        self._index = IdMapIndex(dim=dim, bit_width=bit_width)
        self._dim = dim
        self._to_int: dict[str, int] = {}
        self._to_str: dict[int, str] = {}
        self._dead: set[str] = set()
        self._next = 1

    def add(self, entry_id: str, vector: list[float]) -> None:
        self._dead.discard(entry_id)
        if entry_id not in self._to_int:
            iid = self._next
            self._next += 1
            self._to_int[entry_id] = iid
            self._to_str[iid] = entry_id
        vec = self._np.asarray([vector], dtype=self._np.float32)
        self._index.add_with_ids(vec, self._np.array([self._to_int[entry_id]]))

    def remove(self, entry_id: str) -> None:
        self._dead.add(entry_id)

    def search(
        self, vector: list[float], k: int, exclude: str | None = None
    ) -> list[tuple[str, float]]:
        query = self._np.asarray(vector, dtype=self._np.float32)
        # over-fetch to absorb tombstoned/excluded ids
        scores, ids = self._index.search(query, k + len(self._dead) + 1)
        out: list[tuple[str, float]] = []
        for score, iid in zip(scores, ids):
            sid = self._to_str.get(int(iid))
            if sid is None or sid == exclude or sid in self._dead:
                continue
            out.append((sid, float(score)))
            if len(out) == k:
                break
        return out
```

- [ ] **Step 4: Agreement check (manual; the spec's one exception)**

Run (skip if Step 1 found no wheel):
```bash
cd ~/darwin-memo-organic
KMP_DUPLICATE_LIB_OK=TRUE .venv-organic/bin/python -c "
from bench.fixtures import build_headline_store
from darwin_memo.organic import build_graph, AssociativeGraph
from darwin_memo.organic.associative import BruteForceBackend
from darwin_memo.organic.turbovec_backend import TurbovecBackend
from darwin_memo.retrieval import HashingEmbedder
store = build_headline_store(); ids=[e.id for e in store.alive()]
dim = len(HashingEmbedder()('probe'))
brute = build_graph(store)  # BruteForceBackend default
tv = AssociativeGraph(backend=TurbovecBackend(dim=dim))
for e in store.alive(): tv.add(e)
overlap=[]
for i in ids:
    b={rid for rid,_ in brute.related(i,3)}; t={rid for rid,_ in tv.related(i,3)}
    overlap.append(len(b & t)/max(1,len(b)))
print('mean top-3 id overlap brute vs turbovec:', round(sum(overlap)/len(overlap),2))
"
```
Expected: high mean overlap (turbovec is approximate; expect ~0.6–1.0 top-3 agreement). Record the number; it validates the optional backend tracks the exact one. If no wheel: note skipped.

- [ ] **Step 5: ruff + mypy + commit**

```bash
cd ~/darwin-memo-organic
.venv-organic/bin/python -m ruff check darwin_memo/organic/ && .venv-organic/bin/python -m ruff format --check darwin_memo/organic/
.venv-organic/bin/python -m mypy 2>&1 | tail -2
git add darwin_memo/organic/turbovec_backend.py pyproject.toml
git commit -m "feat(organic): optional turbovec ANN backend (import-guarded, brute-force fallback)"
```
Expected: ruff clean; mypy `Success`.

---

## Task 3: Docs + PR

**Files:** Create `docs/organic.md`; modify `README.md`, `CHANGELOG.md`.

- [ ] **Step 1: `docs/organic.md`** — a short operator page: what the organic layer is (the phased vision in one paragraph), Phase 1 status (associative graph), the `store_related(store, id, k)` API, the zero-dep default vs `pip install darwin-memo[organic]` turbovec backend, and the honest note that the `HashingEmbedder` default gives coarse relatedness (the `[embeddings]` extra is the quality path). Include the Task-2 agreement number if measured.

- [ ] **Step 2: README** — add a short "Organic memory (experimental, opt-in)" subsection pointing at `docs/organic.md` and the `darwin_memo.organic.store_related` entry point; state it is additive and judge-free (relatedness is mechanical cosine, value is still earned by the ledger).

- [ ] **Step 3: CHANGELOG** `[Unreleased] / Added` — bullet: opt-in `darwin_memo.organic` associative graph (Phase 1 of the organic-memory layer); zero-dep brute-force default + optional turbovec backend; read-only w.r.t. survival.

- [ ] **Step 4: Full lint + push + PR**

```bash
cd ~/darwin-memo-organic
.venv-organic/bin/python -m ruff check . && .venv-organic/bin/python -m ruff format --check .
.venv-organic/bin/python -m mypy 2>&1 | tail -2
git add docs/organic.md README.md CHANGELOG.md
git commit -m "docs: organic-memory layer (Phase 1: associative graph)"
git push -u origin feat/organic-memory
gh pr create --title "Organic memory Phase 1: associative graph (opt-in, turbovec backend)" --body "First phase of the organic/brain-like memory layer. Adds darwin_memo.organic.AssociativeGraph: one vector per memory, related(id, k) relevance-weighted neighbours. Zero-dep brute-force default; optional turbovec ANN backend behind the [organic] extra with a graceful fallback. Additive and read-only w.r.t. survival (never touches energy); relatedness is mechanical cosine, value still earned by the ledger. organic/ is omitted from the coverage gate (opt-in layer, turbovec path not in CI) — flagged for review. Spec: docs/superpowers/specs/2026-06-16-organic-memory-design.md.

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```
Expected: ruff clean, mypy `Success`, PR created.

- [ ] **Step 5: Confirm CI green** — `gh pr checks <PR#>`; lint + all test versions pass (coverage unaffected by organic via the `omit`).

---

## Self-review

**Spec coverage:** §4 additive optional layer → Tasks 1–2 (new `darwin_memo/organic/`, core untouched, coverage omit, organic extra); §5 Phase 1 (associative graph, pluggable embedder/backend, turbovec optional + zero-dep fallback, `store_related` surface, dual-backend agreement) → Task 1 (graph + brute + store_related) + Task 2 (turbovec + agreement); §3 no-judge (mechanical cosine, read-only on energy) → enforced in code + docs (Task 3); §6 testing/turbovec-mypy-override/docs → Tasks 1–3; §7 turbovec-wheel risk + HashingEmbedder-coarseness honesty → Task 2 Step 1 + Task 3 docs. Phases 2–4 are out of scope for this plan (separate plans, per the phased spec).

**Placeholder scan:** the only `<PR#>` is the new PR number (Task 3 Step 5) and the optional agreement number (filled if measured). No TBD/TODO; the no-wheel branch is an explicit handled case, not a gap.

**Type consistency:** `Embedder` = callable `(str)->list[float]` (matches `HashingEmbedder.__call__`); `Backend` protocol (`add`/`remove`/`search(vector,k,exclude)->list[(str,float)]`) is implemented identically by `BruteForceBackend` and `TurbovecBackend`; `AssociativeGraph.related(id,k)->list[(str,float)]`; `build_graph`/`store_related` signatures match their callers in the verification steps.
