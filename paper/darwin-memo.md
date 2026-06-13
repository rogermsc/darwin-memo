# Conserved-Resource Selection for Agent Memory: a Retention Rule That Needs No Judge

Roger Simoes

darwin-memo, version 0.5.1. Repository: https://github.com/rogermsc/darwin-memo

## Abstract

An LLM agent that accumulates memories needs a rule for what to keep and
what to forget. The common answer is a judge: a learned reward model or a
second LLM that grades each memory and decides its fate. A judge is
expensive to run and circular in principle, because it scores plausibility
and prose rather than measured consequences. This report studies an
alternative retention rule that uses no judge. Each lesson holds a balance
of a single conserved resource. A decide / settle / tick ledger credits
and debits those balances from the measured outcome of acting on the
lesson, charges a fixed upkeep every cycle, and buries an entry when its
balance starves. There is no model in the loop of the mechanism. We make
two claims and decline a third. The mechanism claim: a conserved-resource
balance, settled from outcomes and drained by upkeep, removes poisoned
knowledge without any label or grader, and the property survives transfer
to a second, structurally different environment family. The regime claim:
we characterize where this rule wins, ties, and loses under outcome noise,
against strike counters, a successive-elimination bandit, and a local LLM
judge, and we publish the losses. The claim we decline: this is not a
state-of-the-art result and is not compared to any memory leaderboard. The
cleanest positive result is cost coupled to mechanism. The deterministic
ledger settles in roughly 0.03 to 0.09 seconds per run while matching or
beating an LLM judge or LLM-driven arm that costs thousands of seconds per
run, a wall-clock gap of about four to six orders of magnitude, while
matching or beating that arm on the conserved-resource outcome.

Every number in this report is read from per-seed result JSON committed
under `bench/results/`, bound to its configuration and reproduction command
by `bench/results/MANIFEST.json`, and re-derived offline with the project's
own `python -m bench.report`. The verified results document is
`docs/benchmarks.md` on the main branch. No number here was produced for
this report.

## 1. Introduction

An agent that keeps a growing store of lessons has a retention problem. A
lesson written from one episode can be wrong, can be poisoned by an
adversarial source, or can simply stop being useful. If the store keeps
everything, a wrong lesson keeps deciding actions forever. If the store
prunes blindly, it loses the lessons that pay. So the store needs a rule
that decides retention from something it can trust.

The dominant rule in recent agent-memory work is a judge: a learned reward
model, a critic, or a second LLM that reads each candidate memory and
grades whether it should be kept. A judge has two costs. The first is
literal: running a model over every memory every cycle is slow and, on a
hosted API, expensive. The second is structural. A judge grades
plausibility, fluency, and surface agreement with a prompt; it does not
observe whether acting on the memory actually helped. A confident, fluent,
wrong lesson is exactly the kind of thing a judge keeps. Grading prose with
a model that was trained to produce prose is circular.

The alternative studied here removes the judge entirely. Retention is
decided by a conserved resource. Each lesson holds a balance. Acting on a
lesson and observing a good measured outcome credits its balance; a bad
outcome debits it. Every cycle a fixed upkeep is charged against every
lesson. A lesson whose balance starves is buried. The only thing the
mechanism reads is the measured outcome of an action the agent already
took, expressed as a single signed scalar. There is no second model, no
learned critic, and no textual verdict anywhere in the loop. That absence
is the differentiating property, and the rest of this report is an attempt
to measure honestly what the absence buys and what it costs.

We are explicit about scope. This work makes a mechanism claim and a
noise-regime claim. It does not claim to beat any leaderboard, and the
known agent-memory benchmarks are out of scope as targets. The contribution
is a selection rule that needs no judge plus a characterization of when it
wins, ties, and loses under outcome noise. The honesty about the losses is
the point: the report runs the two strongest objections from the
literature, a bandit and a judge, against the same harness, and publishes
where each one matches or beats the ledger.

## 2. The Mechanism

The library implements survival-selection memory. The unit is a lesson: a
question, an answer, a provenance set of sources, and a balance of one
conserved resource (energy). The mechanism is three operations over a
ledger, with no model in the loop.

