# Measured-memory release draft

- Preserve cached embeddings during lexical CLI, MCP, and dashboard writes.
- Lock complete mutations, reload MCP state for every call, and reject stale writers.
- Refresh dashboard lesson details and display refused mutation outcomes.
- Add repository-local `github-pytest` initialization and bound fixed evaluations.
- Reserve settlement for CI in the recommended MCP configuration.
- Credit shared test transitions only; added tests and green-to-green runs earn no improvement credit.
- Retain settled run identities beyond lesson-history rotation; distinguish expiry from observed zero outcomes.
- Record source and optional outcome evidence; show historical missing provenance as unknown.
- Correct storage simulation and causal-attribution claims without rewriting historical data.
- Add offline reconstruction of the central paper table and provider-usage instrumentation.

Compatibility: public core calls remain available, with optional evidence and
binding metadata. Persistence without POSIX locking is refused. `settle-ci`
changes suite-change credit semantics. Python settlement defaults to unknown
provenance. The profile and study remain unreleased pending review and pilots.
