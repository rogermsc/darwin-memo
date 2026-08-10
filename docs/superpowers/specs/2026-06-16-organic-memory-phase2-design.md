# Organic memory — Phase 2 (activation + lossless gist↔detail) — design spec

- **Date:** 2026-06-16
- **Branch / worktree:** `feat/organic-memory-phase2` (`~/darwin-memo-organic`), stacked on `feat/organic-memory` (Phase 1, PR #33)
- **Status:** approved design, pre-implementation
- **Parent spec:** `docs/superpowers/specs/2026-06-16-organic-memory-design.md` (§5 Phase 2)

## 1. Goal

Add the **fast recall-salience signal (activation)** and **lossless
gist↔detail surfacing** to the organic layer: a memory recalled recently
surfaces its full detail and **expands**; one left idle **shrinks** to its gist
(question only). Detail is never discarded — surfacing only chooses what to show.
On-thesis: organic-only, in-memory, explicit, no judge, core untouched.

## 2. Decided design

- **Activation lives in the organic layer, in-memory** (not on core
  `MemoryEntry`). The darwin-memo core, types, store, and serialization are
  **untouched**. Activation is fast-decaying and ephemeral, so in-memory (reset
  on load) is the natural, minimal choice; it also keeps the core dependency-free
  and out of the coverage gate. (This refines the parent spec's sketch, which
  had floated an `activation` field on `MemoryEntry`.)
- Recall and decay are **explicit** calls the consumer wires (exactly like the
  survival loop is wired) — the core never auto-hooks into retrieval.
- Surfacing is **lossless**: the `MemoryEntry` is never mutated; `surface()`
  returns either the gist or the retained detail based on activation.

## 3. Components (`darwin_memo/organic/activation.py`, new)

- **`ActivationState`** — wraps an in-memory `dict[str, float]` of id → activation
  in `[0, 1]`:
  - `bump(entry_id: str, to: float = 1.0) -> None` — recall raises the entry's
    activation to `to` (max of current and `to`).
  - `decay(factor: float = 0.5) -> None` — multiply every activation by
    `factor`; delete entries that fall below a small epsilon (1e-3) to keep the
    dict from growing unbounded.
  - `level(entry_id: str) -> float` — current activation, default `0.0`.
- **Surfacing functions:**
  - `GIST` vs `DETAIL`: the gist is `entry.question`; the detail is
    `entry.question` + `entry.answer` + (if any) a `sources` line.
  - `detail(entry) -> str` — always the full detail (the explicit "remind me
    the details" surface; also reusable by `surface`).
  - `surface(entry, state, threshold: float = 0.5) -> str` — returns the gist
    when `state.level(entry.id) < threshold`, else `detail(entry)`. Pure read;
    no mutation of entry or state.

Constants (module-level, overridable per call): bump-to `1.0`, decay factor
`0.5`, surface threshold `0.5`, prune epsilon `1e-3`.

## 4. Behavior (the loop it enables)

1. Consumer recalls memory X (e.g. it was retrieved/used) → `state.bump(X.id)`.
2. `surface(X, state)` now returns full **detail** (activation 1.0 ≥ 0.5).
3. Each cycle with no recall of X → `state.decay()`; after ~1 tick activation
   0.5, after 2 ticks 0.25 (< threshold) → `surface(X, state)` returns just the
   **gist**. The detail is still in X, retained losslessly.
4. `detail(X)` always returns the full text regardless of activation (explicit
   expand).

## 5. Principles & invariants

- **Core untouched, no new deps, no judge.** activation is mechanical; value is
  still earned only by the survival ledger; surfacing is mechanical thresholding.
- **Activation gates *surfacing*, never *survival*.** It must never feed back
  into energy or keep a dead entry alive — stated as an invariant; Phase 2 has no
  code path from activation to the ledger.
- Stays in `darwin_memo/organic/` (already omitted from the coverage gate);
  mypy-clean (organic is in mypy scope).

## 6. Out of scope (later phases)

- Spreading activation to *related* memories on recall (uses Phase 1's graph) —
  **Phase 3**.
- Earned importance / potentiation that slows upkeep — **Phase 4**.
- Persisting activation across restarts (sidecar) — deferred; ephemeral by
  design at this scale.

## 7. Testing, docs

- No TDD / no pytest run (standing preference). Verify by running: a script that
  bumps → `surface` returns detail; decays twice → `surface` returns gist;
  `detail()` always returns full text. `ruff`/`mypy` clean.
- Docs: extend `docs/organic.md` with the activation/surfacing API and the
  shrink/expand behavior; mark Phase 2 done; CHANGELOG bullet.

## 8. Build sequence (detail in writing-plans)

1. `activation.py` (`ActivationState` + `detail`/`surface`); export from
   `organic/__init__.py`; verify the bump→detail / decay→gist loop; ruff/mypy.
2. Docs (`docs/organic.md` + CHANGELOG); ruff/mypy; PR (base
   `feat/organic-memory`; retarget to `main` once #33 merges).