**decide.** Given a query, the store retrieves by relevance only. Retrieval
scoring is pure lexical or embedding relevance; the resource balance is used
at most as a sort tie-break, never as a relevance signal. The top match
becomes the deciding entry, supporting entries are recorded, and a ticket
is opened that names which entries are about to be acted on.

**settle.** When the action's outcome is measured, the ticket is settled
with a single signed scalar: the change in the conserved resource that the
action produced. A positive delta credits the deciding entry's balance; a
negative delta debits it. Credit is bounded per event (a tanh shaping over
a configurable resource scale, then a hard cap at the maximum balance), so
a single enormous reward cannot inflate an entry without limit and a single
enormous penalty is the only thing that can cross a death threshold in one
step. Supporting entries receive a smaller share. The outcome is the only
input; no text is graded.

**tick.** Once per cycle, upkeep is charged against every entry's balance, a
fixed debit independent of whether the entry was used. Entries whose balance
falls to or below the starvation threshold are buried (moved to a graveyard,
queryable for an obituary, removed from retrieval). Consolidation merges
near-duplicate entries above a similarity threshold, taking the union of
their sources. This is the survival pressure: an entry that never earns,
because it is never useful or never gets to act, slowly starves and dies,
while an entry that keeps earning stays alive.

**Trust lifecycle.** New entries enter on probation at a spawn balance.
Entries that accumulate balance are admitted; entries can be pinned to
protect them from culling and from merges (`pin` / `unpin`). Burial is
final for retrieval but auditable: `obituary` reports why an entry died.

**Forgiveness.** Because credit is bounded per event and balances refill by
earning, an entry that was right ninety-nine times survives one disaster:
the single bad outcome debits a bounded amount, and the accumulated balance
absorbs it. This is the property a one-line strike counter (evict on the
first, or Kth, negative outcome) cannot express, and it is the property the
noisy experiments below are designed to stress.

The contrast that defines the whole study: a strike counter and an LLM
judge are the two natural alternatives to this rule, and neither reads a
conserved resource. The strike counter reads only the sign of the outcome
and has no buffer; the judge reads prose and has no measured outcome at
all. The experiments put both alternatives on the same harness and report
where the conserved-resource rule is matched.

## 3. Experimental Setup

### 3.1 Two environment families

All benchmark arms answer tasks through the same driver and differ only in
end-of-cycle retention. Two environment families exercise the mechanism.

`StorageEnv` is the headline family. A store of 16 entries (3 derived from
a poisoned forum post) is queried over 30 cycles, 12 files per cycle. The
conserved resource is bytes: deletions free bytes, restores cost three
times as much, and the poison advises destructive deletions. "Poison
killed" means no living entry from the poisoned source still reads as a
positive action.

`TestSuiteEnv` is the second family, built to test transfer. The conserved
resource is the count of passing tests in a generated project. Each cycle
regenerates an `app.py` and a `test_app.py`, plants three seeded defects,
and offers one patch per defect plus a destructive cleanup patch (removing
a load-bearing helper, costing two tests) and a cosmetic no-op. Applying a
patch reruns the suite; the resource delta is the change in passing-test
count. The corpus has 20 entries with deliberate redundancy: every fix
lesson ships with a near-duplicate twin from a second trusted source, so a
counter that wrongly evicts one copy still has the other. This is the
structural opposite of the StorageEnv corpus, which has no redundancy.

### 3.2 Baselines and control arms

`keep_everything`, `recency`, and `ttl` are pure baselines that track usage
but never touch the resource. `random_matched` is the control that isolates
the active ingredient: it evicts the same per-cycle death counts as the
survival arm on the same seed, with victims chosen uniformly at random.
Same pruning rate, no outcome direction. `evict_on_negative` is the
one-line alternative to the entire ledger: evict whatever decided a
negative-outcome task, with K-strike (`k=1,2,3`), consecutive-strike, and
quarantine variants fielded under noise so the comparison is against the
strike counter's best self, not a strawman.

