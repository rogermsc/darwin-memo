# darwin-memo

**Measured memory for coding agents.** Keep repository lessons, connect them to
reported task outcomes, and inspect why each lesson stays or is removed.

Start with Python projects using pytest, GitHub Actions, and an MCP client.
The core uses only the Python standard library. MCP support is an optional extra.

The product goal is lower total operating cost while preserving task success.
That benefit is **not established** by the committed experiments. A smaller
memory store or a larger energy balance is not a savings measurement.

## See the mechanism in 60 seconds

From this reviewed checkout:

```bash
python -m pip install -e .
darwin-memo demo --out /tmp/darwin-demo.json
darwin-memo ui /tmp/darwin-demo.json
```

The demo uses a filesystem-backed simulation: file deletion uses file size, and
protected-file recreation incurs a **modeled** penalty of three times that size.
It does not measure restoration scratch space, I/O cost, or money. Open a lesson
in the dashboard to inspect its settlements and removal reason.

To try the coding workflow with a real failing evaluation, use the
[fixed pytest example](examples/github-pytest/README.md). Its authentication-retry
defect changes one fixed case from failure to success. The example demonstrates
settlement; it does not establish that memory caused the fix.

## Install the development workflow

The `init` and `task` commands in this checkout are unreleased. Install them from
the reviewed checkout on Python 3.10 or later:

```bash
python -m pip install -e '.[mcp]'
```

Build the dashboard from this checkout before packaging it:

```bash
npm ci --prefix ui
npm run build --prefix ui
```

Persistence requires POSIX advisory locks on a local filesystem. Windows and
shared network stores are unsupported; the package refuses lockless persistence.

## Connect one repository

1. Run `darwin-memo init --profile github-pytest` at your repository root.
2. Configure your MCP client using `.darwin-memo/mcp.example.json`.
3. Add a repository lesson and query memory before a task.
4. Bind the returned ticket to the repository, task, base commit, and fixed evaluation.
5. Complete the task and commit the bound store with your changes.
6. Run the generated GitHub Actions workflow against that task commit.
7. Download its outcome artifact and carry the accepted store forward.
8. Open the dashboard to inspect the reported outcome and retained lesson.

The [GitHub pytest guide](docs/integrations/github-pytest.md) includes setup
requirements and the [generated operating instructions](darwin_memo/data/github-pytest/.darwin-memo/README.md).
`init` refuses overwrites and changes no global agent settings. The recommended
MCP configuration exposes query, add, and inspection while reserving settlement
and retention mutations for the host. It reduces accidental self-awarded credit;
it does not protect against a malicious actor with write access to the store,
evaluation, or workflow.

The workflow compares the **same base evaluation** at both commits. Added passing
tests earn no credit. Green-to-green results earn zero. Missing observations or
infrastructure failures abstain and leave the ticket pending. Bound settlements
record repository, task, commit, run, evaluation fingerprint, and report hashes.
Process one task at a time: independent Git snapshots do not merge.

## Understand retention

A query retrieves lessons and opens a ticket. A later outcome moves the consulted
lessons' bounded energy balances. Ticks charge upkeep; entries that reach the
floor are removed, and similar entries can merge. Pinning exempts a lesson from
removal and consolidation. [The glossary](docs/glossary.md) explains the terms.

Settlement **associates** outcomes with consulted lessons. It does not establish
causation. Passing tests are observable outcomes, not physically conserved
resources. `ci`, `operator`, and `agent` identify reporting paths. Historical
`measured` labels are caller claims; absent provenance is unknown. None of these
labels authenticates a report by itself.

CLI, dashboard, and MCP mutations lock the full load–modify–save operation. MCP
reloads on each call, cached embeddings survive unrelated writes, and stale
Python writers are rejected. Retry the whole operation after contention. See
[the store format](docs/store-format.md) and [API reference](docs/api.md).

## Inspect the evidence

| Question | Evidence | What it supports |
|---|---|---|
| What happens under corrupted feedback? | [Central attack-table reconstruction](paper/reproduce.md), [committed observations](bench/results/adversary.json) | A controlled simulated comparison with a modeled restoration penalty, including failure boundaries |
| Does a tuned counter compete? | [Counter sweep](bench/results/counter_sweep.json), [paper](paper/sections/experiments.tex) | Negative findings for universal superiority; tuned forgiveness can retain useful memory under small attack budgets |
| Does memory reduce total coding cost while preserving success? | [Prospective protocol](docs/research/measured-memory-protocol.md) | An unanswered question; historical results lack the required complete cost comparison and noninferiority evidence |
| Can users complete and retain the workflow? | [Pilot and release record](docs/release-readiness.md) | Pending external observation; no fabricated adoption counts |

Reconstruct the paper's central table without an installation or network:

```bash
python tools/reconstruct_paper.py
```

The paper, *Attacking the Curator*, focuses on the feedback-corruption threat
model, curator comparisons, and a reusable reproduction artifact. Historical
replays remain replays. Read the [claim audit](paper/claim-audit.md),
[reproduction paths](paper/reproduce.md), and [submission status](paper/submission-notes.md).

## Limitations and participation

Memory can be harmful, useful lessons can starve, and an attacker who controls
enough outcome reports can control retention. A fixed evaluation can still be
incomplete or gameable. [The threat model](docs/threat-model.md) defines the boundary.
If no memory performs best in the cost study, the release will report that result.

Other [integrations](docs/README.md) remain available; the GitHub pytest profile
is the supported first-release path. Report setup failures with the
[diagnostic issue template](.github/ISSUE_TEMPLATE/setup-failure.yml), or choose a
[bounded contributor task](CONTRIBUTING.md). Release promotion, participant
contact, paid experiments, and submission remain separate authorized actions.
