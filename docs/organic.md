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
- **Phase 3 — spreading activation + Hebbian reweighting.** A recall spreads
  activation one hop to related memories and strengthens the links it
  traverses; unused links fade. The `OrganicMemory` facade ties the graph,
  activation, and learned weights into one adaptive object.
- **Phase 4 — earned importance + potentiation (this release, opt-in).**
  Recall frequency, earned credit and graph centrality accumulate into an
  importance score that biases ranking and, *if you wire it*, slows upkeep.
  This is the one part of the layer that can touch survival, and it is off
  unless you pass it in. Read [the warning](#potentiation-read-this-first).

Phases 1–3 are **additive and read-only with respect to survival** — they never
touch energy. Relatedness is mechanical cosine similarity; value is still
earned only by the survival ledger. Nothing here introduces a judge, in any
phase: importance is three measured quantities, not an opinion.

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

## Earned importance & potentiation (Phase 4)

Importance is three measured quantities, averaged and normalised against the
live population: how often a memory was **recalled**, how much outcome
**credit** it has earned above its spawn grant, and how **central** it is in
the associative graph. It biases retrieval ranking by default, and it can slow
upkeep if you hand it to the store.

```python
om = OrganicMemory(store)
om.recall("entry-a")

om.importance("entry-a")       # 0.0 - 1.0, recalls + credit + centrality
om.centrality()                # {id: mean effective relatedness}
store.charge_upkeep(scale=om.upkeep_scale())   # opt-in potentiation
```

`upkeep_scale()` returns a per-entry multiplier from `1.0` (unimportant, full
upkeep) down to `1 - MAX_RELIEF`. `MemoryStore.charge_upkeep` clamps whatever
it is given to `[MIN_UPKEEP_SCALE, 1.0]`, so a caller can slow an entry's burn
rate but never stop it or speed it up: **death stays an energy-floor event for
every unpinned entry**, it just takes up to four times as many ticks.

<a id="potentiation-read-this-first"></a>

### Potentiation: read this first

Potentiation makes usage a retention signal, and this project has already
measured that design losing. The `salience_matched` arm
(`bench/results/salience.json`, 10 seeds) selected victims by recency +
importance:

| arm | poison kill rate | mean cum_delta |
| --- | --- | --- |
| survival | 1.00 | +12,586,803 |
| random_matched | 0.80 | −7,673,651 |
| salience_matched | **0.20** | −2,756,505 |

Usage-importance killed poison in 2 runs of 10 — **worse than random
eviction** — because usage cannot distinguish "used" from "useful", so
consulted poison gets shielded. That arm is the stronger form (importance
picks the victim); Phase 4 is the gentler one (importance slows the burn, with
a floor). The difference is one of degree, not of kind.

So it is opt-in, and it is opt-in in the strong sense: `SurvivalLoop` and
`Ledger` charge flat upkeep exactly as they did before, no code in this
package calls `upkeep_scale()`, and `charge_upkeep()` with no `scale` is
byte-for-byte the old behaviour. If you wire it, measure your own store
against a flat-upkeep control before trusting it.

Ranking bias carries no such risk and is always on: it re-orders what surfaces,
never who survives.

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

- Only `organic/turbovec_backend.py` is excluded from the core coverage gate
  (its ANN path needs the optional extra); the zero-dep modules are covered
  like any other.
- This is an existence-grade substrate, not a tuned semantic-memory system; the
  hashing-embedder default is coarse by design, and the real-embedder extra is
  the quality path.
