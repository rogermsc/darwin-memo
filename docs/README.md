# darwin-memo documentation

Start with the [project README](../README.md) for the pitch, the
demo, and the quickstart. This index is everything else.

## Operating it

- **[Tuning guide](tuning.md)**: the load-bearing knobs (upkeep,
  resource_scale, credit_gain, merge_threshold, expire_after, the
  retrieval floors), what each does mechanically, failure symptoms in
  both directions, and evidence-backed starting points for CI lesson
  stores, coding-agent lesson stores, and generic agent memory.
- **[API reference](api.md)**: the public Python surface with real
  signatures, the CLI subcommands, the MCP tools, and every raised
  exception (including `StoreLockedError`).
- **[Store format](store-format.md)**: the on-disk JSON format field
  by field, the events JSONL log and its rotation, the lock and
  flaky-test sidecars, and the honest compatibility policy.

## Understanding it

- **[Benchmarks](benchmarks.md)**: three survival arms vs five
  baselines across seeds, ablations, the noisy-measurement forgiveness
  suite, scaling measurements, the pre-committed SWE-Bench-CL
  learning-curve pilot protocol, and the caveats on the record. Every
  committed number reproduces from `bench/`.
- **[Paper-to-code map](paper-to-code.md)**: every concept borrowed
  from MeMo and the survival paper, where it lives in the code, and
  where the implementation deviates and why.
- **[Launch post](launch-post.md)**: the story of why this exists.

## Integrations

- **[CI lesson store](integrations/ci-lesson-store.md)**: the primary
  production shape, lessons settled by CI pass deltas; this repo runs
  it on itself.
- **[Claude Code](integrations/claude-code.md)**: `darwin-memo render`
  projects the store into the auto-memory `MEMORY.md` Claude Code
  reads at session start, capped to its 200-line / 25KB ceiling.
- **[OpenAI Agents SDK](integrations/openai-agents.md)**:
  `DarwinMemoSession`, a faithful Session for the transcript plus an
  opt-in lesson layer settled by measured outcomes.
- **[OpenClaw](integrations/openclaw.md)**: mount over MCP or claim
  the memory slot with the plugin.
- **[Hermes](integrations/hermes.md)**: Hermes models through the
  Ollama client, Hermes Agent over MCP.
- **[Animoca Minds / EVM](integrations/animoca-minds.md)**: on-chain
  balance deltas as judge-free settlement signals.

## Contributing

- [CONTRIBUTING.md](../CONTRIBUTING.md), [CHANGELOG.md](../CHANGELOG.md),
  [SECURITY.md](../SECURITY.md).
