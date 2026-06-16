# Organic memory — Phase 3 (spreading activation + Hebbian reweighting) — design spec

- **Date:** 2026-06-16
- **Branch / worktree:** `feat/organic-memory-phase3` (`~/darwin-memo-organic`), stacked on `feat/organic-memory-phase2` (Phase 2, PR #34) → on Phase 1 (PR #33)
- **Status:** approved design, pre-implementation
- **Parent spec:** `docs/superpowers/specs/2026-06-16-organic-memory-design.md` (§5 Phase 3)

## 1. Goal

Make the memory *move*: a recall **spreads** activation to related memories (so a
reminder "starts to remind details" of connected ones), and co-recalled links
**strengthen** (Hebbian) while unused ones fade — an adaptive associative graph
layered on the innate cosine relatedness. On-thesis: organic-only, in-memory,
explicit, no judge, core untouched.

## 2. Decided design

- **Hebbian combine rule:** `effective_relevance(a, b) = clamp01(cosine(a, b) +
  learned(a, b))`. Cosine (Phase 1) is the innate prior; `learned` starts at 0,
  increments on co-recall, and decays globally so unused associations fade.
- **Two timescales (again):** activation decays fast (×0.5, short-term salience);
  Hebbian weights decay slow (×0.9, long-term association).
- **Additive:** Phase 1 `AssociativeGraph.related()` stays **pure cosine**;
  Phase 3 overlays the learned weights in a new effective-related path. Phases
  1–2 modules are unchanged.

## 3. Components (`darwin_memo/organic/dynamics.py`, new)

- **`HebbianWeights`** — symmetric learned co-recall strengths:
  - storage `dict[frozenset[str], float]` (key = `frozenset({a, b})`).
  - `strengthen(a, b, by: float = HEBB_INCREMENT) -> None` — add `by`, clamp to
    1.0; ignore `a == b`.
  - `decay(factor: float = HEBB_DECAY) -> None` — scale all; prune below epsilon.
  - `weight(a, b) -> float` — default 0.0.
  - `neighbors(entry_id) -> dict[str, float]` — learned-linked ids → weight.
- **`OrganicMemory`** — the facade tying Phase 1 graph + Phase 2 activation +
  Phase 3 weights into one adaptive object:
  - `__init__(store, embedder=None, backend=None)` — builds an `AssociativeGraph`
    over the store's living entries, a fresh `ActivationState`, a fresh
    `HebbianWeights`.
  - `related(entry_id, k: int = 5) -> list[tuple[str, float]]` — effective
    relatedness: take the cosine top-`2k` from the graph plus any purely-learned
    neighbours (treated as cosine 0), compute `clamp01(cosine + learned)`,
    re-rank, return top-`k`.
  - `recall(entry_id, k: int = 5, spread: float = SPREAD_FACTOR) -> None` — the
    reminder: `state.bump(entry_id)`; for each `(nbr, eff)` in
    `related(entry_id, k)`: `state.bump(nbr, to=spread * eff)` and
    `hebbian.strengthen(entry_id, nbr)`. One hop.
  - `decay() -> None` — `state.decay()` (×0.5) then `hebbian.decay()` (×0.9).
  - `surface(entry) -> str` — delegates to Phase 2 `surface(entry, self.state)`.
  - exposes `.graph`, `.state`, `.hebbian` for inspection.

Constants (module-level, overridable): `SPREAD_FACTOR = 0.5`,
`HEBB_INCREMENT = 0.25`, `HEBB_DECAY = 0.9`, `_PRUNE_EPSILON = 1e-3`.

## 4. Behavior (the loop)

1. `recall(X)` → X hot (1.0); its top-k related neighbours get a fraction of
   activation (so `surface(nbr)` expands toward detail — connected details
   surface); each (X, nbr) link strengthens.
2. Recall X and Y together over time → `learned(X, Y)` grows → `related(X)` ranks
   Y higher even if cosine is modest (usage shapes the graph).
3. `decay()` each cycle → activation fades fast, learned links fade slow; links
   never co-recalled erode back toward pure cosine.

## 5. Principles & invariants

- **Core untouched, no new deps, no judge.** Cosine + Hebbian are mechanical;
  value is still earned only by the survival ledger.
- **Activation and learned weights gate *surfacing/ranking*, never *survival*.**
  No code path from this module to energy — stated as an invariant.
- `related()` here is the *effective* (Hebbian-overlaid) view; Phase 1's
  `AssociativeGraph.related()` remains the pure-cosine primitive.
- Stays in `darwin_memo/organic/` (omitted from the coverage gate); mypy-clean.

## 6. Out of scope (Phase 4)

- Earned importance / potentiation that slows upkeep. Multi-hop spreading,
  persistence, and richer decay schedules are deferred (YAGNI at this scale).

## 7. Testing, docs

- No TDD / no pytest run (standing preference). Verify by running: `recall(X)`
  raises neighbours' activation and `surface(nbr)` flips toward detail; repeated
  co-recall of (X, Y) raises `learned(X, Y)` and lifts Y in `related(X)`;
  `decay()` lowers both. `ruff`/`mypy` clean.
- Docs: extend `docs/organic.md` (mark Phase 3 done + `OrganicMemory` facade
  usage), CHANGELOG.

## 8. Build sequence (detail in writing-plans)

1. `dynamics.py` (`HebbianWeights` + `OrganicMemory`); export from
   `organic/__init__.py`; verify spreading + Hebbian + decay loop; ruff/mypy.
2. Docs (`docs/organic.md` + CHANGELOG); ruff/mypy; PR (base
   `feat/organic-memory-phase2`; retarget up the stack as parents merge).