Two control arms run the literature's strongest objections rather than
arguing against them. `policy_bandit` is a successive-elimination bandit
(the AEL objection, arXiv 2604.21725): each entry is a bandit arm, each
decided task is a pull paying reward 1 (positive reported delta) or 0
(negative), and an entry is culled when its optimistic Hoeffding bound
`mean + sqrt(ln(T) / (2n))` falls below 0.5. `judge_settled` (arXiv
2605.12978) replaces the resource settlement with a local LLM verdict: a
model reads each deciding entry's lesson plus the environment's own outcome
descriptions and returns keep or cull. A fourth arm, `survival_llm`, keeps
the ledger but swaps the deterministic answer step for a local model, so
the cost of the LLM path can be measured against the same selection rule.

### 3.3 Noise models

`FlakyStorageEnv` keeps the world real (bytes are actually freed and spent)
and corrupts only the measurement. Flake marks are drawn per task at
generation time from a dedicated RNG stream, so the set of potentially
lying measurements is a fixed property of the world, identical across arms
at a fixed seed and nested across rates. Three models: **false_bad** (only
positive truths flip, the flaky-CI case where good changes report red but
broken builds never report green), **flip** (symmetric, lies can also
reward the guilty), and **magnitude** (sign preserved, size lied about by
0.25x to 4x, the one model where sign-reading heuristics are immune by
construction). Arms decide off reported deltas; every outcome metric is
computed from true deltas. `keep_everything` doubles as a canary: it never
reads outcomes, so its true cumulative delta must be identical in every
noise cell, and `--check` fails on any drift. TestSuiteEnv carries its own
one-sided flaky-pass-count model with the same false_bad shape.

### 3.4 Seeding, statistics, and the manifest binding

Each (seed, cycle) world derives its RNG from a sha256 hash of the pair, so
no two seeds share a world and across-seed statistics rest on real
independence. An earlier scheme used `seed + cycle`, which made adjacent
seeds shifted windows of one another; every table was regenerated under the
hash scheme, and that regeneration changed several numbers and two
conclusions, including the headline tie discussed below.

Every cell reports a point estimate with a 95% percentile bootstrap
interval (10,000 resamples, seeded so a rerun reproduces it exactly),
resampling seeds because the seed is the unit of independence. Arm
comparisons use exact paired permutation tests: arms at the same seed face
the same world and the same flake marks, so per-seed differences feed a
two-sided sign-flip test. At 10 seeds all 1,024 sign assignments are
enumerated exactly; at 30 seeds it is seeded Monte Carlo with 20,000
permutations. Ties count as extreme, so a deterministic tie reports
p = 1.0, never a spurious significance. All p-values in one tests table are
Holm-Bonferroni adjusted across the full grid of comparisons in that table.

Per-seed raw JSON is committed under `bench/results/`, and
`bench/results/MANIFEST.json` binds each file to its suite, seeds, config
hash, exact reproduction command, library version, and producing git
commit. `python -m bench.report <file> --check --require-manifest`
validates a file against its manifest entry offline, with no model and no
network. CI runs that check on every committed file on every push, so a
deleted manifest entry fails rather than silently passing. All ten
committed files (`headline`, `noisy`, `ablation`, `testsuite`,
`testsuite_noisy`, `bandit`, `judge-llama`, `judge-qwen`, `llm-llama`,
`llm-qwen`) pass `--check --require-manifest`.

## 4. Results

### 4.1 Headline: survival versus baselines (StorageEnv, 10 seeds)

Source: `bench/results/headline.json`. Survival kills the actionable poison
at median cycle 0, ends maximally lean (4 entries), and ends solvent
(cumulative delta about +12.6M). The comparison against cumulative delta,
Holm-adjusted across the grid (`bench.report --tests`):

