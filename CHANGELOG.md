# Changelog

All notable changes to this project are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project uses [SemVer](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-06-10

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

[Unreleased]: https://github.com/rogermsc/darwin-memo/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/rogermsc/darwin-memo/releases/tag/v0.1.0
