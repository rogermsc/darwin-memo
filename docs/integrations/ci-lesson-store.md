# A CI-settled lesson store for coding agents

The most credible production fit for darwin-memo: a per-repo store of
lessons an autonomous coding agent has learned, where the CI suite is
the conserved resource that settles every decision. Lessons that keep
shipping green survive. Lessons that keep breaking builds die. Nobody
reviews the store.

`examples/06_ci_lesson_store.py` runs the full cycle offline. This page
is the wiring for the real thing.

## Quickstart: the settle-ci subcommand

Run your suite with junit XML at the base commit and at the head or
merge commit (`pytest --junitxml base.xml`, then `head.xml`; most CI
setups archive these already), then settle in one step:

```yaml
- name: Settle memory tickets
  if: always()
  env:
    PR_BODY: ${{ github.event.pull_request.body }}
  run: |
    darwin-memo settle-ci .darwin-memo/lessons.json \
      --base-xml base.xml --head-xml head.xml \
      --scale 2.0 --detail "$GITHUB_RUN_ID"
```

`settle-ci` diffs the two reports per test id and settles every
`darwin-memo-ticket: <id>` line in `PR_BODY` with the measured delta:
a pass that became a fail is a regression, a fail that became a pass
is an improvement, and added or removed tests are attributed as suite
changes instead of smearing into a raw count. **When a ticket was
present, and only then**, one tick runs (upkeep, expiry, consolidation);
the store is saved either way. One JSON object on stdout reports the
transitions and what landed, with `"tick": null` on a merge that carried
no ticket.

That condition is load-bearing, and this repo learned it the hard way.
A tick charges every living entry upkeep, so ticking on a merge that
carried no ticket bills the store for time in which it was never given a
chance to earn. Credit is capped at `max_energy`, so no entry outlives
`max_energy / upkeep` such ticks however valuable it is, and one that
never earned starts at spawn energy and gets only `spawn / upkeep` — 20
ticks at the defaults. This repo's own lesson store went extinct exactly
that way: 49 consecutive settlement-free ticks, one per merged PR,
including an entry that had earned +0.600 from a measured +19 test-pass
delta. `darwin-memo doctor` now reports this as
`ticking_without_evidence`.

The cost of the fix, stated plainly: **expiry and consolidation now
advance in settled ticks rather than in merges.** That is the cadence
the energy economy already assumes. A *dropped* settle still counts as
evidence — an unknown ticket id, or a silent decide that never opened a
ticket, is still the caller reporting on the world, and requiring credit
instead would make a store whose retrieval has gone mute immortal.

Three hardenings ride along:

- **Infra failures abstain.** A run with no parseable junit XML, zero
  collected tests, or a collection error measured nothing, so settling
  it at zero would be a lie. settle-ci leaves the store untouched,
  says why on stderr, and exits with code 3 so the broken measurement
  surfaces instead of silently becoming a fake delta.
- **Flaky tests quarantine themselves.** Per-test flip history lives
  in `flaky.json` next to the store; a test that flips direction three
  times inside a ten-observation sliding window is excluded from
  deltas until the flips slide out (tune with `--window` and
  `--flip-threshold`). Quarantined tests are reported in the output,
  never settled. Commit the state file alongside the store so the
  quarantine survives between runs.
- **A degraded fallback exists** for ecosystems without junit XML:
  `--passes-before N --passes-after N` diffs raw pass counts. Both
  numbers are required; never default a missing count to zero. The
  fallback has no per-test attribution, no quarantine, and no infra
  detection, which is why it is the fallback.

A reusable GitHub Action wrapping the whole measure/settle/commit
dance (`rogermsc/darwin-memo-action`) is coming next; until then,
`.github/workflows/memory.yml` in this repo is the copyable reference
for producing the two reports and committing the store back.

## This repo runs it on itself

darwin-memo dogfoods the integration. `.darwin-memo/lessons.json` is
this repo's own store, seeded with real lessons from its development
(`.darwin-memo/seed.py` lists them); `.github/workflows/memory.yml`
runs `darwin-memo settle-ci` on every merged PR with junit XML from
the base and merge commits, and commits the curated store back to
main. The loop for an agent working on this repo:

```bash
python -c "
from darwin_memo import Ledger
ledger = Ledger.load('.darwin-memo/lessons.json', resource_scale=2.0)
ticket = ledger.decide('Are LLM benchmark arms safe to run in CI?')
print(ticket.answer); print('ticket:', ticket.id)
ledger.save('.darwin-memo/lessons.json')
"
```

Act on the answer, commit the store (the open ticket ships with the
PR), and add one line to the PR body:

```
darwin-memo-ticket: <id>
```

The merge workflow settles it with the per-test delta. If you do not
act on the answer, abandon the ticket instead so its escrow releases.
The first tickets through this loop were decisions in the PRs that
built it, including one about the workflow's own concurrency group.

## The shape

```
PR opens
  agent consults memory  ->  ledger.decide(question)   [ticket opened]
  agent acts (or not)
  CI finishes            ->  darwin-memo settle-ci     [per-test delta lands]
end of run               ->  one tick, IF one settled  [upkeep, deaths, merges]
```

The delta is `passing tests gained minus passing tests lost`, computed
per test id and measured by the CI run itself. It is a measurement;
resist every temptation to pass a review score, a vibe, or an LLM's
opinion instead, because the moment you do, the no-judge property and
everything downstream of it is gone.

## Wiring it into the agent

