# Changelog

All notable changes to this project are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project uses [SemVer](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/rogermsc/darwin-memo/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/rogermsc/darwin-memo/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/rogermsc/darwin-memo/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rogermsc/darwin-memo/releases/tag/v0.1.0