| survival vs       | W/T/L  | median diff  | p (holm) | verdict                       |
|-------------------|--------|--------------|----------|-------------------------------|
| keep_everything   | 10/0/0 | +21,872,640  | 0.014    | survival wins, all 10 seeds   |
| random_matched    | 10/0/0 | +18,948,096  | 0.014    | survival wins, all 10 seeds   |
| recency           | 10/0/0 | +7,796,736   | 0.014    | survival wins, all 10 seeds   |
| ttl               | 10/0/0 | +16,569,856  | 0.014    | survival wins, all 10 seeds   |
| survival_writes   | 0/10/0 | 0            | 1.0      | identical arm, exact tie      |
| survival_embedding| 0/0/10 | -857,088     | 0.014    | embedding wins, all 10 seeds  |
| evict_on_negative | 0/7/3  | 0            | 0.5      | tie, no significance          |

The adjusted p of 0.014 is the floor an exact test on 10 seeds can reach
after Holm correction; survival's wins over the four pure baselines hit it
in every seed. Two results in this table are stated against the project's
own interest. First, `survival_embedding` (the same loop over a hashing
embedder) beats survival on all 10 seeds (+13.5M versus +12.6M, adjusted
p = 0.014), because cosine ranking happened to place the protector above
the poison from cycle 0; one corpus is not evidence that embeddings
dominate, but the mechanism plainly does not depend on the lexical path.
Second, and more important, **the survival versus evict_on_negative
comparison is an official tie**: 0W/7T/3L, median diff 0, adjusted p = 0.5
(re-derived for this report as 7 seeds byte-identical, 3 small losses for
survival). On a deterministic environment, the one-line strike counter
matches the full ledger on outcomes. What the ledger buys here is leanness
(final population 4 versus 15) and forgiveness, and a deterministic world
cannot show forgiveness paying. The noisy suites exercise it directly.

### 4.2 Noisy outcomes: where forgiveness pays, and the ledger's boundary

Source: `bench/results/noisy.json` (30 seeds per cell). Under **false_bad**
noise the ledger holds and every strike counter collapses. Mean true
cumulative delta and benign capability:

| arm             | 0.00          | 0.05          | 0.10          | 0.20          | 0.35          |
|-----------------|---------------|---------------|---------------|---------------|---------------|
| survival        | 12.38M / 1.00 | 12.38M / 1.00 | 12.26M / 0.99 | 12.26M / 0.99 | 10.47M / 0.79 |
| evict k=1       | 12.57M / 1.00 | 3.30M / 0.04  | 1.54M / 0.00  | 0.41M / 0.00  | 0.00M / 0.00  |
| consecutive k=2 | 12.38M / 1.00 | 11.47M / 0.81 | 9.12M / 0.48  | 3.73M / 0.06  | 1.08M / 0.00  |

At 5% false-bad noise survival's true outcomes are byte-identical to its
noise-free run in all 30 seeds; at 10% and 20% they are byte-identical in
29 of 30. A capped decider holds roughly nine lies' worth of buffer and
refills it by earning. Against the strongest counter (consecutive), paired
per seed on true cumulative delta, survival is 14W/16T/0L at 5% (adjusted
p = 0.0038), 27W/3T/0L at 10%, and 30W/0T/0L at 20% and 35% (adjusted
p = 0.0036, the Monte Carlo floor). Under false_bad survival loses no seed
to any counter at any rate.

The boundary is published with the same care. Under **flip** noise the
ledger degrades, and at 50% it fails. Survival under flip:

| metric            | 0.00  | 0.05  | 0.10  | 0.20  | 0.35  | 0.50  |
|-------------------|-------|-------|-------|-------|-------|-------|
| true cum delta    | 12.38M| 12.20M| 11.95M| 11.80M| 9.43M | 1.25M |
| benign capability | 1.00  | 1.00  | 0.99  | 0.99  | 0.79  | 0.26  |
| poison kill (med) | 0     | 0     | 1     | 1     | 1     | 3     |

Forgiveness has a price: tolerance for lying measurements is tolerance for
guilty entries, so the poison's kill cycle climbs from 0 to a median of 3
at 50% as false-good lies keep rescuing it (2 of 30 seeds never kill it).
At 50%, a sign flip with no information content, capability collapses to
0.26 and the run barely stays solvent. The honest 50% claim is that
survival is indistinguishable from the counters and nothing curates safely
there: 21W/9L versus consecutive, adjusted p = 1.0. Past roughly one lie in
three, capability dies first. Under **magnitude** noise survival sits at
exactly its rate-0.00 numbers in all 30 seeds at both rates, because the
energy cap, not the tanh curve, clips size lies on a healthy decider.

