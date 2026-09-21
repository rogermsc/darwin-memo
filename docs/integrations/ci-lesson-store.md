# CI lesson store

For repository-bound settlement, use the [GitHub pytest profile](github-pytest.md).
It freezes evaluation bytes from the base commit, compares them at both revisions,
and records task/run identity. It is the supported adoption path.

## Existing JUnit integrations

`settle-ci` remains available for callers that already produce JUnit reports:

```bash
darwin-memo settle-ci MEMORY_PATH --base-xml BASE_XML --head-xml HEAD_XML --opened-since BASE_STORE --pr-body 'darwin-memo-ticket: TICKET_ID'
```

`MEMORY_PATH` is the destination store. `BASE_XML` and `HEAD_XML` are reports.
`BASE_STORE` is the store from the base commit. `TICKET_ID` is the pending ticket's
12-character hexadecimal ID. The command rejects tickets already pending in
`BASE_STORE`, but this check does not bind a report to a repository, task, commit,
or run. The PR body and report paths are caller-supplied, so provenance remains
unverified. A `ci` source label identifies this reporting path, not authentication.

Credit is the count of shared fail-to-pass transitions minus shared pass-to-fail
transitions. Added and removed tests appear in separate output fields and do not
change credit. Green-to-green runs yield zero. Skipped cases are unmeasured.
Missing or invalid reports, collection failures, zero measured cases, and
all-skipped reports abstain with exit code `3` and leave the store untouched.
The retained flip history can quarantine unstable cases; an attacker with write
access to the store or sidecar is outside this configuration's protection.

The deprecated-quality fallback `--passes-before`/`--passes-after` accepts raw
counts. It cannot distinguish suite changes or establish stable evaluation
identity. It remains for compatibility; do not use it for advertised comparisons.
Never turn a missing count into zero or invent positive credit for a green run.

Only a landed settlement advances the clock. A duplicate or unknown ticket
cannot trigger upkeep. All CLI mutations hold the local file lock across load,
change, and save. Retry the entire command after contention.

The repository's historical `.github/workflows/memory.yml` uses the published
external action and evolving suites. It is retained as historical integration
wiring, not presented as equivalent to the fixed-evaluation profile. Do not infer
product cost savings or causal lesson value from its accumulated balances.
