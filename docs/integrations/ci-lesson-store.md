# A CI-settled lesson store for coding agents

The most credible production fit for darwin-memo: a per-repo store of
lessons an autonomous coding agent has learned, where CI pass counts
are the conserved resource that settles every decision. Lessons that
keep shipping green survive. Lessons that keep breaking builds die.
Nobody reviews the store.

`examples/06_ci_lesson_store.py` runs the full cycle offline. This page
is the wiring for the real thing.

## The shape

```
PR opens
  agent consults memory  ->  ledger.decide(question)   [ticket opened]
  agent acts (or not)
  CI finishes            ->  ledger.settle(ticket_id, passes_after - passes_before)
end of run               ->  ledger.tick()             [upkeep, deaths, merges]
```

The delta is `tests passing after the change minus before`, measured by
the CI run itself. It is a measurement; resist every temptation to pass
a review score, a vibe, or an LLM's opinion instead, because the moment
you do, the no-judge property and everything downstream of it is gone.

## Wiring it into the agent

```python
from darwin_memo import Ledger, MemoryStore

store_path = ".darwin-memo/lessons.json"
store = MemoryStore.load(store_path)
ledger = Ledger(store, resource_scale=2.0, event_log=".darwin-memo/events.jsonl")

# Before acting on anything memory might know about:
ticket = ledger.decide("Is the dedupe helper in pkg/util safe to remove?")
if ticket.answer:
    ...  # let the answer inform the change; record ticket.id with the PR

# In the CI completion handler (webhook, Actions step, queue consumer):
ledger.settle(ticket_id, delta=passes_after - passes_before, detail=run_url)
store.save(store_path)

# Once per merged PR, or nightly:
ledger.tick()
store.save(store_path)
```

If the agent speaks MCP, the same three calls are the `memory_query`,
`memory_settle`, and `memory_tick` tools of `darwin-memo-mcp`, and the
ticket id travels in the tool results.

## A GitHub Actions settlement step

Persist `.darwin-memo/` in the repo (or a cache/artifact), record the
ticket id in the PR body or a commit trailer when the agent acts, then
settle when the suite finishes:

```yaml
- name: Settle memory tickets
  if: always()
  run: |
    python - <<'PY'
    import os, re, subprocess
    from darwin_memo import Ledger, MemoryStore

    store = MemoryStore.load(".darwin-memo/lessons.json")
    ledger = Ledger(store, resource_scale=2.0)

    body = os.environ.get("PR_BODY", "")
    tickets = re.findall(r"darwin-memo-ticket: (\w+)", body)
    delta = int(os.environ["PASSES_AFTER"]) - int(os.environ["PASSES_BEFORE"])
    for ticket_id in tickets:
        ledger.settle(ticket_id, float(delta), detail=os.environ.get("RUN_URL", ""))
    ledger.tick()
    store.save(".darwin-memo/lessons.json")
    PY
  env:
    PR_BODY: ${{ github.event.pull_request.body }}
    RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
```

Getting `PASSES_BEFORE` and `PASSES_AFTER` is suite-specific; the
simplest robust form is running pytest on the base ref and the head ref
with `--json-report` (or parsing `-q` output) in earlier steps.

## What to watch out for

- **Flaky tests poison the signal.** A flaky failure settles a good
  lesson negatively. The tanh damping means one flake does not execute
  a proven lesson, but quarantine known-flaky tests from the count.
- **Suites evolve.** Tests added in the same PR shift the baseline; the
  before/after must run on the same suite definition. Diffing
  pass/fail per test id is sturdier than raw counts.
- **Bundled changes blur attribution.** One PR carrying ten decisions
  settles ten tickets with the same delta. Smaller PRs mean cleaner
  selection signal; this mirrors how the credit works inside the loop.
- **Escrow protects in-flight verdicts.** Entries named by unsettled
  tickets cannot be buried or merged, and tickets expire at delta zero
  after `expire_after` ticks if CI never reports back.
- **Concurrency.** The store is a single JSON file with no locking. One
  settler at a time: settle from a single queue consumer or a
  serialized Actions workflow, not from parallel jobs.
