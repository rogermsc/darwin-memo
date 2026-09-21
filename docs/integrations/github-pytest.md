# GitHub pytest workflow

Use this profile for root-importable Python projects, pytest, GitHub Actions,
and an MCP client. Run from your repository root:

```bash
darwin-memo init --profile github-pytest
```

The command generates a repository-local store, an MCP configuration example,
a workflow, and complete operating instructions in `.darwin-memo/README.md`.
It refuses to overwrite any target and does not modify global client settings.
The workflow pins a reviewed darwin-memo commit through repository variable
`DARWIN_MEMO_REVISION`; this development checkout must be released or pushed
before a hosted runner can install its revision.

Follow the [reproducible defect example](../../examples/github-pytest/README.md)
to experience a meaningful fail-to-pass settlement. See the
[generated instructions](../../darwin_memo/data/github-pytest/.darwin-memo/README.md)
for the complete query, bind, task, CI, artifact, and dashboard sequence.

The supported profile runs the evaluation from the bound base commit against
both revisions. It records repository, task, ticket, base/head commits, run,
evaluation fingerprint, and report hashes. It rejects duplicate or mismatched
tickets and abstains on missing observations. A green-to-green result earns zero.
The recommended MCP profile does not expose arbitrary settlement or retention
changes to the agent. File writers and workflow editors remain trusted.

Run one task at a time and carry the accepted artifact store into the next task.
Parallel jobs serialize, but independent Git snapshots do not merge. GitHub's
[concurrency behavior](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
does not make artifacts a shared database.

`settle-ci` remains available for older integrations. It reports added/removed
tests separately and credits only shared test transitions. Its raw-count fallback
and caller-supplied JUnit reports do not establish repository/run identity. Use
`task evaluate` for the supported bound workflow. Source labels report provenance;
they do not authenticate arbitrary callers or establish lesson causation.
