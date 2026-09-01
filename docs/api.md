# API reference

The public surface of darwin-memo 0.6.0: everything importable from
the top-level `darwin_memo` package (its `__all__`), the
`darwin-memo` CLI, and the MCP server tools. Signatures below are
copied from the code; when this page and the code disagree, the code
wins and the page has a bug.

The core has zero runtime dependencies. Optional extras:
`darwin-memo[anthropic]`, `[openai]`, `[embeddings]`
(sentence-transformers), `[mcp]` (the server), `[dev]` (tests and
linters).

## Version

`darwin_memo.__version__` is the installed package version as a string.
`CITATION.cff`, `server.json` and `.zenodo.json` must agree with it; a test
enforces that.

## Core types (`darwin_memo.types`)

### `MemoryEntry`

A self-contained QA pair, the unit of selection.

```python
@dataclass
class MemoryEntry:
    question: str
    answer: str
    kind: EntryKind = EntryKind.EXPLICIT
    sources: list[str] = []          # provenance labels (doc ids, "agent", "cycle-3")
    energy: float = 1.0              # spawn stake; the survival currency
    born_cycle: int = 0
    recorded_ts: str = <UTC ISO-8601 now, second precision>
    last_used_cycle: int = -1        # -1 means never credited
    uses: int = 0
    lineage: list[str] = []          # ids merged into this entry by consolidation
    id: str = <12-hex uuid>
```

- `recorded_ts` is the wall-clock moment the entry was created, shown
  on every consult surface as part of its age line. Files persisted
  before the field existed load as the empty string and render as
  "age unknown": the loader never fakes a timestamp. Consolidation
  carries the NEWEST member's `recorded_ts` into a merged entry.
- `alive: bool` (property): `energy > 1e-9`.
- `to_dict() -> dict` / `from_dict(d) -> MemoryEntry`: the on-disk
  shape, see [store-format.md](store-format.md).

### `EntryKind`

String enum: `EXPLICIT`, `INFERRED`, `ENTITY`, `CROSS_DOC`
(the MeMo reflection-QA kinds), `EXPERIENCE` (written from
trajectories or agent adds), `CONSOLIDATED` (merge products).

### `Outcome`

```python
@dataclass
class Outcome:
    delta: float    # change in a conserved, measured resource; never a grade
    detail: str = ""
```

### `Trajectory` and `CycleStats`

`Trajectory(cycle, task, answer, deciding_entry, supporting_entries,
outcome)` records one task attempt. `CycleStats(cycle, population,
births, deaths, merges, total_energy, resource_delta, tasks=0,
silent=0, nonzero_outcomes=0)` is one cycle's population accounting;
`silent` counts tasks memory did not answer, the best degeneracy
signal.

## `MemoryStore` (`darwin_memo.store`)

```python
MemoryStore(max_energy: float = 5.0, upkeep: float = 0.05,
            retriever: Retriever | None = None)
```

Holds entries, delegates matching to the retriever (lexical by
default), and runs the energy ledger. One invariant: relevance scores
never read energy; energy is a sort tie-break only.