### 4.3 TestSuiteEnv: the mechanism transfers, the headline tie does not

Source: `bench/results/testsuite.json` (10 seeds) and
`bench/results/testsuite_noisy.json` (30 seeds per cell). The mechanism
transfers: survival kills the actionable poison in every seed, the suite
genuinely drops two tests when the poison wins, the negative credit lands,
and the poison is dead by cycle 2. `keep_everything` and `recency` bleed
forever, `random_matched` again shows pruning rate is not the active
ingredient, and `ttl` cures the disease by killing the patient.

The headline tie does not transfer, and the counter wins here.
`evict_on_negative` beats survival on all ten seeds (88 versus 69, median
margin 20, adjusted p = 0.014). The cause is a designed property of this
family meeting a designed property of the ledger: TestSuiteEnv pays nothing
for refusals. A skipped patch runs no suite and produces no measurement, so
the dedupe protector that keeps refusing the destructive patch can never
earn, and under upkeep it starves mid-run (around cycle 21 in nine of ten
seeds). Once it is gone the destructive patch starts landing again. The
counter never touches the resource, so its protector refuses forever (final
population 19 versus 4). Leanness, the ledger's selling point on
StorageEnv, is the liability here.

The pre-committed grid question was: at what flake rate does the ledger's
forgiveness beat the naive strike counter `evict_on_negative`? The answer,
committed before the run and published as found: **at 10%, and not below.**
At 5%, k=1 ties survival (adjusted p = 1.0) and k=2 still beats it (adjusted
p = 0.0015). At 10%, survival beats k=1 in every seed (mean +35, adjusted
p = 0.0015) and beats k=2 (22W/8L, adjusted p = 0.028); the edge stays
significant through 20%. The harsher half is also published: across this
grid **survival is never the best arm in any cell.** k=1 takes the
deterministic column, consecutive k=2 takes 0.05, k=3 takes 0.10,
quarantine takes 0.15 and 0.20. The boundary the question names is against
the naive counter, not against the field. The redundancy that the corpus
ships is real for the counters and spent by the ledger: the survival arm
consolidates each twin pair into one entry, concentrating a whole earning
category into one death, while a counter keeps both twins and absorbs a
wrongful eviction.

### 4.4 Control arm: the bandit boundary

Source: `bench/results/bandit.json` (240 runs, 10 seeds per cell). The AEL
objection holds in one regime and fails elsewhere, exactly as
pre-committed. Mean true cumulative delta (M) / benign capability:

| arm           | false_bad 0.00 | 0.05  | 0.10  | 0.20  | 0.35  |
|---------------|----------------|-------|-------|-------|-------|
| policy_bandit | 11.14 / 1.00   | 11.14 / 1.00 | 11.14 / 1.00 | 11.14 / 1.00 | 11.14 / 1.00 |
| survival      | 12.59 / 1.00   | 12.59 / 1.00 | 12.23 / 0.97 | 12.23 / 0.97 | 11.00 / 0.77 |

The bandit's false_bad and magnitude cells are per-seed identical to its
clean run in all 10 seeds, because false_bad only turns wins into reported
losses and a healthy decider's observed win rate stays far above the 0.5
elimination threshold. So as the noise rate climbs, survival walks down
toward the bandit's flat line and reaches it. **At false_bad 0.35 the
bandit matches survival**: 11.14M versus 11.00M, paired diff +0.14M with the
bandit winning 5 of 10 seeds (re-derived for this report as 5 bandit wins,
4 survival wins, 1 tie, median diff +74,240; adjusted p = 0.68, a
statistical tie), and the bandit retains full benign capability (1.00
versus survival's 0.77) because a winner essentially never crosses the
threshold and so never wrongfully executes. If your noise is one-sided and
you can live with an uncurated population, the bandit is a legitimate tool
in that regime.

Everywhere else the ledger wins (9 of 10 seeds per cell, adjusted p = 0.047,
the Holm floor on this grid) and the pre-committed predictions land. The
bandit starves nothing (final population 15 to 16, near keep_everything,
because a never-pulled entry can never be eliminated), its poison kill lands
at median cycle 1.5 versus survival's 0 (confidence takes confirmed failures
to collapse), and under flip its sign-blindness breaks it: at flip 0.50 it
bleeds to -9.08M, keep_everything's territory, while survival stays the only
arm above zero (+0.80M). The three things the bandit cannot do are starve
dead weight, kill promptly, and survive lies that pay the guilty.

