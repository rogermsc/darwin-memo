# Organic memory (experimental, opt-in)

An adaptive, brain-like layer over darwin-memo. The full vision (see
`docs/superpowers/specs/2026-06-16-organic-memory-design.md`) is a memory that
weighs entries by usage/recurrence and *earned* importance, lets unused ones
**shrink** to a gist and **expand** back to full detail on recall, and connects
related memories with relevance-weighted links — all on earned/measured signals,
**no judge**. It is built in phases; this page documents what has landed.

## Status

- **Phase 1 — associative graph (this release).** One vector per memory and
  `related(id, k)` relevance-weighted neighbours.
- Phases 2–4 (activation + lossless gist↔detail surfacing, spreading
  activation + Hebbian reweighting, earned importance/potentiation) are
  specced but not yet implemented.

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