| method | signature | notes |
|---|---|---|
| `add` | `(entry: MemoryEntry) -> MemoryEntry` | no dedup, no checks |
| `get` | `(entry_id: str) -> MemoryEntry \| None` | alive entries only |
| `alive` | `() -> list[MemoryEntry]` | |
| `graveyard` | `() -> list[MemoryEntry]` | the graveyard only grows |
| `get_dead` | `(entry_id: str) -> MemoryEntry \| None` | O(1) graveyard lookup |
| `dead_count` | `() -> int` | |
| `__len__` | `() -> int` | alive count |
| `retrieve` | `(query: str, k: int = 3, *, half_life: float \| None = None, now_cycle: int \| None = None, kind: EntryKind \| str \| None = None, source: str \| None = None) -> list[tuple[MemoryEntry, float]]` | top-k by retriever score, energy tie-break; see [temporal options](#temporal-retrieval-options) |
| `similarity` | `(a, b) -> float` | pairwise, via the retriever |
| `credit` | `(entry_id: str, amount: float, cycle: int) -> None` | clamps at `max_energy`; bumps `uses`, `last_used_cycle` |
| `charge_upkeep` | `(protect: Collection[str] = ()) -> list[MemoryEntry]` | charges all, buries the dead, returns them; `protect` pays but is not buried |
| `bury` | `(entry_id: str) -> None` | raw mechanism; prefer `Ledger.forget`, which honors escrow |
| `total_energy` | `() -> float` | |
| `energy_share_by_kind` | `() -> dict[str, float]` | |
| `to_payload` / `from_payload` | see [store-format.md](store-format.md) | |
| `save` | `(path) -> None` | atomic write under the advisory lock |
| `load` | `classmethod (path, retriever=None) -> MemoryStore` | |

### `StoreLockedError`

`class StoreLockedError(RuntimeError)`: raised by `save` and `load`
(on `MemoryStore` and `Ledger`, and therefore by every CLI and MCP
operation that persists) when another process holds the advisory lock
on the same store file. The lock is `fcntl.flock` on a sidecar file,
held only for the duration of one save or load. POSIX only: on
Windows the lock degrades to a no-op and the behavior is the lockless
last-writer-wins of every release before 0.5.0. Either way the
contract is single-writer; the lock adds noise on violation, not
multi-writer support.

## Retrieval (`darwin_memo.retrieval`)

### `Retriever` (protocol)

Implement these five methods to plug in your own matching:
`rank(query, entries) -> list[tuple[MemoryEntry, float]]`,
`similarity(a, b) -> float` (in [0, 1]),
`forget(entry_id) -> None`,
`dump_state() -> dict` (persisted into the store file; `{}` if none),
`load_state(state) -> None`.

### `LexicalRetriever(min_coverage: float = 0.25)`

The zero-dependency default: smoothed-IDF token overlap with a
relevance floor. Below `min_coverage` of the query's IDF mass, an
entry does not qualify and memory stays silent.

### `EmbeddingRetriever(embed: EmbeddingFn, min_similarity: float = 0.30)`

Cosine retrieval over any `text -> list[float]` function
(`EmbeddingFn` protocol). Vectors are cached per entry id and persist
through `MemoryStore.save`. Raises `ValueError` if the embedding
function returns an empty vector (caching one would make the entry
permanently unretrievable).
`warm(entries, batch_embed=None) -> int` pre-embeds uncached entries,
in one request when given a batch function such as
`OllamaEmbedder.batch`.

Honest scaling note: `rank` is O(population x dims) in pure Python,
fine to a few thousand entries
([benchmarks: scaling](benchmarks.md#scaling-synthetic-corpus-median-of-repeats-apple-m4)).

### `HashingEmbedder(dims: int = 256, ngram_range: tuple[int, int] = (3, 5))`

Zero-dependency character n-gram hashing embedder (crc32, stable
across processes). Buys typo and morphology robustness, not synonym
recall.

### `EMBEDDING_MERGE_THRESHOLD = 0.85`

Cosine similarity runs hotter than Jaccard: survival configs over
embedding retrievers should raise `merge_threshold` to at least this.
The Jaccard-scale counterpart is `DEFAULT_MERGE_THRESHOLD = 0.55`
(from `darwin_memo.consolidate`, re-exported at top level), shared by
consolidation, `SurvivalConfig.merge_threshold`, and conflict
surfacing, so "near duplicate" means one thing package-wide.

## Temporal retrieval options

`MemoryStore.retrieve`, `QueryProtocol.answer`, and `Ledger.decide`
share keyword-only options that change what gets surfaced, never what
gets paid: balances, credit assignment, and escrow do not see any of
them.

- `half_life: float | None = None`: opt-in recency-weighted ranking.
  Scores halve for every `half_life` ticks since the entry last
  settled (its born tick if nothing ever has). Off when `None`; a
  non-positive value raises `ValueError` rather than silently ranking
  without recency.
- `now_cycle: int | None = None` (`retrieve` and `answer` only):
  anchors the decay clock. The Ledger passes its own tick count; when
  omitted, the latest tick recorded on any alive entry stands in.
- `kind: EntryKind | str | None = None`: only entries of this kind
  qualify. An unknown kind string raises `ValueError` rather than
  silently matching nothing.
- `source: str | None = None`: only entries whose `sources` list
  contains this label qualify.

### `darwin_memo.temporal`

The mechanics behind the dated consult surfaces. Top-level exports:
`age_annotation`, `newest_first`, `recency_weight`,
`conflict_clusters`, `CONFLICT_HEADER`.

- `age_annotation(entry) -> str`: one bracketed age line (recorded UTC
  timestamp or "age unknown", born tick, last settled tick or "never
  settled").
- `newest_first(entries) -> list[MemoryEntry]`: recency order by
  `(recorded_ts, born_cycle)`; entries without a timestamp sort
  oldest.
- `recency_weight(entry, now_cycle: int, half_life: float) -> float`:
  the half-life multiplier, 1.0 at age zero, 0.5 one half-life after
  the last settlement. Raises `ValueError` on non-positive
  `half_life`.
- `conflict_clusters(entries, similarity, threshold) ->
  list[list[MemoryEntry]]`: groups of two or more near-duplicate
  entries (same anchor-based clustering and threshold semantics as
  consolidation), newest first within each group.
- `render_consult(hits, similarity, threshold) -> str` (submodule
  only, not in `__all__`): the single choke point that turns retrieval
  hits into dated consult text. A clear winner renders as its answer
  plus an age line; hits overlapping the winner above the threshold
  render as a conflict block under `CONFLICT_HEADER`
  (`"conflicting/overlapping advice, newest first:"`), each entry
  dated, newest first.

## Encoding (`darwin_memo.encode`)

- `Document(doc_id: str, text: str)`: dataclass input to encoders.
- `LocalEncoder().encode(documents: list[Document]) -> list[MemoryEntry]`:
  rule-based reflection encoding, offline, no models.
- `ReflectionEncoder(client: LLMClient, max_workers: int = 4)`:
  model-driven MeMo steps 1 through 5; `encode(documents)` runs
  per-document and per-pair calls on a thread pool.
- `demo_corpus() -> list[Document]`: the canonical three-document demo
  corpus, shipped as package data.

## Query protocol (`darwin_memo.protocol`)

```python
QueryProtocol(store: MemoryStore, client: LLMClient | None = None,
              conflict_threshold: float = DEFAULT_MERGE_THRESHOLD)
answer(query: str, k: int = 3, *, half_life: float | None = None,
       now_cycle: int | None = None, kind: EntryKind | str | None = None,
       source: str | None = None) -> ProtocolAnswer
```

Without a client: local mode, the answer is the top retrieved entry's
text and `deciding_entry` is its id; empty text means memory is
silent. With a client: the three-stage MeMo protocol (grounding,
entity identification, answer seeking); snippets are numbered and
carry their age lines (near-duplicate snippets get a mechanical
conflict note), the model cites which it used, and credit attaches to
the cited entries. An unparseable citation line falls back to even
spread over everything consulted; an explicit "SOURCES: none" yields
no provenance at all.

`conflict_threshold` is the near-duplicate floor for flagging
overlapping hits as conflicting advice; the keyword-only `answer`
options are the [temporal retrieval
options](#temporal-retrieval-options) passed through to
`MemoryStore.retrieve`.

`ProtocolAnswer(text: str, deciding_entry: str | None = None,
supporting_entries: list[str] = [], annotated_text: str = "")`.
`annotated_text` is the consult-surface rendering of `text`: the same
answer plus age annotations, or a dated conflict block when
near-duplicate entries disagree. Acting paths (the survival loop,
environments) keep reading `text`, so the economics never see an
annotation; surfaces that show memory to a model or agent (CLI
`query`, `ledger decide`, MCP `memory_query`) show `annotated_text`.

## Survival loop (`darwin_memo.survival`)

### `SurvivalConfig`

```python
@dataclass
class SurvivalConfig:
    cycles: int = 30
    credit_gain: float = 0.6
    supporting_share: float = 0.25
    consolidate_every: int = 5
    merge_threshold: float = DEFAULT_MERGE_THRESHOLD   # 0.55
    write_experience: bool = True
    resource_scale: float | None = None   # None: use the environment's
```

See [tuning.md](tuning.md) for what each knob does and the evidence.

### `SurvivalLoop`

```python
SurvivalLoop(store, env: Environment, protocol=None, config=None)
run() -> SurvivalReport
run_cycle(cycle: int) -> tuple[CycleStats, list[Trajectory]]
```

Batch-shaped selection: per cycle, the environment proposes tasks,
the protocol answers, the environment measures, credit flows along
provenance, upkeep is charged, and consolidation runs periodically.
When no protocol is passed, the default one flags conflicting advice
at `config.merge_threshold`, the same floor consolidation merges at
(the Ledger does the same).
`SurvivalReport` carries `stats` and `trajectories`; `summary()`
renders the table and appends `health_warning()`, a plain-language
diagnosis of the two degenerate modes (persistent silence, and
environments that never pay out).

### Functions

- `assign_credit(store, deciding_entry, supporting_entries, delta,
  resource_scale, config, cycle) -> list[tuple[str, float]]`: the one
  credit rule (`credit_gain * tanh(delta / resource_scale)`), shared
  by the loop, the Ledger, and the examples. Returns the applied
  (entry_id, credit) pairs.
- `is_silent(answer_text, deciding, supporting) -> bool`: did memory
  contribute nothing.
- `death_cause(entry, poisoned_ids, merged_away) -> str`: classify a
  graveyard entry as `"merged"`, `"executed"`, or `"starved"`.
- `advance_lifecycle(store, applied, delta, deciding_entry) -> list[tuple[str, str]]`:
  the one trust-lifecycle rule, shared by `Ledger.settle` and the loop.
  Advances probation and juvenile counters after a credited outcome and
  returns the (entry_id, transition) pairs. Only relevant when the trust
  lifecycle is enabled; see [the threat model](threat-model.md).

## Ledger (`darwin_memo.ledger`)

Event-driven survival for real-world outcome timing: decide now,
settle when the measurement lands, tick on your own cadence.

```python
Ledger(store: MemoryStore,
       protocol: QueryProtocol | None = None,
       config: SurvivalConfig | None = None,
       resource_scale: float | None = None,
       event_log: str | Path | None = None,
       event_log_max_bytes: int = 10 * 1024 * 1024,
       event_log_keep: int = 3)
```

| method | signature | notes |
|---|---|---|
| `decide` | `(query: str, k: int = 3, *, half_life: float \| None = None, kind: str \| None = None, source: str \| None = None) -> Ticket` | answers via the protocol, opens a ticket when there is provenance; the [temporal options](#temporal-retrieval-options) are pure retrieval concerns (`half_life` anchors at this ledger's tick count) |
| `settle` | `(ticket_id: str, delta: float, detail: str = "") -> bool` | credit flows now; False means unknown, already settled, or expired (a no-op, never an exception: duplicate deliveries are normal) |
| `abandon` | `(ticket_id: str) -> bool` | settle at delta zero for answers never acted on |
| `add` | `(question: str, answer: str, source: str = "agent") -> MemoryEntry` | writes an EXPERIENCE entry at spawn energy, logged |
| `forget` | `(entry_id: str) -> str` | `"buried"`, `"missing"`, or `"escrowed"` (refused: a pending ticket names it) |
| `tick` | `(expire_after: int \| None = 50) -> dict` | expiry, upkeep, deaths, periodic consolidation; returns stats |
| `save` | `(path) -> None` | one atomic file: store plus ledger state; may raise `StoreLockedError` |
| `load` | `classmethod (path, protocol=None, config=None, resource_scale=None, event_log=None, retriever=None) -> Ledger` | a plain store file loads with fresh ledger state |
| `pending` | `() -> list[Ticket]` | |
| `history` | `(entry_id: str) -> list[str \| dict]` | per-entry notes, oldest first, capped at 100 in memory; the JSONL log is full |
| `obituary` | `(entry_id: str) -> str` | why did this entry die, from recorded history |

Escrow invariant: entries named by any unsettled ticket pay upkeep
but cannot be buried or merged, so a verdict can never arrive after
the execution.

### `Ticket`

`Ticket(query, answer, deciding_entry, supporting_entries, born_tick,
id=<12-hex uuid>)` with a `provenance` property (supporting entries
plus the decider). `answer` carries the consult-surface rendering
(`ProtocolAnswer.annotated_text` when present): entry text plus age
lines, or a dated conflict block.

## Consolidation (`darwin_memo.consolidate`)

```python
DEFAULT_MERGE_THRESHOLD = 0.55
consolidate(store, cycle: int, threshold: float = DEFAULT_MERGE_THRESHOLD,
            exclude: frozenset[str] | set[str] = frozenset()) -> int
```

Merges clusters of similar alive entries into single CONSOLIDATED
entries: energy pools (capped at `max_energy`), sources union,
lineage records the merged ids, and `recorded_ts` carries the newest
member's timestamp (stamping merge time would make stale advice look
current; it stays empty when no member has one). Returns merges
performed. `exclude` is how the Ledger keeps escrowed entries out.

## Environments (`darwin_memo.environments`, `darwin_memo.testsuite_env`)

### `Environment` (protocol)

```python
class Environment(Protocol):
    resource_scale: float
    def tasks(self, cycle: int) -> list[Task]: ...
    def verify(self, task: Task, answer_text: str) -> Outcome: ...
```

The one rule: `verify` must measure, never grade.
`Task(prompt: str, context: dict)`.

### `decision_polarity(answer_text, extra_positive=(), extra_negative=()) -> bool | None`

Reads a yes/no action decision out of an answer. True is act, False
is do not act, None is silence. Negative markers win; positive
markers do not fire when directly negated. The built-in vocabulary
covers delete/remove and apply/keep only: for any other action verbs
you MUST pass extra markers or every answer reads as silence and the
population starves.

### Bundled environments

- `StorageEnv(root=None, files_per_cycle=12, seed=7)`,
  `resource_scale = 100_000.0` (bytes). Disk cleanup against a real
  temp directory; deleting a protected file costs 3x its size.
  `cleanup()` removes the tree.
- `TestSuiteEnv(root=None, defects_per_cycle=3, seed=7)`,
  `resource_scale = 2.0` (tests). Patch review in a generated
  micro-project; the reward is the passing-test count. `cleanup()`.
- `VerifiableQAEnv(qa_pairs: list[tuple[str, str]], per_cycle=5,
  seed=7)`, `resource_scale = 1.0`. Exact containment of a known
  token: the weakest grounding, still a measurement.

### Priced inaction

Both bundled environments score inaction at exactly zero: a kept file and
a skipped patch cost nothing, so a store that has gone silent pays nothing
for it. Several conclusions rest on that, and it is a property of these
worlds rather than of curation, so each has a subclass on the other side
of it.

- `RentedStorageEnv(..., hold_cost=0.0, rent_tier="uniform")`. Same world,
  but the conserved quantity is quota **occupancy** in byte-cycles: a file
  left in place occupies its own size for the cycle it was left.
  `hold_cost=0.0` delegates to the parent identically, on purpose, as a
  reproducibility canary.
- `RentedTestSuiteEnv(..., hold_cost=0.0)`. The counterpart, where leaving
  the suite broken is measured rather than free.
- `RENT_TIERS = ("uniform", "aligned", "inverted")` and
  `rent_multipliers(tier) -> dict[str, float]`: per-category multipliers,
  normalised on expected cost so a tier changes the *shape* of the price
  and not its total. `aligned` bills only the disposable categories, which
  is the economy a real retention policy has; `inverted` is its mirror.

## LLM clients (`darwin_memo.llm`)

Top-level exports:

- `OllamaClient(model="llama3.2", base_url="http://localhost:11434",
  temperature=0.0, timeout=120.0, max_tokens=1024)` with
  `complete(prompt, system="") -> str`. Stdlib urllib, no
  dependencies. Raises `OllamaError`.
- `OllamaEmbedder(model="nomic-embed-text", base_url=..., timeout=60.0)`:
  callable `(text) -> list[float]`, plus
  `batch(texts: list[str]) -> list[list[float]]` for one-request
  warming. Raises `OllamaError`.
- `OllamaError(message, status=0, body="")`: a `RuntimeError` carrying
  the HTTP status and response body.
- `ollama_available(base_url=..., timeout=2.0) -> bool`.

Importable from the submodule (not re-exported at top level, and the
optional extras gate their dependencies): `darwin_memo.llm.LLMClient`
(the protocol: `complete(prompt, system="") -> str`),
`AnthropicClient(model=None, max_tokens=1024)`,
`OpenAICompatClient`, and `parse_json_array(text) -> list`.

## EVM settlement (`darwin_memo.evm`)

- `DEFAULT_BASE_RPC = "https://mainnet.base.org"`.
- `EvmRpc(url=DEFAULT_BASE_RPC, timeout=30.0)`: minimal JSON-RPC over
  stdlib urllib; `call(method, params)`, `block_number()`,
  `block_timestamp(block)`. Raises `EvmRpcError(message, code=0,
  body="")`, a `RuntimeError`.
- `EvmSettler(address: str, rpc: EvmRpc | None = None,
  token: str | None = None)`: measure one conserved on-chain resource
  for one address. `snapshot(block=None) -> dict`,
  `delta(before, after) -> float` (static),
  `block_at(timestamp) -> int`,
  `measure(start_timestamp, end_timestamp) -> float`,
  `tx_cost(tx_hash) -> dict`, `token_decimals() -> int`.

## OpenAI Agents SDK adapter (`darwin_memo.integrations.openai_agents`)

Importable from the subpackage, zero dependencies (the SDK's `Session`
protocol is implemented by duck typing; neither package imports the
other):

```python
DarwinMemoSession(session_id: str, transcript_dir: str | Path,
                  ledger: Ledger | None = None,
                  lesson_path: str | Path | None = None,
                  resource_scale: float | None = None)
```

The transcript side is a faithful SDK Session backed by one JSONL file
per session id under `transcript_dir`: async `get_items(limit=None)`
(latest N, chronological order), `add_items(items)`, `pop_item()`,
`clear_session()`. The lesson side is explicit and opt-in, requiring
`ledger` or `lesson_path` (otherwise these raise `RuntimeError`):

- `consult(question: str, k: int = 3) -> Consultation` opens a ticket
  against the lesson store; `Consultation(ticket_id: str | None,
  lessons: str)`, with `ticket_id` None when memory was silent.
- `settle(ticket_id: str, delta: float, detail: str = "") -> bool`
  reports the outcome the HOST measured; the adapter never invents
  deltas.
- `abandon(ticket_id: str) -> bool` releases a ticket not acted on.

When `lesson_path` is set, every consult/settle/abandon persists, so
open tickets survive the process that minted them.
`transcript_filename(session_id) -> str` maps unsafe session ids to
collision-free JSONL filenames. Wiring examples:
[integrations/openai-agents.md](integrations/openai-agents.md).

## CLI: `darwin-memo`

Every subcommand that persists may raise `StoreLockedError` if
another process overlaps on the same file. Ledger-backed subcommands
auto-create a missing store file and append to an event log named
after the store (`lessons.json` writes `lessons.events.jsonl` next to
it).

| command | what it does |
|---|---|
| `darwin-memo demo [--cycles N] [-o FILE]` | the self-contained poisoned-entry demo |
| `darwin-memo encode DOCS... [-o memory.json]` | text files to a reflection-QA memory (LocalEncoder) |
| `darwin-memo query MEMORY "question" [--model ollama:NAME\|anthropic:NAME] [--half-life N] [--kind KIND] [--source SRC]` | interrogate a saved memory; default is local retrieval; answers carry age lines and conflict blocks |
| `darwin-memo stats MEMORY` | population and energy overview |
| `darwin-memo ledger MEMORY [--scale F] OP ...` | one Ledger operation, one JSON object on stdout |
| `darwin-memo top MEMORY [--limit N] [--json]` | living entries ranked by balance |
| `darwin-memo why MEMORY ENTRY_ID [--json]` | one entry's full life story, dead or alive |
| `darwin-memo audit MEMORY [--since TS] [--last N] [--json]` | event-log digest across rotated files |
| `darwin-memo render MEMORY [-o MEMORY.md] [--budget 25kb] [--max-lines 200] [--split-dir DIR]` | top-balance survivors as a budget-capped `MEMORY.md` (see the [Claude Code integration](integrations/claude-code.md)) |
| `darwin-memo doctor MEMORY [--json]` | name the failure mode behind a store that is not earning; see [findings](#doctor-findings) below |
| `darwin-memo ui MEMORY [--port 8787] [--no-open]` | local read-only dashboard in your browser |
| `darwin-memo settle-ci MEMORY ...` | settle a CI lesson store from test results |
| `darwin-memo mcp [--memory PATH] [--resource-scale F]` | serve the memory over MCP stdio, the same server as the `darwin-memo-mcp` console script below |

### `ledger` operations

All mutating operations save before printing; `stats` and `obituary`
are read-only.

```
ledger FILE decide "question" [-k 3]          {"answer", "ticket_id", "silent"}
            [--half-life N] [--kind KIND] [--source SRC]
ledger FILE settle TICKET_ID DELTA [--detail] {"settled": bool}
ledger FILE abandon TICKET_ID                 {"abandoned": bool}
ledger FILE add "question" "answer" [--source agent]   {"entry_id"}
ledger FILE forget ENTRY_ID                   {"forgotten": bool, ["reason"]}
ledger FILE tick [--expire-after 50]          tick stats
ledger FILE stats                             population overview
ledger FILE obituary ENTRY_ID                 {"obituary": str}
```

`--scale` (default 1.0) sets `resource_scale` for settle deltas.
`--half-life`, `--kind`, and `--source` (shared with `query`) are the
[temporal retrieval options](#temporal-retrieval-options); a
non-positive `--half-life` is an argparse error. The
CLI cannot construct your embedder, so it always loads with the
default lexical retriever and ranks lexically. Warning, verified
behavior: because the lexical retriever persists no state, any
mutating `ledger` operation on a store built with an embedding
retriever re-saves the file WITHOUT its persisted vectors (see
[store-format.md](store-format.md)). Read-only commands are safe.

### `settle-ci`

Settles every `darwin-memo-ticket: <id>` line found in `--pr-body`
(default: the `PR_BODY` environment variable) with a measured
test-pass delta, then runs one tick and saves.

```
darwin-memo settle-ci MEMORY
  --base-xml FILE --head-xml FILE      junit mode (primary): per-test diff
  --passes-before N --passes-after N   fallback mode: raw counts, both required
  [--pr-body TEXT] [--detail TEXT] [--scale 1.0]
  [--state flaky.json] [--window 10] [--flip-threshold 3]
  [--expire-after 50]
```

Exit codes: 0 settled, 1 usage error, 3 abstained (no parseable junit
XML, zero collected tests, or a collection error: the run measured
nothing and the store is left untouched). **Skipped tests are unmeasured,
not failed**: a test skipped on either side contributes to no transition
and accrues no flake history, so a skip that later turns into a pass pays
nothing. A test that is *absent* is different and still counts, because
deleting a passing test is a real loss. Flaky tests that flip
direction `--flip-threshold` times inside the `--window` are
quarantined out of the delta via the sidecar state file. See
[the integration guide](integrations/ci-lesson-store.md).

### `doctor` findings

`darwin-memo doctor MEMORY [--json]` reads the store and its event log
(`darwin_memo/observe.py:doctor`, rules shared with the batch loop's
`SurvivalReport.health_warning` via `darwin_memo/diagnose.py`) and
names which of six degeneracies it hit, instead of leaving several of
them looking identical (a starving population reads the same whether
memory never speaks or never gets paid). Human output is one block per
finding: `SEVERITY [code]: summary`, then `evidence:` and `fix:`
lines; `--json` prints `{"findings": [...]}` with the same fields.
Findings are independent — zero or more can fire in one run.

The three rules above the fold below all read the event-log *window*
handed to `doctor`, not the store — and the window is not the store: a
rotated log (`EVENT_LOG_KEEP`), a missing sidecar `.events.jsonl`, or a
quiet window (ticks only, settles rotated off the end) all thin it on
a store that earned plenty outside it. `doctor` computes once, from
evidence that does not depend on the window (per-entry settlement
history persisted in the memory file), whether credit ever flowed
*anywhere* in the store's life, and every rule below that would
otherwise conclude "never earned" from the window alone is gated on
that store-wide evidence first.

| code | severity | fires when |
|---|---|---|
| `silent_majority` | error | at least 10 decisions were made and memory stayed silent on over 80% of them, **and the store never earned anywhere in its history** |
| `env_never_paid` | error | at least 5 settlements landed *that the caller itself made* (tick's own zero-delta expiry settlements are excluded) and every one carried a zero delta (gross movement, not a net sum, so cancelling payouts do not read as dead), **and the store never earned anywhere in its history** |
| `starvation_cliff` | error | at least 3 dead entries, at least half of them starved (never used, not merged, not executed), nothing in the window was ever credited, no settlement in the window is unattributable (`credit_untracked` below), **and the store never earned anywhere in its history**. Starving alone is a healthy death mode for trivia nobody needed; the fault is a population that never earns |
| `tickets_stale` | warn | one or more pending tickets are older than 50 ticks (`expire_after`'s default) |
| `settles_dropped` | warn | `settle_dropped` events exceed the count of silent decides. A silent `decide()` never opens a ticket (`Ledger.decide` only tracks a ticket when the answer has provenance), so settling a silent decide always drops — that count is benign and subtracted out; only the excess is worth a warning |
| `credit_untracked` | warn | one or more settlements carry no per-entry `applied` credit list (written by a version before per-entry credit was logged) |
| `ticking_without_evidence` | warn | more ticks have passed since the last credited settlement than the living population has upkeep left to pay. The threshold is the store's own arithmetic, not a constant, because a fixed share of `max_energy / upkeep` fires only after the store is already dead. Unlike the three rules above it, this one applies to a store that *did* earn — every tick charges upkeep whether or not anything was measured, so a clock running faster than the evidence is a slow, silent, total loss |

Exit code: **1 if any finding has severity `error`**, otherwise **0**
— warnings alone (`tickets_stale`, `settles_dropped`,
`credit_untracked`, `ticking_without_evidence`) exit 0.

### `ui`

`darwin-memo ui MEMORY [--port 8787] [--no-open]` serves a dashboard
over `MEMORY` on `127.0.0.1` (0 for `--port` picks a free one;
`--no-open` skips the automatic browser launch). Loopback-only and
read-only by construction: `serve()` refuses to bind any host outside
`{127.0.0.1, localhost, ::1}`, and there are no mutation endpoints, so
the server needs no authentication. That bind alone does not stop a
page the operator has open elsewhere from pointing its own hostname at
`127.0.0.1` (DNS rebinding) and reading the store same-origin, so every
request also checks its `Host` header and answers `421` on anything
that is not a loopback name or address. The store and event log are
re-read from disk on every request rather than cached. Four JSON
routes plus the static bundle: `GET /api/state` (population, energy,
`doctor` findings, `timeline`, `economics`, living entries, graveyard,
pending tickets — everything the dashboard renders, in one pass),
`GET /api/entry/{id}` (one entry's life story, 404 if unknown),
`GET /api/events?since=&last=` (windowed event log), and everything
else served from the built frontend (`darwin_memo/data/ui`) or a
"build it" placeholder page when no bundle is present. A concurrent
external writer (the CLI, the MCP server) holding the store's advisory
lock answers 503, not a crash.

## MCP server: `darwin-memo-mcp`

```
darwin-memo-mcp [--memory PATH] [--resource-scale 1.0]
```

`--memory` defaults to the `DARWIN_MEMO_PATH` environment variable,
then `~/.darwin-memo/memory.json`. Requires the `[mcp]` extra. The
server wraps one `Ledger` held in memory and saves after every
mutating call; full state including open tickets survives restarts.
Do not point a second writer (the CLI, another server) at the same
file while it runs: the server's next save clobbers whatever the
other writer wrote.

| tool | signature | returns |
|---|---|---|
| `memory_query` | `(query: str, half_life: float = 0)` | JSON: `answer`, `ticket_id`, `silent`; answers carry age lines and conflict blocks; `half_life > 0` opts into recency ranking, zero means off |
| `memory_settle` | `(ticket_id: str, delta: float, detail: str = "")` | settled or NOT settled, plainly |
| `memory_abandon` | `(ticket_id: str)` | abandoned or not pending |
| `memory_add` | `(question: str, answer: str, source: str = "agent")` | the new entry id |
| `memory_tick` | `()` | tick stats JSON |
| `memory_stats` | `()` | population overview JSON |
| `memory_obituary` | `(entry_id: str)` | the entry's credit history |
| `memory_audit` | `(since: str = "", last: int = 0)` | event-log digest JSON; zero values mean no filter |

## Exceptions, in one place

| exception | raised by |
|---|---|
| `StoreLockedError` | any save or load that finds the sidecar lock held (POSIX only) |
| `OllamaError` | Ollama client and embedder transport or API errors |
| `EvmRpcError` | EVM JSON-RPC transport, API, or decode errors |
| `ValueError` | `EmbeddingRetriever` on an empty embedding vector; `darwin_memo.render.render_store` and `parse_budget` on unreadable stores and bad budgets (the `render` CLI turns these into a one-line error, exit 1); `MemoryStore.retrieve` and `recency_weight` on a non-positive `half_life`, and `retrieve` on an unknown `kind` filter |
| `RuntimeError` | `DarwinMemoSession.consult`/`settle`/`abandon` without a configured lesson store |

`Ledger.settle` returning False and `Ledger.forget` returning
`"escrowed"`/`"missing"` are deliberate non-exceptions: duplicate
settlements and contested buries are normal in event-driven use, and
callers need the outcome, not a crash.