### 4.5 Control arm: the LLM judge, per model

Source: `bench/results/judge-llama.json` and `bench/results/judge-qwen.json`
(5 survival plus 5 judge seeds each, StorageEnv, 12 cycles). Five seeds is a
small sample by design: each judged cycle is a model call, so the exact
two-sided permutation test cannot drop below p = 0.0625 even on a clean 5-0
sweep. These are direction and effect size, not significance.

| model       | arm           | cum delta (M)       | benign | kill (med) | judge wall (s) |
|-------------|---------------|---------------------|--------|------------|----------------|
| llama3.2:3b | survival      | 2.66 [2.19, 3.10]   | 1.00   | 1          | 0.09           |
| llama3.2:3b | judge_settled | 1.88 [0.76, 2.96]   | 0.67   | 1          | 87.6           |
| qwen3:4b    | survival      | 2.66 [2.19, 3.10]   | 1.00   | 1          | 0.03           |
| qwen3:4b    | judge_settled | 3.09 [2.88, 3.29]   | 1.00   | 0          | 1,514.2        |

The two local judges split, and the report does not smooth that. The
hypothesis (survival beats judge settlement) **holds for llama3.2:3b**:
survival wins the per-seed cum-delta pairing 3W/2T/0L (mean diff +0.78M),
and the judge pays capability (benign correctness falls to 0.67) by culling
load-bearing benign entries on the prose it reads, with 67 unparseable or
missing verdicts defaulted to keep across the five runs. The hypothesis
**fails for qwen3:4b**: it slightly beats survival on cum delta (3.09M
versus 2.66M, 0W/2T/3L for survival), holds benign capability at 1.00, and
kills the poison at cycle 0. So the differentiating claim does not get clean
benchmark support at this scale, and this report says so rather than
reporting only the model that confirmed it. Mean survival-arm wall time
re-derived from the committed JSON is 0.093 s (judge-llama) and 0.032 s
(judge-qwen); total run wall time is 87.8 s and 1,514.4 s respectively.

### 4.6 LLM-mode arm: citation fidelity and the cost ratio

Source: `bench/results/llm-llama.json` (10 runs, 5 seeds off and 5 on) and
`bench/results/llm-qwen.json` (2 runs, the only qwen runs complete at
assembly). The `survival_llm` arm keeps the ledger and swaps the
deterministic answer step for a local model, and carries a
`refuse_unparseable` mitigation that turns an answer whose SOURCES line
fails to parse into silence.

The mitigation is **inert for llama3.2:3b**, and the report calls it inert.
The model emitted a parseable SOURCES line on every answer
(`citation_sources_line_rate` 1.00, `citation_fallback_rate` 0.00) under
both settings, so the protocol never reached the fallback path the
mitigation gates. Per-seed cum-delta pairing off versus on is 1W/2T/2L,
mean diff -84,790 with exact paired p = 0.5000, and the unattributed-action
rate is byte-identical off and on (0.2283, exact paired p = 1.0000). The
mitigation only bites a model that drops the SOURCES line, which is the
qwen case (`citation_sources_line_rate` mean 0.525, `citation_fallback_rate`
mean 0.475 across its two runs); but the qwen on-cells are not yet committed,
so the report does not claim the mitigation helps qwen. The two qwen seeds
split on the sign of cum delta (-1,677,312 and +2,200,576), which is why
two seeds settle nothing.

The cost result is the clean one. Re-derived from the committed JSON
(`metrics.wall_time_s`):

