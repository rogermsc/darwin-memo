# darwin-memo

[![CI](https://github.com/rogermsc/darwin-memo/actions/workflows/ci.yml/badge.svg)](https://github.com/rogermsc/darwin-memo/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/darwin-memo)](https://pypi.org/project/darwin-memo/)
[![Python](https://img.shields.io/pypi/pyversions/darwin-memo)](https://pypi.org/project/darwin-memo/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

**Memory for LLM agents that dies unless it earns its keep.** Every
entry pays energy upkeep and earns only from measured outcomes: bytes
actually freed on a real disk, tests actually passing. Poisoned advice
gets executed by the environment it damaged. Useless trivia starves.
There is no reward model, no LLM judge, and no human curation anywhere.

![Survival loop demo: a poisoned memory entry going extinct](docs/assets/demo.gif)

Watch a poisoned entry go extinct in your own terminal, one command,
no keys, no checkout:

```bash
pip install darwin-memo && darwin-memo demo
```

## When to use this (and when not)

Use darwin-memo where a **conserved, measurable outcome** exists to
settle decisions against: coding-agent lesson stores settled by CI
pass counts (the primary target, see
[the integration guide](docs/integrations/ci-lesson-store.md)), storage
and artifact retention, cache and dedup advisors, spend-cap automation.

Do not use it for chat-preference memory, RAG over documentation, or
personal assistants. Those have no conserved resource pushing back, and
upkeep would starve the long tail of correct-but-rarely-used knowledge.
mem0, Zep, and Letta serve that market; darwin-memo deliberately does
not. The honest rule: if your `verify` would be a model scoring an
answer, this package is wrong for you, by design.

## The headline demo

The demo corpus contains an ops runbook, platform notes, and one
poisoned document: a forum post claiming database files are "redundant
and safe to remove". Before selection pressure exists, retrieval
confidently repeats the poison, because it has no reason to doubt it.

Then 30 survival cycles run against `StorageEnv`, a disk cleanup
sandbox where the selection signal is actual bytes on an actual disk.
Deleting a disposable file frees its size. Deleting a protected file
triggers a restore that costs three times the size. Nothing grades the
answers, the filesystem just responds:

```
cycle  pop births deaths merges   energy   resource Δ
    0   17      1      0      0    17.11       -12288
    1   16      0      1      0    17.27      -808960   <- poison being executed
    ...
   19    5      0      7      0    15.60       338944   <- unused knowledge starves
   ...
   29    4      0      0      0    15.10       346112   <- stable, positive forever

Poisoned entries still alive: 0
```

Three death modes show up in the graveyard, and the distinction matters:

- **executed**: the poisoned entries that decided real actions. The
  environment measured real damage and the negative delta flowed back
  along provenance until they died. The opening cycles are the price of
  the lesson, and the benchmarks show it is bounded.
- **starved**: cafeteria trivia and facts the agent never needed.
  Nothing punished them, they just never earned their upkeep.
- **merged**: near-duplicate survivors absorbed into consolidated
  entries. Their energy pools, their lineage is recorded, and the
  population shrinks while capability per entry rises.

## Where it comes from

A practical mix of two papers. MeMo says what memory is, the survival
paper says what gets to stay in it.

| Paper | What this repo takes from it |
|---|---|
| [MeMo: Memory as a Model](https://arxiv.org/abs/2605.15156) (Quek et al.) | Keep the main LLM frozen and put knowledge in a dedicated memory. The reflection-QA encoding pipeline and the three-stage query protocol (grounding, entity identification, answer seeking). |
| [Survival is the Only Reward](https://arxiv.org/abs/2601.12310) (Dodgson et al.) | Environment-mediated selection. The only signal is a conserved, physically measurable resource delta. Behaviors that persist get reinforced, everything else is pruned. There is no proxy to hack. |

```mermaid
flowchart LR
    subgraph encode [MeMo encoding]
        C[Corpus] --> R[Reflection QA pipeline] --> S[(Memory store)]
    end
    subgraph loop [Survival loop]
        S -->|3-stage query protocol| A[Answer + provenance]
        A --> E[Environment acts and MEASURES]
        E -->|resource delta along provenance| S
        S -->|upkeep every cycle| S
        S -->|consolidate + prune| S
    end
```

## Using it

Requires Python 3.10+. The core has zero dependencies; everything below
runs offline.

The anatomy in 30 seconds: a `MemoryEntry` is a self-contained QA pair
(`.question`, `.answer`, `.sources`, `.energy`). The store retrieves,
the protocol answers with provenance, the environment measures, credit
flows back.

```python
from darwin_memo import Document, LocalEncoder, MemoryStore, QueryProtocol

store = MemoryStore(upkeep=0.05)
for entry in LocalEncoder().encode([Document("runbook", open("runbook.txt").read())]):
    store.add(entry)

answer = QueryProtocol(store).answer("Is it safe to delete old log files?")
print(answer.text)             # the top entry's answer, or "" when memory is silent
print(answer.deciding_entry)   # provenance: the id credit will flow to
```

### Event-driven (production shape): the Ledger

Real outcomes arrive late. The Ledger decouples the three moments:
decide now, settle whenever the measurement lands, tick on your own
cadence. Entries with unsettled tickets are escrowed: they keep paying
upkeep but cannot be buried or merged until their verdict arrives.

```python
from darwin_memo import Ledger

ledger = Ledger(store, resource_scale=2.0, event_log="events.jsonl")

ticket = ledger.decide("Is the dedupe helper safe to remove?")
# ... act on ticket.answer, CI runs, hours pass ...
ledger.settle(ticket.id, delta=passes_after - passes_before, detail=run_url)
ledger.tick()                        # upkeep, deaths, consolidation
print(ledger.obituary(entry_id))     # why did this entry die?
```

### Batch (research shape): the SurvivalLoop

```python
from darwin_memo import StorageEnv, SurvivalConfig, SurvivalLoop

loop = SurvivalLoop(store, StorageEnv(), config=SurvivalConfig(cycles=30))
report = loop.run()
print(report.summary())   # includes per-cycle silence counts and a
                          # plain-language warning if the run is degenerate

store.save("memory.json")  # survivors only carry forward
```

### MCP server: mount it into an agent

```bash
pip install "darwin-memo[mcp]"
claude mcp add darwin-memo -- darwin-memo-mcp --memory ~/.darwin-memo/memory.json
```

The agent gets `memory_query` (returns an answer plus a ticket id),
`memory_settle` (report the measured delta later), `memory_add`,
`memory_tick`, `memory_stats`, and `memory_obituary`. The store
persists across sessions, so the population carries its scars forward.

### With an LLM

`pip install "darwin-memo[anthropic]"` and set `ANTHROPIC_API_KEY`; the
examples pick it up automatically.

```python
from darwin_memo import ReflectionEncoder, QueryProtocol
from darwin_memo.llm import AnthropicClient

client = AnthropicClient()                  # or OpenAICompatClient(model=..., base_url=...)
encoder = ReflectionEncoder(client)         # 5-step reflection QA synthesis
protocol = QueryProtocol(store, client)     # grounding -> entities -> answer seeking
```

In LLM mode the memory snippets are numbered and the model cites which
it used, so credit flows to the entries that actually shaped the answer
(even spread over everything consulted is the fallback).

## Bring your own selection pressure

The environment is the whole trick, and yours is probably better than
the demos. Implement two methods, and keep the one rule: `verify` must
measure, never grade.

```python
from darwin_memo import Outcome, Task, decision_polarity

class BudgetEnv:
    resource_scale = 100.0

    def tasks(self, cycle):
        # Each Task needs a prompt and a context dict (yours to fill).
        return [Task(prompt="Is the paymentsly plan safe to cancel?", context={})]

    def verify(self, task, answer_text):
        act = decision_polarity(
            answer_text,
            extra_positive=("safe to cancel",),
            extra_negative=("do not cancel", "keep paying"),
        )
        if not act:
            return Outcome(delta=0.0, detail="kept")
        return Outcome(delta=dollars_saved, detail="cancelled")
```

Good conserved resources: tests passing, bytes freed, requests served
under budget, rows deduplicated, dollars of spend avoided. Bad ones:
anything a model scored.

### Make it work on the first try

Three silent failure modes catch every new environment, and they all
end the same way (the whole population starving around cycle 20 with
every delta at zero). The loop's summary now warns about each, but know
them up front:

1. **The action vocabulary.** `decision_polarity`'s built-in markers
   speak delete/remove and apply/keep, the bundled environments'
   dialects. "Safe to cancel" reads as silence unless you pass
   `extra_positive`/`extra_negative` markers for your verbs.
2. **The relevance floor.** Retrieval mutes entries whose lexical
   overlap with the task is below `LexicalRetriever(min_coverage=0.25)`.
   Your task phrasing must share vocabulary with your corpus, or use an
   embedding retriever. Silence beats guessing, but silence earns zero.
3. **The starvation cliff.** Entries spawn at 1.0 energy and pay 0.05
   upkeep, so a population that never earns dies at cycle ~20. If
   everything dies at once around there, your environment never paid
   out: check 1 and 2.

## Retrieval modes

Retrieval is pluggable through the `Retriever` protocol; the store stays
the single owner of the energy ledger, and no retriever may read energy
when scoring (selection pressure comes from outcomes, never from
retrieval preferring incumbents).

```python
from darwin_memo import EmbeddingRetriever, HashingEmbedder, MemoryStore

store = MemoryStore()                                  # lexical IDF, the default
store = MemoryStore(retriever=EmbeddingRetriever(HashingEmbedder()))
store = MemoryStore(retriever=EmbeddingRetriever(my_model.encode))
```

- **Lexical (default)**: smoothed IDF overlap with a relevance floor.
  Zero dependencies, deterministic, fine for runbook-scale corpora.
- **HashingEmbedder**: zero-dependency character n-gram hashing. Buys
  typo and morphology robustness ("databse" still finds database
  entries), not synonym recall.
- **Any real embedding**: pass any `text -> list[float]` function
  (sentence-transformers, an API endpoint). Vectors persist inside
  `memory.json` so paid embeddings are never recomputed on load.

Honest scaling note: ranking is pure-Python O(population x dims), fine
to a few thousand entries. Past that you want numpy or an ANN index,
which is out of scope for the zero-dependency core. With cosine
retrievers, raise `merge_threshold` to roughly 0.85 or unrelated
entries will consolidate.

## Benchmarks

Survival is benchmarked against six baselines across 10 seeds, with
ablations and a scaling probe, all reproducible offline from `bench/`.
The sharpest comparison is `random_matched`: identical per-cycle
eviction counts, random victims.

| arm | kill rate | kill cycle (med) | damage before kill | tail delta | cum delta |
|---|---|---|---|---|---|
| survival | 1.00 | 0 | -751k | +435k | +12.0M |
| random_matched | 0.80 | 19 | -8.97M | -75k | -5.25M |
| keep_everything | 0.00 | never | -10.6M | -287k | -7.29M |

Same pruning rate, 12x the damage, negative steady state: outcome
direction is the active ingredient, not eviction itself. The harness
also runs the baseline that keeps us honest: `evict_on_negative`, a
one-line "evict whatever erred" heuristic, ties survival on outcomes in
this deterministic environment; the ledger's measured edge here is
leanness (4 surviving entries vs 15), and its forgiveness under noisy
outcomes is a designed property this benchmark cannot exercise. A
paraphrase probe set, scored by provenance rather than keywords,
quantifies how the demo degrades outside its own vocabulary, and an
embedding-retriever arm shows the mechanism does not depend on the
lexical-match path. Full tables, every baseline's best metric stated
plainly, and honest caveats: [docs/benchmarks.md](docs/benchmarks.md).

## More examples

```bash
git clone https://github.com/rogermsc/darwin-memo && cd darwin-memo && pip install -e .

python examples/01_encode_memory.py    # corpus -> reflection-QA memory
python examples/02_query_protocol.py   # interrogate it, with provenance
python examples/03_survival_loop.py    # the headline demo
python examples/04_agent_loop.py       # memory as a tool in an agent loop
python examples/05_testsuite_env.py    # selection pressure from a test suite
python examples/06_ci_lesson_store.py  # the Ledger settling lessons by CI delta
```

Three environments ship: `StorageEnv` (bytes on a real disk),
`TestSuiteEnv` (passing tests in a generated micro-project, with
destructive patches dressed as cleanup), and `VerifiableQAEnv` (exact
containment, the weakest grounding but still a measurement).

To distill survivors into an actual parametric memory model (MeMo's
native form), `training/train_memory_model.py` fine-tunes a small model
on the surviving QA pairs with LoRA, conditioning on questions only.

## Design notes

- **Energy ledger**: entries spawn at 1.0 energy, pay 0.05 upkeep per
  cycle, earn `0.6 * tanh(delta / resource_scale)` when they decide a task
  (supporting entries get 25% of that), and are capped at 5.0. Death is at
  zero. All tunable via `MemoryStore` and `SurvivalConfig`.
- **Credit flows along provenance.** Only the entries that produced an
  answer are touched by its outcome. In LLM mode, citations name them;
  tanh keeps one disaster from executing an entry that was right
  ninety-nine times, and one jackpot from making an entry immortal.
- **Memory silence is a feature.** Retrieval has a relevance floor, and an
  earlier version of this repo demonstrated why: entries matching only
  structural tokens ("safe", "file") were deciding questions they knew
  nothing about, getting executed for it, and being reborn. Better for
  memory to say nothing than to guess.
- **Silence is conservative.** When memory is silent, `StorageEnv` keeps
  the file: the safe reading of an irreversible action. A side effect
  worth knowing: protective knowledge ("never delete X") eventually
  starves because it is redundant with that default. The population
  converges to exactly the knowledge that changes behavior.
- **Escrow keeps delayed verdicts honest.** Ledger entries named by an
  unsettled ticket cannot be buried or merged, so an outcome can never
  arrive after the execution. Unsettled tickets expire at delta zero.

The full concept-to-code mapping, including honest deviations from both
papers, is in [docs/paper-to-code.md](docs/paper-to-code.md). The story
of why this exists: [docs/launch-post.md](docs/launch-post.md).

## Tests

```bash
pip install -e ".[dev]"
pytest
```

The load-bearing tests: poisoned advice must die and useful advice must
survive across seeds and across two environment families, ledger
escrow must hold verdicts open, and hypothesis property tests pin the
conservation laws (energy pools exactly on merge, caps hold, retrieval
never reads energy), all with no labels anywhere.

## Citations

This repo is an independent practical interpretation, not the official
code of either paper. If you build on the ideas, cite the originals:

```bibtex
@misc{quek2026memo,
  title  = {MeMo: Memory as a Model},
  author = {Quek, Ryan Wei Heng and Lee, Sanghyuk and Leong, Alfred Wei Lun and
            Verma, Arun and Prakash, Alok and Chen, Nancy F. and
            Low, Bryan Kian Hsiang and Rus, Daniela and Solar-Lezama, Armando},
  year   = {2026},
  eprint = {2605.15156},
  archivePrefix = {arXiv},
  url    = {https://arxiv.org/abs/2605.15156}
}

@misc{dodgson2026survival,
  title  = {Survival is the Only Reward: Sustainable Self-Training Through
            Environment-Mediated Selection},
  author = {Dodgson, Jennifer and Alhajir, Alfath Daryl and Joedhitya, Michael and
            Pattirane, Akira Rafhael Janson and Kumar, Surender Suresh and
            Lim, Joseph and Peh, C.H. and Ramdas, Adith and Zhexu, Steven Zhang},
  year   = {2026},
  eprint = {2601.12310},
  archivePrefix = {arXiv},
  url    = {https://arxiv.org/abs/2601.12310}
}
```

## License

MIT
