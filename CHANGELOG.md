# Changelog

All notable changes to this project are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project uses [SemVer](https://semver.org/).

## [Unreleased]

### Added

- SWE-Bench-CL learning-curve pilot harness (`bench/swebench_cl/`):
  pins one or two continual-learning sequences (dataset commit plus
  file sha256, task identity in a committed manifest), runs a model
  through them task by task under three arms (memory_on, memory_off,
  random_matched at the same injected-token budget), settles the
  lesson store from the official SWE-Bench evaluation outcome, and
  mints one lesson per task from a deterministic template (no LLM
  judging; only the model's quoted reflection is model-authored).
  Model calls sit behind one OpenAI-compatible endpoint config, so a
  local Ollama server and a frontier provider differ by config only.
  The Docker executor sizes every image from the registry before
  pulling and refuses any pull that would leave less than 4 GB of
  disk free; the documented stub executor exercises every runner
  path offline and labels every report `mode="stub"`. The pilot
  protocol and its pre-committed cells live in `docs/benchmarks.md`
  before any result exists.
- `darwin-memo render STORE -o MEMORY.md`: project top-balance
  survivors into Claude Code's auto-memory file under both ceilings the
  host actually loads, a hard byte budget (`--budget`, default 25kb)
  and a hard line cap (`--max-lines`, default 200), with admission
  measured against the fully rendered document. Deterministic: same
  store, same arguments, byte-identical output. `--split-dir DIR`
  writes one topic file per kind plus a budget-aware index that counts
  only the topics it links, and a re-render deletes topic files for
  kinds with nothing left to show, so dead lessons never linger on the
  reading surface. A missing or empty-world store renders a minimal
  honest file; an unreadable store (empty, truncated, locked, or not a
  store payload) exits with a one-line error and leaves the previous
  render untouched, so hooks and cron jobs can run it unconditionally.

- `darwin-memo mcp`: the main CLI now serves the MCP stdio server,
  sharing the flag set and `DARWIN_MEMO_PATH` handling of
  `darwin-memo-mcp` (which keeps working unchanged). MCP registry
  clients construct launches as `uvx [runtimeArguments]
  darwin-memo@VERSION [packageArguments]`, and uvx runs the console
  script named after the package, which had no way to reach the
  server. `server.json` now installs the extra with `--with
  "darwin-memo[mcp]"` (with `--from`, uvx reads `darwin-memo@VERSION`
  as a literal executable name and fails) and passes `mcp` as a
  package argument, so machine-constructed launches start the server.
  Without the extra installed the subcommand exits with the exact
  `pip install "darwin-memo[mcp]"` command.

## [0.5.0] - 2026-06-12

The release that unbreaks the published OpenClaw plugin: its install
instructions invoke `darwin-memo ledger`, which existed on main but
not in PyPI 0.4.0. It is also the first release where a concurrent
clobber of a store file is loud instead of silent.

### Added

- Statistical rigor for the benchmark suite: seeded bootstrap 95% CIs
  on every aggregate column, `bench.report --paired ARM_A ARM_B`
  per-seed difference tables, and `bench.report --tests` (exact paired
  sign-flip permutation tests vs a baseline, Holm-Bonferroni adjusted
  across the full printed grid). Committed raw evidence
  (`bench/results/headline.json`, `noisy.json`, `ablation.json`) is
  bound to `bench/results/MANIFEST.json`: suite, seeds, config hash,
  exact reproduction command, library version, and producing git
  commit per file. CI validates each committed file against its entry
  with `bench.report --check --require-manifest`, which fails if the
  manifest or the entry goes missing.
- `darwin-memo ledger FILE OP`: every Ledger operation as a CLI
  subcommand with one JSON object on stdout (decide, settle, abandon,
  add, forget, tick, stats, obituary). The scripting bridge for shell
  scripts, CI steps, and host-process plugins, built for the OpenClaw
  memory plugin, whose host SDK ships no MCP client. The store
  auto-creates on first use; mutating ops save before printing (a
  crash cannot acknowledge an unsaved settlement, and invocations that
  overlap on one file trip the advisory lock instead of clobbering
  each other silently); events append to the same `.events.jsonl` the
  MCP server writes; and `forget` refuses entries escrowed by pending
  tickets, since burying one would let a later settle report success
  while crediting a corpse.
- Fail-loud advisory file lock on persistence: `MemoryStore.save`/
  `load` and `Ledger.save`/`load` hold `fcntl.flock` (`LOCK_EX |
  LOCK_NB`) on a sidecar lock file (`memory.json.lock`) for the
  duration of the operation, and contention raises `StoreLockedError`
  naming the lock file. Single-writer stays the contract: no blocking,
  no waiting, no multi-writer merge. The lock only turns a concurrent
  clobber from silent data loss into a loud error. POSIX-only; where
  `fcntl` is missing (Windows) it degrades to a documented no-op.
- `EvmSettler`: on-chain balances as the conserved resource, with zero
  dependencies (stdlib JSON-RPC). One settler measures one resource
  for one address, native wei or one ERC-20's raw units, via pinned
  block snapshots, so the decide-now-settle-later flow needs no
  archive node. Timestamp-bisection `block_at`/`measure` for
  retroactive windows, and `tx_cost` for single transactions
  (including the OP-stack `l1Fee`, verified to the wei against a live
  balance movement; reverted txs burn gas and move nothing). Default
  endpoint is `mainnet.base.org`, the only one of the public Base
  RPCs tested that served honest full-archive state: the module
  docstring names the one that silently lies about history. Closes
  the durable half of the Animoca Minds spike (#3);
  `examples/08_evm_settler.py` runs the loop offline.
- Dogfood: this repo now runs its own CI lesson store.
  `.darwin-memo/lessons.json` (seeded with real lessons from this
  repo's development by `.darwin-memo/seed.py`) is consulted by agents
  via `ledger.decide()`, tickets ride in PR bodies as
  `darwin-memo-ticket: <id>`, and `.github/workflows/memory.yml`
  settles them with the measured pass-count delta on every merged PR,
  ticks, and commits the curated store back to main. First production
  deployment of the flagship integration, on the repo that ships it.
- Noisy-outcome benchmark suite (`bench --suite noisy`): the ledger's
  forgiveness claim is now measured instead of asserted.
  `FlakyStorageEnv` makes measurements lie deterministically (the world
  stays truthful; arms decide off reported deltas and are scored on
  true ones) under three noise models: `flip` (symmetric sign flip),
  `false_bad` (flaky-CI shape: good changes report red), and
  `magnitude` (sign kept, size lied about: the one model where
  sign-driven heuristics are provably immune and only the ledger can
  degrade). The grid runs to 50% noise so the ledger's own failure
  boundary is published, not just the baselines'.
- Noise-hardened baselines, so the ledger is compared against the
  heuristic family's best selves rather than a strawman:
  `evict_on_negative` generalized to K lifetime strikes (K=1,2,3),
  `evict_consecutive` (strikes a success wipes clean), and
  `quarantine` (evict on blame, re-encode a fresh copy after a
  cooldown: the recovery path real deployments have).
- `bench.report --paired ARM_A ARM_B [--metric M]`: per-seed paired
  differences with win counts. Flake marks are a fixed property of the
  world at a given (seed, rate, model), so arms are exactly paired and
  mean±std understates what the data supports.
- Per-run lie accounting (`flakes_marked`, `flakes_fired`, fired
  counts split by direction, `reported_cum_delta`) with a hard
  accounting-identity check; `keep_everything` doubles as an in-suite
  canary (its true deltas are provably noise-invariant, and
  `bench.report --check` fails on any drift).
- Citation-fidelity probe (`python -m bench.citation_probe --model
  NAME`): per-model rates for parsed citations, explicit none,
  even-spread fallback, think-block emission, reflection-QA JSON
  validity, and the dangerous cell local mode cannot have:
  answers that read as an action while citing nothing, so the
  environment acts and selection has nobody to charge.
- Measured citation-fidelity matrix in
  docs/integrations/hermes.md (llama3.2, hermes3:8b, qwen3:30b-a3b,
  Hermes 4.3 36B): SOURCES-line emission, citation vs explicit-none vs
  fallback rates, think-block handling verified live, and the
  unattributed-action hazard (an answer that reads as an action while
  citing nothing: the environment acts, selection has nobody to
  charge). Plus the first measured LLM-mode survival results: with
  llama3.2 the actionable poison dies at cycle 14 in 3/3 seeds (cycle
  0 in local mode): citation dilution slows selection by an order of
  magnitude, it does not break it.

### Changed

- BREAKING (same-seed worlds): `StorageEnv`, `VerifiableQAEnv`, and
  `TestSuiteEnv` derive each cycle's RNG from `cycle_rng(seed, cycle)`,
  a SHA-256 hash of the pair, instead of `random.Random(seed + cycle)`.
  The old scheme made adjacent seeds shifted windows of one another
  (seed 3 at cycle 5 WAS seed 4 at cycle 4), so multi-seed spreads read
  smoother than independent draws justify. The same seed now produces a
  different world than released 0.4.0; the next release takes at least
  a minor version bump for this, and the committed benchmark results
  record their producing commit in `MANIFEST.json` so the evidence
  stays reproducible from exactly the code that made it.
- `bench.report --check`'s poison-kill gate now exempts noisy runs:
  under measurement noise a delayed or missed kill is an honest result
  the suite exists to measure, not a CI failure.
- `random_matched` and `survival_writes` refuse flake overrides loudly
  (the shadow schedule would come from a noise-free world; experience
  writes select on reported deltas and embed detail strings that name
  the true delta).
- Trove classifier moved from `3 - Alpha` to `4 - Beta`: the README
  has called the Ledger the production shape since 0.2.0 and the
  dogfood deployment runs it on this repo; the metadata now agrees.

### Fixed

- xhigh review findings: every EVM transport failure (DNS, refused,
  TLS, read timeout) now surfaces as `EvmRpcError` instead of a bare
  socket exception; `eth_call` empty return data (`"0x"`, the
  no-contract-code case) reads as a measurement failure instead of a
  Python `ValueError`; `tx_cost` guards a null transaction body. New
  `Ledger.add`/`Ledger.forget` put entry writes and burials on the
  event log and enforce escrow at the invariant's home (`forget`
  returns buried/escrowed/missing); the CLI routes through them,
  validates non-empty add, and keys all three decide fields on
  provenance so consumers never see a ticket without an answer.
- `OllamaClient` caps generation (`max_tokens=1024`, mapped to
  `num_predict`), matching the Anthropic and OpenAI-compat clients.
  Previously unbounded: a small model that loses the plot at
  temperature 0 (observed live: llama3.2 drifting into generating
  Python code on a reflection-QA extraction prompt) generated until
  the context window filled, presenting as an inexplicable timeout
  instead of a bad, parseable answer.
- `parse_json_array` strips `<think>...</think>` reasoning blocks
  before extracting, so hybrid-reasoning models can drive the
  reflection-QA encoder: measured on qwen3:30b-a3b, encoding validity
  went from 0/6 valid calls to 5/6 (a stray bracket in the reasoning poisoned
  the greedy array match into garbage). One shared `THINK_RE` in
  `llm.py` now serves both citation parsing and JSON extraction.

## [0.4.0] - 2026-06-11

A max-effort review pass surfaced 15 correctness findings plus a
cleanup list; every finding was treated. The Ledger path is the big
one: its central promise now holds across process boundaries.

### Fixed

- Ledger persistence: `Ledger.save`/`Ledger.load` write one file
  carrying the store AND the ledger state (pending tickets, tick
  count, history), forward and backward compatible with plain store
  files. The MCP server uses it, so a ticket opened today settles
  correctly from tomorrow's process. Previously every cross-process or
  cross-restart settlement silently did nothing.
- Escrow integrity: settling one ticket no longer buries entries still
  escrowed by OTHER pending tickets; a verdict can never arrive after
  the execution, per ticket.
- `settle` returns whether the settlement landed, and the MCP
  `memory_settle` reply says plainly when it did not. New `abandon`
  (and `memory_abandon`) releases no-act tickets instead of pinning
  their entries until expiry.
- Citation parsing takes the LAST `SOURCES:` line per the contract
  (earlier prose or an echoed instruction no longer shadows it), and
  an explicit `SOURCES: none` attaches no provenance instead of
  attributing every consulted entry.
- Encode-time dedup merges provenance across documents instead of
  dropping the second document's sources, which previously could
  mislabel shared facts as purely poisoned (or hide poison as trusted).
- `decision_polarity` matches markers on word boundaries with a
  negation guard: "keep iterating", "unprotected", and "not safe to
  cancel" no longer misread.
- Ollama failures raise `OllamaError` carrying the server's own
  message instead of masquerading as memory silence; embedders never
  return or cache empty vectors (which would have permanently muted
  entries through persisted caches); model-missing 404s stop falling
  back to the legacy endpoint with a worse error.
- Silence accounting keys on provenance, so it works in LLM mode where
  models always produce prose; the degenerate-run health warning uses
  gross outcome movement, not net-zero float equality.
- Experience writes now work for multi-citation LLM answers (the first
  cited entry stands in as parent).
- All persistence is atomic (temp file + rename): a crash mid-write
  can no longer destroy the memory file.
- The `[mcp]` extra floor is `mcp>=1.10`, verified empirically as the
  oldest release with the `instructions` parameter and the structured
  `call_tool` return.
- Obituary cause-of-death is tracked structurally (no spoofable string
  matching), and `python -c "import darwin_memo.__main__"` no longer
  runs the CLI.
- Bench: the paraphrase trust check requires fully-trusted sources, so
  consolidation can no longer launder poison past the metric (the
  survival_writes paraphrase-grounded score honestly drops to 0.00);
  random_matched shadow runs apply resource_scale overrides and are
  memoized; survival_embedding rejects the inapplicable min_coverage
  override loudly.

### Changed

- One shared `assign_credit` rule used by the loop, the Ledger, and
  the examples; `resource_scale` lives on `SurvivalConfig`.
- The canonical demo corpus ships as package data, read by the CLI,
  the examples, and the benchmarks (one copy, no drift); shared
  `death_cause` classifier; five benchmark baselines share one driver;
  `OllamaEmbedder.batch` plus `EmbeddingRetriever.warm` batch
  first-query embedding.

## [0.3.0] - 2026-06-11

### Added

- Fully local stack through Ollama with zero dependencies:
  `OllamaClient` and `OllamaEmbedder` speak the native localhost API
  over stdlib urllib (current `/api/embed` with legacy fallback), plus
  `ollama_available` for graceful auto-detection and
  `examples/07_local_stack.py`.
- `darwin-memo query --model ollama:NAME` (and `anthropic:NAME`) runs
  the full three-stage protocol from the shell.
- Opt-in `bench --suite llm`: the at-home recipe for the LLM-mode
  benchmark question, survival with a local model answering. Sampled,
  never in CI.
- Citation parsing strips `<think>...</think>` blocks, so
  hybrid-reasoning models (Hermes 4, R1 style) cannot cite from inside
  their thinking.
- Integration guides: OpenClaw (MCP mount today, memory-slot plugin
  planned with measured settlement), Hermes (models via Ollama, Hermes
  Agent via MCP), Animoca Minds (planned spike around a generic EVM
  settler on Base RPC). Roadmap issues #1, #2, #3.

## [0.2.0] - 2026-06-11

### Added

- `Ledger`: event-driven decide/settle/tick API for real-world outcome
  timing. Escrow holds entries with unsettled tickets out of burial and
  consolidation, unsettled tickets expire at delta zero, every event
  appends to an optional JSONL log, and `obituary(entry_id)` answers
  why an entry died from its credit history.
- `darwin-memo` CLI: `demo` (self-contained poison extinction, one
  command after pip install), `encode`, `query`, `stats`.
- MCP server (`darwin-memo-mcp`, `[mcp]` extra): `memory_query` opens a
  ledger ticket, `memory_settle` reports the measured delta later, plus
  `memory_add`, `memory_tick`, `memory_stats`, `memory_obituary`. State
  persists across sessions.
- Citation-based attribution in LLM mode: memory snippets are numbered,
  the model cites which it used, and credit flows to the cited entries
  (even spread over everything consulted is the fallback).
- `decision_polarity` accepts `extra_positive`/`extra_negative` marker
  vocabulary for environments whose actions are not delete/apply.
- Silence diagnostics: per-cycle silent-task counts in `CycleStats` and
  the report summary, plus a plain-language health warning naming the
  two degenerate-run failure modes.
- Benchmarks: `evict_on_negative` (the one-line heuristic; it ties the
  ledger on outcomes in the deterministic environment and the doc says
  so), `survival_embedding` (the loop off the lexical-match path), and
  a paraphrase probe set scored by provenance rather than keywords.
- CI lesson-store integration example and guide
  (`examples/06_ci_lesson_store.py`, docs/integrations/).

### Changed

- README restructured: one-command demo first, an explicit "when to use
  this (and when not)" section, and a guide to the three silent failure
  modes that catch new environments.
- The vocabulary coupling between corpus, environment prompts, and the
  keyword reader is now named plainly in docs/benchmarks.md.
- Demo graveyards no longer label starved poisoned entries as executed.

### Fixed

- `LocalEncoder` dedupes identical QA pairs at encode time, so repeated
  text in a document cannot multiply the population.

## [0.1.0] - 2026-06-11

### Added

- Reflection-QA memory encoding following the MeMo pipeline:
  rule-based `LocalEncoder` (offline) and LLM-driven `ReflectionEncoder`
  (fact extraction, consolidation, self-containment verification,
  entity surfacing, cross-document synthesis).
- Three-stage query protocol (grounding, entity identification, answer
  seeking) with honest provenance: a real deciding entry in local mode,
  even credit across consulted entries in LLM mode.
- Survival loop with energy ledger: upkeep per cycle, credit scaled by
  tanh of the real resource delta along provenance, death at zero, and
  Negative-Space consolidation (merge similar survivors, pool energy,
  record lineage).
- Pluggable retrieval: `LexicalRetriever` (smoothed IDF, relevance
  floor, default), `EmbeddingRetriever` over any `text -> list[float]`
  function, and the zero-dependency `HashingEmbedder` (crc32 character
  n-grams). Vectors persist inside `memory.json`.
- Three environments where the reward is a measured conserved resource:
  `StorageEnv` (real bytes on disk), `TestSuiteEnv` (passing tests in a
  generated micro-project), `VerifiableQAEnv` (exact containment).
- Benchmark harness (`bench/`, stdlib-only): survival vs
  keep-everything, TTL, recency, and rate-matched random eviction,
  plus ablations and a scaling probe. Results in docs/benchmarks.md.
- Hypothesis property tests for the ledger invariants and multi-seed
  robustness tests for poison extinction.
- Five offline examples, including an agent tool-use loop with
  credit-back and the test-suite poison extinction demo.
- Optional LoRA distillation script compressing survivors into a small
  parametric memory model, conditioning on questions only.
- Typed package (`py.typed`, mypy strict), ruff lint and format,
  coverage floor in CI across Python 3.10 to 3.14.

[Unreleased]: https://github.com/rogermsc/darwin-memo/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/rogermsc/darwin-memo/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/rogermsc/darwin-memo/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/rogermsc/darwin-memo/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/rogermsc/darwin-memo/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rogermsc/darwin-memo/releases/tag/v0.1.0