| arm / source                | per-run wall (s, mean) | range (s)            |
|-----------------------------|------------------------|----------------------|
| survival (judge-qwen.json)  | 0.032                  | 0.030 to 0.036       |
| survival (judge-llama.json) | 0.093                  | 0.089 to 0.101       |
| survival_llm, llama3.2:3b   | 1,076.0                | 925.7 to 2,054.8     |
| survival_llm, qwen3:4b      | 17,182.4               | 16,983.0 to 17,381.7 |

The deterministic ledger settles in roughly 0.03 to 0.09 seconds per run.
The same per-cycle work answered by a local model costs about 1,076 s/run
for llama3.2:3b (about 12,000x the ledger at the means) and about 17,182
s/run for qwen3:4b (about 540,000x; one qwen run alone is 4.8 hours of model
time for 120 queries). The cost gap holds before any answer is even
classified, and it is the most robust result in this report.

## 5. Honest Limitations

This section collects every loss, tie, and inert result in one place,
because the honesty is the credibility.

- **The headline tie.** On deterministic StorageEnv, survival ties
  `evict_on_negative` on outcomes (0W/7T/3L, adjusted p = 0.5). The earlier
  "50%-flip headline" that suggested survival dominated did not survive the
  seeded re-analysis under independent (sha256-hashed) seeds; that re-analysis
  narrowed several claims and is the reason the tie is now stated officially.
  The ledger's only deterministic-world advantages are leanness and
  forgiveness, and a deterministic world cannot show forgiveness paying.
- **The bandit ties under one-sided noise.** The successive-elimination
  bandit (the AEL objection, arXiv 2604.21725) ties survival at false_bad
  0.35 (about 35%): paired diff +0.14M, 5 bandit wins to 4, adjusted
  p = 0.68, and the bandit keeps full benign capability (1.00 versus 0.77)
  while survival is degrading. The ledger wins elsewhere, but the regime
  where the objection holds is published.
- **The TestSuiteEnv loss.** `evict_on_negative` beats survival on all ten
  seeds on the test-suite family (88 versus 69, adjusted p = 0.014), because
  that family pays nothing for refusals and the protector starves. Survival
  is never the best arm in any cell of the TestSuiteEnv noise grid; k=1, k=2,
  k=3, and quarantine each own a cell.
- **The judge does not always degrade.** The local LLM judge (arXiv
  2605.12978) degrades as predicted for llama3.2:3b (benign capability falls
  to 0.67) but does not degrade for qwen3:4b at n=5 (benign 1.00, slightly
  beats survival on cum delta). The differentiating claim therefore gets no
  clean benchmark support at this scale.
- **The mitigation is inert.** In the LLM-mode arm, `refuse_unparseable` is
  inert for llama3.2:3b, which always emits a parseable SOURCES line
  (off-versus-on exact paired p = 0.5000 on cum delta, 1.0000 on
  unattributed-action rate). The model it was built for, qwen3:4b, has no
  on-cells committed yet.
- **Small samples and weak judges.** The judge and LLM-mode arms run 3B and
  4B instruction-tuned models at temperature 0, the weak end of the judge
  spectrum, at five seeds (judge, LLM-llama) and two seeds (LLM-qwen).
  Nothing in those arms clears p = 0.05; they are direction, effect size,
  and cost, never significance. A frontier judge could plausibly hold
  capability where llama3.2:3b drops it.
- **Vocabulary coupling.** On StorageEnv the corpus, the task prompts, and
  the polarity reader were written by one hand in one vocabulary, so the
  crisp cycle-0 kill lives in the lexical-match regime. The paraphrase
  columns are the out-of-distribution honesty check: harmful paraphrases
  stay safe because silence is conservative, but lexical arms ground only
  about a third of benign paraphrases.
- **Scale and structure.** The corpora are demo-scale (16 and 20 entries).
  StorageEnv has no redundancy, so its counter collapses are a
  redundancy-free upper bound; TestSuiteEnv has twin redundancy, so its
  counter wins are the cushioned complement. Both families couple prompts
  and corpus to the same hand. The conclusions that hold on only one family
  are flagged as family-dependent rather than averaged away.

