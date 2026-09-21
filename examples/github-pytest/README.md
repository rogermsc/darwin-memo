# Fixed-evaluation example

Copy this directory into an empty repository. It contains a defect:
`should_retry(401)` returns `True`, which repeats a request that needs different
credentials. The fixed evaluation includes one failing case and two passing cases.
Use Python 3.10 or later and darwin-memo from this checkout. Install the example evaluator:

```bash
python -m pip install pytest==8.4.2
```

1. Initialize and commit the example in your own repository.
2. Run `darwin-memo init --profile github-pytest` at its root.
3. Add the lesson below.
4. Query the lesson below and keep the returned ticket.
5. Bind the ticket using the generated `.darwin-memo/README.md` instructions.
6. Change the function to `return status >= 500`.
7. Commit the task and bound store to your example repository.
8. Run the generated GitHub workflow, or the local evaluation command below.
9. Open the dashboard and select the lesson to inspect the recorded comparison.

```bash
darwin-memo ledger .darwin-memo/memory.json add 'When should an HTTP request retry?' 'Retry server errors (500 and above); do not retry authentication errors such as 401.'
darwin-memo ledger .darwin-memo/memory.json decide 'When should an HTTP request retry?'
```

```bash
darwin-memo task evaluate --ticket TICKET_ID --repository OWNER/REPOSITORY --task TASK_ID --head HEAD --run local-1
darwin-memo ui .darwin-memo/memory.json
```

`TICKET_ID`, `OWNER/REPOSITORY`, and `TASK_ID` must match the binding. `HEAD`
resolves to your task commit. The local command records `operator` provenance;
the generated job records `ci` provenance. Both run the same fixed evaluation.
Expected outcome: one fail-to-pass transition, no regression, delta `1`, and
three cases in each report. This demonstrates settlement, not cost savings or
causal evidence that the lesson produced the fix.

To observe abstention, create a separate task whose code cannot be imported.
To observe zero improvement, bind another ticket to the fixed commit and compare
it with an unchanged commit. Do not modify the evaluation to manufacture credit.
