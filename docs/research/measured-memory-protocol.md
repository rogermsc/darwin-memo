# Prospective cost and success protocol

Status: protocol draft; no calibration or held-out paid run is authorized or
executed by this implementation. Historical results remain under their recorded
configurations. Do not describe this draft as a frozen preregistration.

## Questions and budget

The product question is whether memory lowers total operating cost while
preserving issue-resolution success. The security question is how retention
behaves under corrupted feedback. Keep those results separate.

The total spending cap is $500: $50 calibration, $350 primary comparisons, and
$100 reruns or independent replication. Include API requests, retries (including
uncertain billing), lesson generation, and paid execution infrastructure.
Unknown costs remain unknown; they are not zero. Stop rather than exceed a
stage's cap. No paid run starts until the operator authorizes it and sets a
provider-side spending limit.

## Freeze before held-out evaluation

1. Select disjoint development and held-out task IDs before viewing held-out outcomes.
2. Pin dataset bytes and revision, repository revisions, model identifier and provider, prompt files, retrieval settings, and task order by SHA256.
3. Tune all four methods on the development set under the same tuning budget.
4. Calibrate the total cost of a complete task, including retries and execution.
5. Choose an equal sequence length for all arms from the calibrated budget.
6. Freeze the manifest, calibration ledger, analysis code revision, and checksums before requesting any held-out model response.

Use three repository sequences and three repeated runs when calibration permits.
Reduce sequence length equally across arms to fit $350. If that leaves too few
sequence/run units, retain the budget and label the result underpowered. Select
length from calibration cost, never from held-out outcomes. Record any deviation
before continuing.

The four arms in `bench/swebench_cl/arms.py` are:

- `memory_off`: no memory.
- `keep_everything`: relevance retrieval without deletion.
- `forgiveness_counter`: consecutive negative outcomes remove an entry at a development-tuned threshold; positive outcomes reset the counter, and zero outcomes leave it unchanged.
- `memory_on`: darwin-memo with development-tuned retention parameters.

Use `--memory-budget` for an equal maximum memory context in whitespace words;
this is a context bound, not a provider token measurement. Use equal output-token
limits, code-context limits, model attempts, and execution timeouts. Record actual
consumption separately. The inherited five-arm historical matrix is not this
preregistered four-arm study; specify arms explicitly. The added counter's default
threshold is a convenience, not a tuned experimental value.

The existing harness needs a frozen manifest naming three repository sequences,
calibration results, reviewed prices, and an authorized execution budget before
it is ready for this study. Its historical manifests do not satisfy those gates.
Do not use historical task outcomes to choose the new held-out set or parameters.

## Records and analysis

`ChatEndpoint` records provider-reported usage and latency for every attempted
call, including retries; missing usage is unknown. Each task carries the call
records and the context size. Lesson generation in this harness uses the same
response's reflection plus local extraction, so its cost is already in that
call. If a future runner adds separate generation, account for those calls too.
A sidecar call log preserves completed attempts when later evaluation fails.
Execution invoices and price schedules must accompany the result artifact.

Report issue-resolution rate, pass-to-pass regressions, total cost per task,
total cost per resolved task, provider token usage, latency, and memory context
size. Cost per resolved task is undefined when no task resolves. Count failed
requests and unresolved tasks in total cost. Keep infrastructure failures explicit.

Pair the same task sequence and repeated-run identity across all arms. Compute
uncertainty at the sequence/run level, with repository clustering; do not treat
dependent tasks as independent samples. Freeze the interval method and analysis
seed before held-out evaluation. Report the paired success difference relative
to no memory and the other controls.

Preregister a five-percentage-point noninferiority margin. Say **preserved
success** only if the lower confidence bound for the paired success difference
exceeds `-0.05`. A nonsignificant superiority comparison is insufficient. Report
an underpowered or incomplete-cost result as inconclusive. If no memory offers
the best cost/success tradeoff, say so.

## Offline comparative analysis

Reconstruct the historical long coding-agent matrix without a provider call:

```bash
python -m bench.swebench_cl.compare bench/results/swebench_cl_long
```

The command requires identical task order and sequence/run identities across
arms. It reports an exploratory hierarchical bootstrap over repositories and
repeated runs, never over dependent task rows. Missing cost and provider usage
remain `null`. Use `--costs COST_LEDGER_JSON` to supply a reviewed billing ledger.
`COST_LEDGER_JSON` maps `RESULT_FILENAME::INSTANCE_ID` to `api_usd`,
`execution_usd`, `other_usd`, and a `source` reference. Include all attempts,
lesson generation, and paid infrastructure. The historical one-cell-per-file
layout makes each billing key specific to an arm, sequence, run, and task.

This reconstruction does not freeze or preregister a prospective analysis.
Few repositories produce unstable intervals. A descriptive interval crossing
the five-point margin does not support preserved success.

## Feedback-corruption study

Preserve a separate, checksummed ground-truth record. Corrupt only the delivered
feedback under an explicit per-cycle or per-sequence budget. Log both values,
which report was changed, and the remaining budget. Include attack-free runs,
the tuned counter, useful-memory loss, harmful decisions, and the boundary where
each method fails. Freeze attack choices without access to held-out truth beyond
the stated threat model.

Label offline replays as replays. Report separately runs where the resulting
memory actually changes the next agent prompt and action. The existing attack
harness retains true `metrics.delta` and corrupted `adversary.reported_delta`;
its historical results do not establish the prospective product claim.