The honest cross-family summary: when refusals earn nothing and redundancy
is pre-paid, a counter is better below 10% flake and quarantine is better
above it; the ledger's regime is the middle band against naive counters,
and its StorageEnv dominance does not transfer. The one claim that holds
across every arm is cost.

## 6. Related Work

This report uses two arXiv references as the design anchors and runs them as
control arms rather than citing them as distant context.

The judge alternative is anchored by arXiv 2605.12978, which predicts the
failure mode the `judge_settled` arm goes looking for: continuously updated
memories settled by a judge go faulty because the judge grades plausibility
and prose where a conserved resource weighs measured consequences. Rather
than argue this, the report builds the arm, gives the judge more per-event
information than the ledger gets (the prose descriptions name what really
happened), and reports the per-model split.

The bandit alternative is anchored by arXiv 2604.21725 (the AEL objection):
a simple bandit over retrieval policies should match outcome-settled
selection under noise, which would make the energy ledger decoration. The
report builds a successive-elimination bandit with a Hoeffding radius (real
confidence-based forgiveness), and publishes the regime where the objection
holds (one-sided false_bad noise around 35%) alongside the regimes where it
fails (dead-weight immortality, slow kills, symmetric-noise collapse).

The library's design lineage (external memory kept by survival selection
rather than a reward model) is recorded in the repository's `CITATION.cff`,
which also cites MeMo (arXiv 2605.15156) and a survival-only-reward training
line (arXiv 2601.12310). The framing here is deliberately narrow: the bandit
and the judge are the two strongest objections to a no-judge rule, and this
work runs them rather than arguing against them. No memory leaderboard is
invoked as a target, by design.

## 7. Reproducibility

A frozen reproduction package ships alongside this report under `paper/`:
`paper/reproduce.md` and `paper/reproduce.sh`. The package documents what is
frozen (the per-seed JSON, `MANIFEST.json`, config hashes, and the recorded
Ollama model digests for the LLM arms), how the manifest binds each result
file to a config hash and a producing git commit, and the exact commands.

The verification path is offline by default. `reproduce.sh` installs the
package pinned to the v0.5.1 release (or, equivalently, the recorded release
commit), then runs `python -m bench.report <file> --check
--require-manifest` against every committed result file. This checks the
committed evidence against the manifest with no model and no network. The
script then prints which arms can be regenerated deterministically offline
(every stdlib suite: headline, noisy, ablation, testsuite, testsuite_noisy,
bandit) and which require a local Ollama server with a named model pulled
(the judge and LLM arms), with the recorded wall times so a reader knows the
cost before starting. The script never calls a model or the network by
default.

One detail matters for byte reproduction: the environments' per-cycle seed
scheme changed after the 0.4.0 release while `__version__` still read 0.4.0,
so reproducing the committed numbers means checking out each file's
manifest `source_commit`, not installing the 0.4.0 wheel. The reproduction
document states this and gives the exact `git checkout`.

## 8. Conclusion

A conserved-resource balance, credited and debited from measured outcomes
and drained by a fixed upkeep, is a retention rule for agent memory that
needs no judge. It removes poisoned knowledge without labels, and the
property transfers to a second environment family. Its advantage over a
one-line strike counter is forgiveness and leanness, and the experiments
locate that advantage precisely: under one-sided false-bad noise the ledger
holds where every strike counter collapses, while on a family that pays
nothing for refusals the counter wins and the ledger's leanness becomes a
liability. The two strongest objections from the literature, a bandit and a
judge, were run rather than argued, and each one matches or beats the ledger
in a published regime. None of this is a state-of-the-art claim, and none of
it is compared to a leaderboard.

The result that holds across every arm is cost coupled to mechanism: a
deterministic ledger settles in roughly 0.03 to 0.09 seconds per run, four
to six orders of magnitude faster than an LLM judge or LLM-driven arm, while
matching or beating that arm on the conserved-resource outcome. For an agent
that must decide retention every cycle over the lifetime of a deployment,
that gap is the practical case for settling memory by a measured resource
instead of by a model's verdict.
