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

## Shipped: `openclaw-memory-darwin` (the memory-slot plugin)

[openclaw-memory-darwin](https://www.npmjs.com/package/openclaw-memory-darwin)
claims OpenClaw's memory slot (`plugins.slots.memory`, one active at
a time) and replaces curation with selection. Install by name:

```bash
pipx install darwin-memo            # the ledger CLI the plugin drives
openclaw plugins install openclaw-memory-darwin
```

Zero npm dependencies; targets host 2026.3.24; verified end to end by
installing the published package by bare name into a real gateway
(slot claimed from memory-core, plugin registered, doctor clean).
Source: github.com/rogermsc/openclaw-memory-darwin.

- `memory_recall` calls `decide()` through the `darwin-memo ledger`
  CLI, opening a ticket keyed by the session (OpenClaw's `agent_end`
  carries no run id, so the session key is the correlation unit).
- The `agent_end` hook settles every ticket the session opened with
  the measured outcome (configurable success/failure deltas).
  Settlement is measured rather than self-reported, which no other
  OpenClaw memory plugin does. Tickets older than `maxTicketAgeHours`
  are abandoned rather than inheriting a later run's outcome, and
  failed settlements re-queue instead of stranding escrow.
- A background service runs `tick()` on a persisted cadence that
  survives gateway restarts; `memory_store`/`memory_forget` round out
  the slot (forget honors ledger escrow and says so).
- The bridge is the `darwin-memo ledger` CLI, one short-lived process
  per operation with a JSON object on stdout, serialized client-side
  to respect the CLI's single-writer contract. (The original plan
  said "the MCP stdio server as a child process"; ground truth
  changed it: OpenClaw's plugin SDK ships no MCP client, so the CLI
  keeps both sides dependency-free.)

Honest note on the delta semantics, also stated in the plugin's own
README: a success boolean is a weaker conserved resource than bytes
or passing tests. The default mapping (+1 success, -1 failure) is
configurable, and lessons that keep being recalled into failing runs
die on their own.