```python
from darwin_memo import Ledger

store_path = ".darwin-memo/lessons.json"
ledger = Ledger.load(
    store_path, resource_scale=2.0, event_log=".darwin-memo/events.jsonl"
)

# Before acting on anything memory might know about:
ticket = ledger.decide("Is the dedupe helper in pkg/util safe to remove?")
if ticket.answer:
    ...  # let the answer inform the change; record ticket.id with the PR
ledger.save(store_path)  # the open ticket must survive this process

# Settlement and ticking belong to CI: `darwin-memo settle-ci` does
# both from the junit XML when the PR merges.
```

If the agent speaks MCP, the decide call is the `memory_query` tool of
`darwin-memo-mcp`, and the ticket id travels in the tool results.

## The trust boundary: who may settle a ticket

In a public repository the PR body is attacker-influenced, and open ticket
ids are readable in the committed store. Without a check, a merged PR could
paste someone else's in-flight ticket id and settle their decision at a delta
whose sign it chooses -- adding trivial passing tests to crown an entry that
earned nothing, or removing tests to bury one as damaged. **Open ticket ids
are not capabilities.** A store you publish leaks every id in it.

`settle-ci` closes this with `--opened-since`, pointing at the store as it was
at the base commit. A legitimate ticket is opened by `decide()` writing it
into the store, which the PR then commits -- so a ticket that was already
pending at the base was opened by someone else, and this run refuses it:

```bash
# check out the base-commit copy of the store to a temp path...
git show "$BASE_SHA:.darwin-memo/lessons.json" > /tmp/base-store.json
darwin-memo settle-ci .darwin-memo/lessons.json \
  --base-xml /tmp/base.xml --head-xml /tmp/head.xml \
  --opened-since /tmp/base-store.json
```

Refused ids appear in the output under `refused_not_opened_here`, and the run
settles only what it opened. Without `--opened-since`, the output carries
`"ticket_provenance": "unverified"` -- settlement still happens, but the run
is telling you it could not check provenance. Pass it.

Two related notes:

- **Fork PRs.** GitHub caps the token to read-only for pull requests from
  forks regardless of the `permissions:` block, so a settle step that pushes
  the store back to the default branch fails on a merged fork PR -- and a
  legitimate ticket in that PR settles only inside the discarded runner, never
  landing. If you accept outside contributions, trigger settlement on `push`
  to the default branch (or `workflow_run` from a trusted branch) and resolve
  the merged PR through the API, so the token is always the base repo's and
  the PR body is fetched from a trusted context rather than injected.
- **The flaky sidecar is untrusted too.** If you commit `flaky.json`, the PR
  being measured can author it. A malformed sidecar now regenerates to empty
  history rather than crashing settlement, and a bogus quarantine entry a PR
  wrote to hide its own regression is lost with it -- but the cleaner posture
  is to keep the sidecar out of the repo, in an Actions artifact the PR
  cannot write.

## What to watch out for

- **Flaky tests poison the signal.** The quarantine handles the
  repeat offenders, and the tanh damping means one flake does not
  execute a proven lesson, but a brand-new flake's first flip still
  lands on whatever tickets are open. Smaller windows quarantine
  faster at the cost of sidelining honest fixes for longer.
- **Suites evolve.** Per-test diffing attributes added and removed
  tests instead of letting them shift the baseline, but a PR that
  deletes failing tests still moves the delta; that is a review
  problem, not a measurement problem.
- **Bundled changes blur attribution.** One PR carrying ten decisions
  settles ten tickets with the same delta. Smaller PRs mean cleaner
  selection signal; this mirrors how the credit works inside the loop.
- **Escrow protects in-flight verdicts.** Entries named by unsettled
  tickets cannot be buried or merged, and tickets expire at delta zero
  after `expire_after` ticks if CI never reports back.
- **Concurrency.** The store is a single JSON file with no locking. One
  settler at a time: settle from a single queue consumer or a
  serialized Actions workflow, not from parallel jobs.

## Appendix: the manual settlement step

Before settle-ci, this was the pattern: harvest pass counts yourself
and settle through the Python API. It still works where you cannot
install the CLI, with two warnings. Counting passes in shell invites
the `|| echo 0` bug, where a run that crashed before reporting reads
as zero passes and settles a violent fake delta; if you cannot produce
a real count, skip settlement entirely. And raw counts cannot tell a
regression from a removed test, which is why per-test diffing replaced
them.

One consequence worth knowing before you point this at a suite with
environment-gated tests, which is most suites. A `skipped` test measured
nothing, so it is treated as unmeasured rather than as failing: it enters
no transition, accrues no flake history, and cannot be quarantined. That
matters most in the direction people do not expect --- when a test skips
at base because an extra was missing and passes at head because it landed,
the delta stays zero rather than crediting a lesson for an outcome it did
not cause. An *absent* test is a different thing and still counts against
you, because deleting a passing test is a real loss.

```yaml
- name: Settle memory tickets
  if: always()
  run: |
    python - <<'PY'
    import os, re
    from darwin_memo import Ledger

    ledger = Ledger.load(".darwin-memo/lessons.json", resource_scale=2.0)

    body = os.environ.get("PR_BODY", "")
    tickets = re.findall(r"darwin-memo-ticket: (\w+)", body)
    delta = int(os.environ["PASSES_AFTER"]) - int(os.environ["PASSES_BEFORE"])
    for ticket_id in tickets:
        ledger.settle(ticket_id, float(delta), detail=os.environ.get("RUN_URL", ""))
    ledger.tick()
    ledger.save(".darwin-memo/lessons.json")
    PY
  env:
    PR_BODY: ${{ github.event.pull_request.body }}
    RUN_URL: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
```

Getting `PASSES_BEFORE` and `PASSES_AFTER` is suite-specific; the
simplest robust form is running pytest on the base ref and the head
ref with `--junitxml` in earlier steps, which is also exactly the
input settle-ci wants, so prefer the subcommand.
