# OpenClaw

OpenClaw (github.com/openclaw/openclaw) is the self-hosted personal AI
assistant. Its memory today is markdown files plus hybrid search, and
its own tracker documents the gap darwin-memo exists for: memory grows
without guardrails, nothing ever dies, and `memory_search` gets noisier
as the corpus grows (issues #42877, #50096, #43747). OpenClaw has no
notion of which memories earn their keep. darwin-memo is exactly that
notion.

## Today: mount over MCP (no new code)

OpenClaw treats MCP servers as first-class tools. With darwin-memo
installed (`pipx install "darwin-memo[mcp]"`):

```bash
openclaw mcp add darwin-memo
```

then configure the server entry (Control UI at `/mcp`, or
`~/.openclaw/openclaw.json` under `mcp.servers`):

```json
{
  "command": "darwin-memo-mcp",
  "args": ["--memory", "~/.openclaw/workspace/darwin-memo.json"]
}
```

Verify with `openclaw mcp doctor --probe`: the tools `memory_query`,
`memory_settle`, `memory_add`, `memory_tick`, `memory_stats`, and
`memory_obituary` should list. Tell the agent how to use them (in your
`MEMORY.md` or a skill): query at task start, keep the ticket id, and
when the task's outcome is measurable, settle the ticket with the
measured delta. `memory_tick` belongs in a daily cron job.

Two caveats with this shape:

- Settlement is model-discretionary: the agent must remember to call
  `memory_settle`, and the delta is self-reported. That is weaker than
  darwin-memo's design wants, which is what the plugin below fixes.
- darwin-memo state survives OpenClaw retiring idle MCP processes,
  because everything persists to the JSON file after each call.

## Planned: `openclaw-memory-darwin` (the memory-slot plugin)

OpenClaw's memory is a swappable plugin slot (`plugins.slots.memory`,
one active at a time; `memory-lancedb` and the mem0 bridge are working
precedents). The plan, tracked in the repo issues:

- A thin TypeScript plugin claims the slot: `memory_recall` calls
  `decide()` (opening a ticket keyed by `ctx.runId`), `memory_store`
  calls `memory_add`, `memory_forget` retires an entry.
- The plugin listens on OpenClaw's `agent_end` hook, which carries a
  success boolean and run duration, and settles the run's tickets
  automatically from those measurements, optionally weighted by
  `after_tool_call` errors and `message_sent` delivery failures during
  the run. Settlement becomes measured rather than self-reported,
  which no other OpenClaw memory plugin does.
- A background cron calls `tick()`; obituaries surface in chat on
  request.
- The bridge to Python is the `darwin-memo ledger` CLI, one
  short-lived process per operation with a JSON object on stdout.
  (The original plan said "the MCP stdio server as a child process";
  ground truth changed it: OpenClaw's plugin SDK ships no MCP client,
  so the CLI keeps both sides dependency-free.)

Honest note on the delta semantics: a success boolean is a weaker
conserved resource than bytes or passing tests. The default mapping
(+1 success, -1 failure, scaled by recalls in the run) will be
configurable and stated in the plugin docs, not hidden.
