# Paper-to-code map

This repo is a practical mix of two papers. This page maps every borrowed
concept to the code that implements it, and is explicit about where the
implementation deviates and why.

## MeMo: Memory as a Model (arXiv:2605.15156)

| Paper concept | Where it lives | Notes |
|---|---|---|
| Frozen Executive model, knowledge lives outside it | whole design; `darwin_memo/llm.py` | Clients use plain completion APIs. No weights, no logprobs, works with closed models. |
| Reflection QA synthesis, step 1: fact extraction (explicit + inferred) | `encode.py`, `_EXTRACTION_PROMPT` and `LocalEncoder.encode` | LLM mode prompts for both kinds. Local mode treats declarative sentences as explicit facts. |
| Step 2: consolidation of related facts | `encode.py` (LLM mode), `consolidate.py` (ongoing) | MeMo consolidates once at encoding time. Here consolidation also runs continuously as part of Negative-Space Learning. |
| Step 3: self-containment verification | `encode.py` prompts | Every question must be answerable with zero access to source documents. |
| Step 4: entity surfacing, both directions (reversal curse) | `encode.py`, entity QAs | Local mode surfaces capitalized entities; LLM mode prompts for attribute and relation QAs in both directions. |
| Step 5: cross-document synthesis (converging clues) | `encode.py`, `_CROSS_DOC_PROMPT`, `EntryKind.CROSS_DOC` | Local mode links entities that appear in two or more documents. |
| Three-stage query protocol: grounding, entity identification, answer seeking | `protocol.py`, `QueryProtocol` | LLM mode runs all three stages. Local mode degrades to scored retrieval with provenance. |
| Compact memory responses, constant in corpus size | `protocol.py` | Memory returns short QA snippets, never documents. |
| Parametric memory model trained with next-token loss | `training/train_memory_model.py` | The live store is structured, see deviations below. The training script distills survivors into a small LoRA model, conditioning on questions only. |
| Task-vector merging for continual learning | `training/train_memory_model.py` (LoRA per corpus) | One adapter per corpus is the practical analog. Merging adapters is left to the reader. |

## Survival is the Only Reward (arXiv:2601.12310)

| Paper concept | Where it lives | Notes |
|---|---|---|
| Behaviors selected by persistence, not by reward functions | `survival.py`, `SurvivalLoop` | Memory entries are the unit of selection. Energy is the survival currency. |
| The metric is a conserved physical resource, not a proxy | `environments.py`, `StorageEnv` | Real bytes in a real temp directory. Destroying protected data triggers a restore that costs three times the size, so the negative delta is also physical. |
| Procedurally regenerated environment per iteration | `StorageEnv.tasks` | A fresh directory tree every cycle, same topology, different instances. Nothing can overfit one filesystem. |
| Only positive-delta trajectories feed back into the system | `SurvivalLoop._write_experience` | The paper fine-tunes on surviving trajectories. The memory analog writes an experience entry that reinforces the deciding entry, and the write must then survive on its own. |
| Upkeep: existing costs something | `MemoryStore.charge_upkeep` | The paper's agents pay compute and storage to act at all. Entries pay energy per cycle. |
| Negative-Space Learning: consolidation and pruning over invention | `consolidate.py` | Similar survivors merge, energy pools, dead entries are buried. Improvement shows up as reallocation of energy mass, observable via `MemoryStore.energy_share_by_kind`. |
| Reward hacking is evolutionarily unstable | `survival.py` docstring, demo | There is nothing to hack. An entry only earns by producing outcomes that persist, at which point it is simply useful. |
| Credit assignment along provenance | `SurvivalLoop._assign_credit` | The deciding entry takes full credit, supporting entries a configurable share, scaled by tanh of the normalized delta. |

## Honest deviations

1. **The live memory is a structured store, not model weights.** MeMo's
   central artifact is a small fine-tuned LLM. A structured store keeps the
   core dependency-free and lets selection operate on individual entries,
   which is what the survival mechanics need. The distillation script in
   `training/` closes the loop for anyone who wants the parametric form.
2. **Local retrieval is lexical.** Smoothed IDF overlap with a relevance
   floor (`MemoryStore.retrieve`). Good enough to demonstrate the
   mechanics offline. Swap in embeddings if you need semantic recall.
3. **The paper's agents propose executable code.** Here the proposal is an
   answer plus a binary action read from it (`decision_polarity`). Same
   selection geometry, far smaller attack surface.
4. **VerifiableQAEnv verifies by exact containment.** Weaker grounding than
   bytes on disk, but still a measurement, never a model's judgment.
