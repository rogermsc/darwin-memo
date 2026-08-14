# Organic memory (experimental, opt-in)

An adaptive, brain-like layer over darwin-memo. The full vision (see
`docs/superpowers/specs/2026-06-16-organic-memory-design.md`) is a memory that
weighs entries by usage/recurrence and *earned* importance, lets unused ones
**shrink** to a gist and **expand** back to full detail on recall, and connects
related memories with relevance-weighted links — all on earned/measured signals,
**no judge**. It is built in phases; this page documents what has landed.

## Status

- **Phase 1 — associative graph.** One vector per memory and `related(id, k)`
  relevance-weighted neighbours.
- **Phase 2 — activation + lossless gist↔detail.** A recalled memory expands
  to full detail; an idle one shrinks to its gist.
- **Phase 3 — spreading activation + Hebbian reweighting (this release).** A
  recall spreads activation one hop to related memories and strengthens the
  links it traverses; unused links fade. The `OrganicMemory` facade ties the
  graph, activation, and learned weights into one adaptive object.
- Phase 4 (earned importance/potentiation) is specced but not yet implemented.

The layer is **additive and read-only with respect to survival** — it never
touches energy. Relatedness is mechanical cosine similarity; value is still
earned only by the survival ledger. Nothing here introduces a judge.

## Usage

```python
from darwin_memo import MemoryStore
from darwin_memo.organic import store_related, build_graph

# one-shot: related memories for one entry
related = store_related(store, entry_id, k=5)
# -> [(other_id, relevance_in_0_1), ...], highest first, self excluded

# reusable graph (build once, query many)
graph = build_graph(store)
graph.related(entry_id, k=5)
```

## Activation & surfacing (Phase 2)

A fast recall-salience signal that decides how much of a memory to show: a
recalled memory expands to full detail, an idle one shrinks to its gist. The
detail is always retained — surfacing only chooses what to show.

```python
from darwin_memo.organic import ActivationState, surface, detail

state = ActivationState()
surface(entry, state)      # cold -> gist (the question only)
state.bump(entry.id)       # recall raises activation to 1.0
surface(entry, state)      # hot  -> full detail (question + answer + sources)
state.decay()              # one idle cycle (x0.5); call per cycle
detail(entry)              # always the full detail (explicit "remind me")
```

Activation is in-memory and ephemeral (reset on load); `bump`/`decay` are
explicit calls you wire, like the survival loop. It gates *surfacing* only —
never survival — and never mutates the entry. Defaults: bump→1.0, decay ×0.5,
surface threshold 0.5.

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

## Backends

`AssociativeGraph(embedder=..., backend=...)` is pluggable:

- **Embedder** — default `darwin_memo.retrieval.HashingEmbedder` (zero-dep,
  deterministic). *Honest caveat:* a hashing embedder gives only **coarse**
  relatedness (relevances are low and approximate). For semantic quality, pass a
  real embedder (the `darwin-memo[embeddings]` extra, e.g. sentence-transformers).
- **Backend** — default `BruteForceBackend` (zero-dep, exact top-k cosine; fine
  at darwin-memo's demo scale). For scale, install `darwin-memo[organic]` and use
  the turbovec ANN backend:

```python
from darwin_memo.organic import AssociativeGraph
from darwin_memo.organic.turbovec_backend import TurbovecBackend
from darwin_memo.retrieval import HashingEmbedder

dim = len(HashingEmbedder()("probe"))
graph = AssociativeGraph(backend=TurbovecBackend(dim=dim))
```

turbovec quantizes vectors for memory-efficient ANN (10M vectors: 31GB → 4GB).
It is **optional**: if `darwin-memo[organic]` is not installed, use the
brute-force default. On a small store the two agree closely — measured **0.92
top-3 neighbour overlap** between the turbovec and exact backends. The turbovec
path requires `dim` to be a multiple of 8 (HashingEmbedder's 256 satisfies this).

## Scope and honesty

- The `organic/` package is excluded from the core coverage gate (it is opt-in
  and its ANN path does not run in default CI).
- This is an existence-grade substrate, not a tuned semantic-memory system; the
  hashing-embedder default is coarse by design, and the real-embedder extra is
  the quality path.
