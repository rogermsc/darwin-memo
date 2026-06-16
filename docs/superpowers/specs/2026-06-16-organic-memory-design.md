# Organic memory: an adaptive, brain-like layer for darwin-memo — phased design spec

- **Date:** 2026-06-16
- **Branch / worktree:** `feat/organic-memory` (`~/darwin-memo-organic`), off `main`
- **Status:** approved architecture, phased; Phase 1 to be planned next
- **External dep:** [turbovec](https://github.com/RyanCodrai/turbovec) (Rust ANN, TurboQuant quantization, Python bindings) — **optional extra**, zero-dep fallback always available

## 1. Vision

Make darwin-memo's memory *organic and adaptive*, like the brain: memories are
weighted by usage/recurrence and (earned) importance; unused ones **shrink**
(surface only a gist) rather than dying outright; a **reminder expands** a memory
back to full detail and lights up **related** memories; memories are connected
with **relevance-weighted** links that adapt with co-recall. A moving,
self-organizing memory — built **entirely on earned/measured signals, no judge**,
preserving darwin-memo's identity.

## 2. The model (two timescales + lossless detail + association)

darwin-memo today conflates "recently/usefully used" into one slow **energy**
signal. The organic layer separates the timescales and adds association:

- **Energy (slow — exists, unchanged).** Survival currency: earned from measured
  conserved-resource outcomes, drained by upkeep, death at zero. Long-term
  retention. The organic layer never bypasses or fakes it.
- **Activation (fast — new).** A recall-salience float in `[0, 1]` that **spikes
  on recall and decays each cycle**. Controls *surfacing*, not survival. This is
  the "moving" part.
- **Lossless gist↔detail.** Every `MemoryEntry` already has a **gist** (its
  `question`) and **detail** (`answer` + `sources`). Detail is **always
  retained**. Low activation → retrieval surfaces only the **gist**; recall
  raises activation → the entry **expands** to full detail. "Shrink when unused"
  = activation decays to gist-only. "Expand on reminder" = recall re-surfaces the
  retained detail. **No summarizer; nothing is discarded.**
- **Earned importance (new — slow).** Accumulates purely from measured signals:
  recall frequency, outcome contribution (credit the entry already earns), and
  **associative centrality** (degree/strength in the graph). It **slows upkeep
  decay** for important memories (long-term potentiation) and biases ranking.
  Never assigned by a model or human heuristic (explicit pinning already exists
  for the human-override case).
- **Associative graph (new — turbovec).** One embedding vector per memory;
  relevance-weighted links to related memories. On recall, **spreading
  activation** flows along links (weighted by relevance) so a reminder *"starts
  to remind details" of connected memories*. Links **strengthen Hebbianly** when
  two memories are co-recalled.

## 3. No-judge stance (decided: strict on-thesis)

- Gist↔detail is **lossless de-activation**, never lossy LLM summarization.
- Importance is **earned** (recall freq + outcome + centrality), never assigned.
- The associative graph uses **embeddings + similarity** (mechanical), not a
  model's opinion of relatedness.
- turbovec is an **optional extra**; the layer must work (at small scale) with a
  zero-dep fallback. `pip install darwin-memo` stays dependency-free.
- Nothing here weakens the survival ledger; energy remains the only thing that
  decides life and death.

## 4. Architecture — additive optional layer

The zero-dep `MemoryStore` and `SurvivalLoop` are **not rewritten**. Organic
behavior is an opt-in layer alongside them (the pattern already used by the
embedding retriever and `temporal.py`):

- New module(s) under `darwin_memo/organic/` (or `darwin_memo/organic.py` if it
  stays small): the associative graph, the activation/surfacing logic, the
  earned-importance accumulator.
- New optional extra in `pyproject.toml`: `darwin-memo[organic]` pulling
  `turbovec` (and reusing the existing embedding extra where relevant). Imports
  are lazy; absence falls back to the zero-dep path.
- `MemoryEntry` gains one new field, `activation: float = 0.0` (serialized
  backward-compatibly, like the trust-lifecycle fields already added — missing →
  default). Earned-importance components are derived from existing fields
  (`uses`, credit history) plus graph centrality, so no schema bloat.
- Per the minimal-design preference: each phase adds the **smallest** thing that
  works; no pre-building for hypothetical scale.

## 5. Phases (one spec, sequenced; Phase 1 planned first)

### Phase 1 — Associative graph (turbovec)  ← plan this next
A vector per memory and relevance-weighted "related memories", as the substrate
everything else uses.
- **`AssociativeGraph`** (new): `add(entry)` embeds + indexes; `related(entry_id,
  k) -> list[(other_id, relevance)]` where relevance is cosine similarity in
  `[0, 1]`; `remove(entry_id)`; serialization alongside the store.
- **Embedder** (pluggable): zero-dep default = the existing `HashingEmbedder`;
  optional = a real embedder via the embedding extra.
- **Backend** (pluggable): zero-dep default = brute-force top-k cosine (fine for
  the demo-scale stores darwin-memo targets); optional = **turbovec
  `IdMapIndex`** (stable external ids = memory ids) for scale, behind
  `[organic]`. Same `related()` contract either way; a test asserts both backends
  agree on small inputs.
- **Integration:** the graph is built from a store's living entries and kept in
  sync on add/bury (and union on consolidation). It is read-only w.r.t.
  survival — it never changes energy in Phase 1.
- **Deliverable:** `store_related(store, entry_id, k)` usable from the CLI/MCP as
  a "related memories" surface; opt-in, documented; zero-dep path covered.

### Phase 2 — Activation + gist↔detail surfacing
- Add `activation` to `MemoryEntry`; `bump_activation(id)` on recall (spike to
  1.0), `decay_activation()` per cycle (multiplicative, e.g. ×0.5).
- Retrieval/`QueryProtocol` returns **gist by default**, **detail when activation
  ≥ threshold** (or when explicitly expanded). A new `expand(id)` surface forces
  detail. Lossless: detail is always present, just gated by activation.

### Phase 3 — Spreading activation + Hebbian reweighting
- On recall of X, propagate a fraction of activation to `related(X, k)` weighted
  by relevance (one hop, capped), so reminders surface connected details.
- Co-recalled pairs **strengthen** their link (Hebbian increment, decayed
  otherwise) — the graph becomes adaptive, not static cosine.

### Phase 4 — Earned importance & potentiation
- Accumulate `earned_importance` from recall frequency + outcome credit +
  associative centrality (all measured).
- Importance **slows upkeep** (potentiation: important memories resist shrinking)
  and biases retrieval ranking. Still earned, still no judge; death remains an
  energy-floor event.

## 6. Testing, docs, compute

- Per the standing preference: no TDD, no pytest run/report; verify by running.
  (One exception worth keeping: the dual-backend agreement check in Phase 1 — a
  small determinism assertion, run once, since it guards a real correctness
  property.)
- `ruff`/`mypy` clean; turbovec added to the mypy `ignore_missing_imports`
  override (like the ML deps) since it ships no stubs.
- Docs: a `docs/organic.md` operator page + README section per phase; CHANGELOG.
- Local dev only; turbovec installs via `pip install turbovec` (wheels) — confirm
  it imports in the venv before Phase 1 implementation; if no wheel for the local
  Python, the zero-dep fallback path is what we build/verify first.

## 7. Open risks (pre-registered)
- **turbovec wheel availability** for the local Python (3.13): verify at Phase 1
  start; the brute-force fallback de-risks this (turbovec becomes a scale
  optimization, not a hard dependency).
- **HashingEmbedder relevance quality**: a hashing embedder gives weak semantic
  relatedness; the zero-dep path may produce coarse links. Acceptable for the
  substrate; the real-embedder extra is the quality path. Phase 1 reports this
  honestly rather than overclaiming semantic association on the hashing default.
- **Activation vs energy interaction** (Phase 2+): activation must not become a
  back-door that keeps dead weight alive; it gates *surfacing*, never *survival*.
  Stated as an invariant.

## 8. Build sequence
1. Phase 1 → its own implementation plan (next, via writing-plans) → PR.
2. Phases 2–4 each get their own plan/PR after the prior lands, re-using what
   Phase 1 establishes. Re-evaluate scope after Phase 1 (learn-then-extend).
