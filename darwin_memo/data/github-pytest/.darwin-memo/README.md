# Repository memory

Use Python 3.10 or later on a POSIX local filesystem. The profile supports
pytest evaluations with imports from the repository root and dependencies
installed in the evaluation environment. Add project dependencies to the CI
installation step. It does not install or infer project dependencies.

1. Install `darwin-memo[mcp]` from the reviewed release or checkout.
2. Replace `REPOSITORY_PATH` in `mcp.example.json` with your absolute repository path.
3. Copy that server definition into your repository-local MCP configuration.
4. Commit the generated setup to your default branch so GitHub can dispatch the workflow.
5. Add a lesson with `darwin-memo ledger .darwin-memo/memory.json add 'QUESTION' 'ANSWER'`.
6. Query memory through MCP before your task and retain the returned ticket.
7. Bind the ticket before changing the evaluation with the command below.
8. Complete your task and commit its changes, including the store with its binding.
9. Dispatch **Settle memory from a fixed evaluation** with the task commit, ticket, and task identity.
10. Download the outcome artifact and inspect `outcome/report.json` and both logs.
11. Replace the local store with the artifact's store while no agent uses it.
12. Open `darwin-memo ui .darwin-memo/memory.json` to inspect the lesson and its evidence.

```bash
darwin-memo task bind --ticket TICKET_ID --repository OWNER/REPOSITORY --task TASK_ID --base BASE_COMMIT --evaluation tests
```

`TICKET_ID` is the query result. `OWNER/REPOSITORY` is your GitHub repository.
`TASK_ID` identifies the issue or task. `BASE_COMMIT` is the commit before the fix.
The evaluation directory must exist in that commit. Keep the store outside the
evaluation directory. Configure repository variable `DARWIN_MEMO_REVISION` with
the full reviewed darwin-memo commit SHA before dispatching the workflow.

The job copies exactly the base evaluation into temporary base and head
checkouts. It disables automatic pytest plugin loading and ignores repository
pytest configuration, inherited pytest options, and conftest files outside the
frozen evaluation. Projects that require plugins or pytest configuration
need an explicitly reviewed evaluation runner before using this profile.
For namespace or `src/` layouts, provide the required imports in the evaluation
or adapt the runner; this profile targets root-importable Python projects.

Only shared fail-to-pass transitions earn credit. Green-to-green comparisons
produce zero. Added or removed tests in the task commit do not affect the fixed
evaluation. The task report lists head evaluation file additions, removals,
and modifications separately, without running or crediting them. `settle-ci` reports suite changes separately for existing integrations.
Missing reports, collection failures, mismatched test IDs, and all-skipped runs
abstain without changing the store. An abstention keeps the ticket pending.

Process one task at a time through artifact download. GitHub concurrency
serializes jobs, but independent store snapshots do not merge. Repeating a job
from the original commit creates a separate copy; it does not update the accepted
store. Always carry the accepted store forward before starting another task.
Duplicate deliveries against that store and mismatched identities are rejected.

The MCP example exposes query, add, and inspection tools. It reserves settlement
and retention controls for the host. This reduces accidental self-awarded credit;
it does not defend against someone who can write the store, evaluation, runner,
or workflow. The CI source label identifies the reporting path, not a signature
or proof that the consulted lesson caused the outcome. A failing fixed evaluation
is required to demonstrate improvement; do not invent a reward for green runs.
