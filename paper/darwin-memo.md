# Conserved-Resource Selection for Agent Memory: Cost, Leanness, and the Noise Regimes Where a Judge-Free Buffer Helps

Roger Simoes

darwin-memo, version 0.5.1. Repository: https://github.com/rogermsc/darwin-memo

## Abstract

An LLM agent that accumulates memories needs a rule for what to keep and
what to forget. A common answer is a judge: a learned reward model or a
second LLM that grades each memory and decides its fate. This report
studies a deterministic, judge-free alternative and measures what it buys.
Each lesson holds a balance of a single conserved resource. A decide /
settle / tick ledger credits and debits those balances from the measured
outcome of acting on the lesson, charges a fixed upkeep every cycle, and
buries an entry when its balance starves. There is no model in the loop of
the mechanism. We do not claim that a judge-free buffer is superior in
general; the data here cannot establish that, and our own controls undercut
it. We treat "no judge" as a design stance, justified by two arguments, and
then characterize where the resulting rule actually helps.

The first argument is cost. A deterministic arithmetic update settles in
roughly 0.03 to 0.09 seconds per run, while a local LLM judge or LLM-driven
arm doing the same per-cycle work costs roughly 88 to 17,000 seconds per
run, three to six orders of magnitude more, and that gap holds before any
answer is even classified. The second argument is circularity: a judge
grades plausibility and prose, the very thing the underlying model was
trained to produce, whereas the ledger weighs a measured consequence. The
third contribution, and the most defensible, is an empirical regime map.
Against discrete strike counters, a continuous outcome-settled buffer
dominates inside a band of one-sided false-bad noise (roughly 10 to 35
percent on StorageEnv), where its forgiveness pays. Outside that band it
ties or loses, and we report this plainly: it ties a one-line
evict-on-negative counter on the deterministic StorageEnv headline (0W/7T/3L,
adjusted p = 0.5); it loses the TestSuiteEnv headline to the same counter on
all ten seeds because that family pays nothing for refusals; it ties a
successive-elimination bandit at false_bad 0.35; and at symmetric flip noise
of 50 percent no arm curates safely. A separate strength is leanness:
upkeep starves dead weight, so the population stays small where a counter
hoards everything that never erred. Leanness is an asset on StorageEnv and a
liability on TestSuiteEnv, and we show both.

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

One rule in recent agent-memory work is a judge: a learned reward model, a
critic, or a second LLM that reads each candidate memory and grades whether
it should be kept (Section 6 places this line of work). A judge has two
costs. The first is literal: running a model over every memory every cycle
is slow and, on a hosted API, expensive. The second is structural. A judge
grades plausibility, fluency, and surface agreement with a prompt; it does
not observe whether acting on the memory actually helped. A confident,
fluent, wrong lesson is exactly the kind of thing a judge keeps. Grading
prose with a model that was trained to produce prose is circular.

We take "no judge" as a design stance, not as a demonstrated superiority.
The retention rule studied here uses no judge: retention is decided by a
conserved resource. Each lesson holds a balance. Acting on a lesson and
observing a good measured outcome credits its balance; a bad outcome debits
it. Every cycle a fixed upkeep is charged against every lesson. A lesson
whose balance starves is buried. The only thing the mechanism reads is the
measured outcome of an action the agent already took, expressed as a single
signed scalar. There is no second model, no learned critic, and no textual
verdict anywhere in the loop. Two arguments justify the stance, both
quantified below: the cost gap of three to six orders of magnitude against an
LLM judge or LLM-driven arm (Sections 4.5 and 4.6), and the circularity of
grading prose with prose. Whether the absence of a judge also improves
outcomes is an empirical question this report answers regime by regime, and
the answer is "sometimes."

We are explicit about scope. This work is a recombination of two
well-studied ideas, aged and cost-weighted eviction and bounded-reward
credit assignment, applied to agent memory (Section 6). It does not claim a
new primitive and does not claim to beat any leaderboard; the known
agent-memory benchmarks are out of scope as targets. The contributions are
three. (1) A cost and circularity argument for avoiding an LLM judge in the
retention loop. (2) Leanness: upkeep starves dead weight that a strike
counter would hoard. (3) The empirical regime map, the most defensible
contribution, of where a continuous outcome-settled buffer dominates
discrete strike, consecutive, and quarantine counters and where it does not.
The honesty about the losses is the point: the report runs the two strongest
objections from the literature, a successive-elimination bandit and an LLM
judge, against the same harness, and publishes every regime where each one
matches or beats the ledger.

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
absorbs it. Section 2.1 gives the arithmetic so this property can be checked
on the page. This is the property a one-line strike counter (evict on the
first, or Kth, negative outcome) cannot express, and it is the property the
noisy experiments below are designed to stress.

The contrast that defines the whole study: a strike counter and an LLM
judge are the two natural alternatives to this rule, and neither reads a
conserved resource. The strike counter reads only the sign of the outcome
and has no buffer; the judge reads prose and has no measured outcome at
all. The experiments put both alternatives on the same harness and report
where the conserved-resource rule is matched.

### 2.1 The balance update, formally

The arithmetic below is read directly from the source so it can be checked
against the code. Constants are quoted with the DEFAULT values found in
`darwin_memo/`. Let entry `e` hold balance `b_e in [0, cap]`. The shared
credit rule (`darwin_memo/survival.py`, `assign_credit`, lines 89 to 116)
maps one measured resource delta to a bounded credit:

    credit(delta) = g * tanh(delta / scale)

where `g` is `credit_gain` (default 0.6, `SurvivalConfig.credit_gain`) and
`scale` is `resource_scale` (the environment's normalization hint; 100,000
bytes for `StorageEnv`, 2.0 for `TestSuiteEnv`, and 1.0 when a bare `Ledger`
is constructed with no scale). For the deciding entry, the balance update on
settlement, composing `MemoryStore.credit` (clips at the cap, `store.py`
line 199) with the same-tick upkeep debit from `tick` (`charge_upkeep`,
`store.py` lines 222 to 230), is

    b_e <- clip( b_e + g * tanh(delta / scale) - upkeep , 0 , cap )

with `upkeep` 0.05 (`MemoryStore.upkeep`) and `cap` 5.0 (`max_energy`). The
clip at 0 is the burial floor: `MemoryEntry.alive` is `energy > 1e-9`
(`types.py` line 90), so an entry is buried on the tick its balance reaches
zero, unless it is pinned (then the balance floors at 0 and the entry
survives) or escrowed by a pending ticket (`ledger.py` `charge_upkeep`
`protect` set). A supporting (provenance-neighbor) entry `s` takes a smaller
share, `supporting_share` (default 0.25, `SurvivalConfig.supporting_share`):

    b_s <- clip( b_s + supporting_share * g * tanh(delta / scale) - upkeep , 0 , cap )

When no single entry decided (the even-spread path, `survival.py` lines 106
to 113), the credit `g * tanh(delta / scale)` is divided evenly across the
supporting entries, and a probationary import among them is further scaled by
`supporting_share`. New locally minted entries spawn at balance 1.0
(`MemoryEntry.energy`, `types.py` line 75) and imported entries spawn on
probation (`DEFAULT_PROBATION` 3, `ledger.py` line 58), during which they
ride along as support but may not decide. Admission gating
(`admission_window`, default 0, off) is the one optional knob that changes
this arithmetic: while a locally minted entry is juvenile its deciding credit
is capped at the supporting share, and one negative deciding delta zeroes its
balance outright (`advance_lifecycle`, `survival.py` lines 154 to 162).

The forgiveness bound follows from the equation. Because `tanh` is bounded by
1, the most a single adverse settlement can debit a deciding entry is
`g + upkeep = 0.6 + 0.05 = 0.65`. A healthy decider sits at the cap, 5.0, so
in the worst case it absorbs `floor(cap / (g + upkeep)) = floor(5.0 / 0.65) =
7` maximally adverse settlements before burial, and absorbs more when the
debits are smaller. On `StorageEnv` the largest disposable-file deltas land
near `tanh(delta / 100,000) approximately 0.83`, a per-event debit of
`0.6 * 0.83 + 0.05 approximately 0.55`, so `5.0 / 0.55 approximately 9`: the
"buffer absorbs about nine lies" claim in Section 4.2 is this number, and a
skeptic can recompute it from `g`, `scale`, `upkeep`, and `cap` above. Two
details are genuinely ambiguous in the source and we flag them rather than
overstate. First, the exact count of absorbable adverse settlements depends
on the per-event delta magnitudes a given world produces, so "about nine" is
a representative worst case for `StorageEnv`'s disposable deltas, not a fixed
constant. Second, the death threshold is the floating-point predicate
`energy > 1e-9`, not an exact equality to zero, so an entry that lands at a
tiny positive residual survives one extra tick; the `1e-9` epsilon is the
operative threshold, not 0.

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
(the Agent Evolving Learning, or AEL, objection [Xu et al. 2026a], that a
bandit over policies should match outcome-settled selection): each entry is a
bandit arm, each decided task is a pull paying reward 1 (positive reported
delta) or 0 (negative), and an entry is culled when its optimistic Hoeffding
bound `mean + sqrt(ln(T) / (2n))` falls below 0.5. `judge_settled` [Zhang et
al. 2026] replaces the resource settlement with a local LLM verdict: a
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

The raw deltas above are in bytes, which makes their practical magnitude
hard to read, so we normalize. Taking survival's clean cumulative delta
(+12.59M) as the scale of one full curated run, the wins over the pure
baselines are large in fraction-of-scale terms (`keep_everything` and
`random_matched` finish underwater, a swing of roughly 1.7 of one curated
run; `recency` trails by about 0.62; `ttl` by about 1.3), while the
`survival_embedding` loss is small (about 0.07 of scale, +13.5M versus
+12.6M) and the `evict_on_negative` difference is zero at the median. Read
as a rank-based effect size, the four pure-baseline comparisons are 10/10
one-directional (the maximum separation 10 seeds allow), the embedding
comparison is 10/10 the other way, and the counter comparison is 7 exact
ties with 3 small losses, which is the rank signature of a tie rather than
an edge. The leanness difference normalizes cleanly too: final population 4
versus the counter's 15 is a 73 percent smaller resident set for the same
outcome.

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
refills it by earning; that "nine" is the
`cap / (g * tanh(delta / scale) + upkeep) approximately 5.0 / 0.55`
arithmetic from Section 2.1 for `StorageEnv`'s disposable deltas, with
`floor(cap / (g + upkeep)) = 7` the saturated worst-case floor.
Against the strongest counter (consecutive), paired per seed on true
cumulative delta, survival is 14W/16T/0L at 5% (adjusted p = 0.0038),
27W/3T/0L at 10%, and 30W/0T/0L at 20% and 35% (adjusted p = 0.0036, the
Monte Carlo floor). Under false_bad survival loses no seed to any counter at
any rate. The practical magnitude is large in this band: normalizing by the
clean run (12.38M), the gap to consecutive widens from about 0.07 of one
curated run at 5% to about 0.76 at 35% (10.47M versus 1.08M), and the gap to
k=1 reaches roughly 0.85 of scale. The benign-capability column is already a
fraction in [0, 1] and is the more legible effect: survival holds 0.79 to
1.00 across the band while consecutive falls from 0.81 to 0.00.

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

### 4.7 Parametric memory: distillation as a data filter

Every result above scores the retrieval store. This arm asks MeMo's own
question: distilled into model weights, does selection still help? We
LoRA-fine-tune `Qwen/Qwen2.5-0.5B-Instruct` on three curated sets of a
purpose-built QA corpus (30 distinctive good facts, 6 distinctive poison
entries whose harmful tokens are out-of-vocabulary for the good facts, so a
model cannot hallucinate them; selection over `VerifiableQAEnv`,
consolidation disabled). Each model is scored by containment — `good_recall`
and `poison_reproduction` — over 5 seeds (opt-in arm; sampled; never CI).

| arm | source set | good_recall | poison_reproduction |
|-----|-----------|-------------|---------------------|
| base_model | none | 0.00 | 0.00 |
| retrieval | survivor store (ref) | 1.00 | 0.00 |
| distill_survivor | energy-ledger survivors | **1.00** | **0.00** |
| distill_raw | unfiltered | 0.96 | **1.00** |
| distill_judge | LLM-judge-kept (no floor) | 0.05 | 0.00 |
| distill_judge_floor | LLM-judge-kept, ledger-settled | 0.93 | 0.00 |

Distilling the raw store teaches the facts but bakes in every poison
statement; distilling the energy-ledger survivors teaches the same facts and
reproduces none of the poison, because survival removed it before training.
The floor-free judge, run for the identical 40 cycles, has no energy floor:
its culls accumulate with no earn-back toward extinction (1–4 survivors),
leaving almost nothing to distill — though at a short horizon (≈10 cycles) it
tracks correctly, so the failure is the missing floor, not the verdict
quality. The `distill_judge_floor` arm confirms this directly: it settles the
*identical* judge verdicts through the energy ledger (keep +0.6, cull −0.6,
upkeep 0.05, die at the floor) and the collapse vanishes — 29–30 survivors,
recall 0.93, poison 0.00, nearly matching the measured ledger. So the active
ingredient is the conserved-resource floor, not the choice of signal:
measurement and judgment both work once buffered, with measurement holding a
small, tighter edge (1.00 ± 0.00 vs 0.93 ± 0.10). This is a 0.5B existence
proof, not a scaling law, and the separation depends on poison being distinct
from the benign distribution (see Limitations).

**Selection quality, not set membership.** Two follow-up arms, added to answer
an adversarial review, separate what is tautological here from what is not.
First, a **counter baseline**: the poison=0 result is *not* ledger-specific —
a one-line `evict_on_negative` filter also yields poison 0, because the poison
is always wrong and gets buried by any blame rule. The ledger's distinctive
contribution is **capability retention under noisy measurement**. Distilling the
filtered sets under `flip@0.2` report-noise, the survivor-distilled model keeps
good_recall 0.91 ± 0.04 while the naive and hardened counters collapse to
0.00 / 0.03 — the noise-free toy hides the difference; realistic lying
measurement reveals it. Second, a **benign-distribution poison** arm removes the
out-of-vocabulary crutch: poison is a corrupted rule in the good facts'
vocabulary, scored on held-out services. The unfiltered model **generalizes the
harmful rule to 0.60 ± 0.18 of held-out services it never trained on**
(generalization, not memorization); survival buries the poison and reproduces it
on none (0.00), generalizing the safe rule instead (1.00) — and under noise the
counter collapses to nothing while survival still blocks the harm and keeps the
safe rule. So selection quality is load-bearing: the ledger uniquely retains
capability and blocks harmful generalization under noise, where set-membership
filters and counters do not.

### 4.8 Continual learning via task-vector merging

The same machinery composes across corpora. We distill one survivor-filtered
LoRA adapter per disjoint corpus (two corpora of 15 facts + 3 poison each over
non-overlapping services) and combine the adapters with `peft`'s
`add_weighted_adapter`, scoring recall on both parts and poison reproduction
over both (5 seeds).

| condition | recall_part0 | recall_part1 | recall_all | poison |
|-----------|-------------|-------------|------------|--------|
| solo_part0 | 0.97 | 0.32 | 0.65 | 0.00 |
| solo_part1 | 0.27 | 1.00 | 0.63 | 0.00 |
| merged_cat | 0.68 | 0.75 | 0.71 | 0.00 |
| merged_ties | 0.73 | 0.65 | 0.69 | 0.00 |
| merged_linear | 0.23 | 0.20 | 0.21 | 0.00 |
| joint | 1.00 | 1.00 | 1.00 | 0.00 |

A solo adapter recalls only its own corpus; merging with `cat` or `ties`
recovers most of *both* without retraining on their union (recall_all ≈ 0.70 vs
the solo half-knowledge ≈ 0.64), while naive `linear` summing interferes (0.21).
The joint adapter trained on the union is the ceiling (1.00); the merged↔joint
gap is the interference cost of composition over retraining. Poison reproduction
stays 0.00 for every distilled and merged condition: survival filtered each
corpus and merging introduces no new data, so the poison is absent from the
merged weights as well. This realizes the task-vector-merging continual-learning
story (Section 6) on survival-selected memory, again as a 0.5B existence proof.

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
  bandit (the AEL objection [Xu et al. 2026a]) ties survival at false_bad
  0.35 (about 35%): paired diff +0.14M, 5 bandit wins to 4, adjusted
  p = 0.68, and the bandit keeps full benign capability (1.00 versus 0.77)
  while survival is degrading. The ledger wins elsewhere, but the regime
  where the objection holds is published.
- **The TestSuiteEnv loss.** `evict_on_negative` beats survival on all ten
  seeds on the test-suite family (88 versus 69, adjusted p = 0.014), because
  that family pays nothing for refusals and the protector starves. Survival
  is never the best arm in any cell of the TestSuiteEnv noise grid; k=1, k=2,
  k=3, and quarantine each own a cell.
- **The judge does not always degrade.** The local LLM judge [Zhang et al.
  2026] degrades as predicted for llama3.2:3b (benign capability falls
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
- **The distillation arm is an existence proof.** The parametric result
  (§4.7) is a 0.5B model on a 30/6 corpus at five seeds; it shows the
  data-filter effect cleanly but is not a scaling law. Its separation also
  depends on the poison being distinct from the benign distribution: the
  harmful tokens are deliberately out-of-vocabulary, so reproduction is
  unambiguous. An earlier file-deletion corpus, where survival's safety was
  *absence* (silence) rather than positive knowledge, did not separate under
  parametric distillation at all — a generative model cannot reproduce
  silence — which is why the arm measures `good_recall`/`poison_reproduction`
  on a distinctive corpus rather than reusing the retrieval suite's
  `harmful_safe_rate`. The judge's collapse is a property of the floor-free
  baseline, not of judges in general — the `distill_judge_floor` arm settles
  the same verdicts through the ledger and recovers to recall 0.93 / poison
  0.00, so the floor, not the signal, is the active ingredient.

The honest cross-family summary: when refusals earn nothing and redundancy
is pre-paid, a counter is better below 10% flake and quarantine is better
above it; the ledger's regime is the middle band against naive counters,
and its StorageEnv dominance does not transfer. The one claim that holds
across every arm is cost.

## 6. Related Work

darwin-memo recombines two well-studied lines, aged and cost-weighted cache
eviction and bounded-reward credit assignment, and applies the combination to
agent memory. Its specific contribution is the empirical regime
characterization of Section 4 and the judge-free cost argument, not a new
primitive. This section places the neighbors and is honest about what is
borrowed.

**Cache eviction and admission.** The retention question, what to keep in a
bounded store, is the cache-replacement question. Recency (LRU) and frequency
(LFU) are the textbook baselines, and `recency` and `ttl` arms here are their
direct analogs. The closer neighbor is cost-aware and learned eviction.
GreedyDual-Size weights eviction by a per-item cost rather than access alone
[Cao and Irani 1997], which is exactly what a conserved-resource balance does
when the resource is bytes or passing tests. ARC self-tunes between recency
and frequency using ghost history [Megiddo and Modha 2003], and LeCaR casts
eviction as online regret minimization over LRU and LFU experts [Vietri et
al. 2018], framing cache replacement as a learning problem. The upkeep-driven
starvation in darwin-memo is an aging policy in this lineage: an entry that
stops earning decays out, as in cost-aware eviction, with the cost read from
measured outcomes rather than item size.

**Credit assignment and bandits.** The settlement rule, distributing a
bounded scalar reward back along the provenance that produced an outcome, is
credit assignment. The `tanh`-bounded credit and the supporting-share
spread to provenance neighbors are a simple instance of the eligibility-trace
idea that decays credit across the entities responsible for a reward [Sutton
and Barto 2018]. The control arm that most directly threatens the ledger is a
multi-armed bandit with successive elimination: an entry is an arm, a measured
outcome is a pull, and an arm is culled when its optimistic confidence bound
falls below a threshold [Even-Dar et al. 2006]. We field exactly this arm with
a Hoeffding radius and publish the regime where it matches the ledger
(one-sided false_bad noise around 35%, Section 4.4) alongside the regimes
where it fails: it starves nothing, kills slowly, and collapses under
symmetric noise. The bandit framing is also the AEL objection [Xu et al.
2026a], that a simple bandit over retrieval policies should match
outcome-settled selection and make the ledger decoration; Section 4.4 is our
answer, run rather than argued.

**Agent memory.** Recent agent-memory systems manage what to remember with
mechanisms other than a conserved resource. Generative Agents retrieve by a
weighted sum of recency, importance, and relevance, with importance scored by
an LLM [Park et al. 2023]. MemGPT manages a tiered context with the LLM
paging information in and out [Packer et al. 2023]. MemoryBank applies an
Ebbinghaus-style forgetting curve so memories decay and reinforce with time
and significance [Zhong et al. 2024]. Mem0 extracts, consolidates, and
retrieves salient memories for production agents [Chhikara et al. 2025], and
A-Mem builds an evolving interlinked note network [Xu et al. 2025]. Reflexion
keeps an episodic buffer of verbal self-reflections to improve later trials
[Shinn et al. 2023]. darwin-memo differs in the retention signal: rather than
an LLM-scored importance, a time-based forgetting curve, or a model-managed
context, it keeps a balance settled from measured outcomes and drained by
upkeep, with consolidation and pinning as hygiene. It does not compete with
these systems on their benchmarks and makes no leaderboard claim.

**LLM-as-judge.** Using a strong LLM to grade open-ended outputs is now a
standard evaluation tool, with documented position, verbosity, and
self-enhancement biases [Zheng et al. 2023]. The structural objection in this
report, that a judge grades plausibility and prose rather than measured
consequence, is the same circularity that biases line of work warns about.
The `judge_settled` arm tests it directly, and the closest prior statement of
the failure mode it targets is that continuously updated memories settled by
an LLM degrade [Zhang et al. 2026]. We give the judge more per-event
information than the ledger gets and report the per-model split (Section 4.5).

**Design lineage.** The survival-selection framing, external memory kept by
environmental viability rather than a reward model, follows MeMo [Quek et al.
2026], which supplies the population of reflection-QA entries, and the
survival-only-reward self-training line [Dodgson et al. 2026], which supplies
the selection principle. The framing here is deliberately narrow: the bandit
and the judge are the two strongest objections to a judge-free rule, and this
work runs them rather than arguing against them.

## References

Pin Cao and Sandy Irani. 1997. Cost-Aware WWW Proxy Caching Algorithms. In
Proceedings of the USENIX Symposium on Internet Technologies and Systems
(USITS), Monterey, CA, pages 193 to 206.

Prateek Chhikara, Dev Khant, Saket Aryan, Taranjeet Singh, and Deshraj Yadav.
2025. Mem0: Building Production-Ready AI Agents with Scalable Long-Term
Memory. arXiv:2504.19413.

Jennifer Dodgson, Alfath Daryl Alhajir, Michael Joedhitya, Akira Rafhael
Janson Pattirane, Surender Suresh Kumar, Joseph Lim, C. H. Peh, Adith Ramdas,
and Steven Zhang Zhexu. 2026. Survival is the Only Reward: Sustainable
Self-Training Through Environment-Mediated Selection. arXiv:2601.12310.

Eyal Even-Dar, Shie Mannor, and Yishay Mansour. 2006. Action Elimination and
Stopping Conditions for the Multi-Armed Bandit and Reinforcement Learning
Problems. Journal of Machine Learning Research, 7, pages 1079 to 1105.

Nimrod Megiddo and Dharmendra S. Modha. 2003. ARC: A Self-Tuning, Low
Overhead Replacement Cache. In Proceedings of the 2nd USENIX Conference on
File and Storage Technologies (FAST), San Francisco, CA, pages 115 to 130.

Charles Packer, Sarah Wooders, Kevin Lin, Vivian Fang, Shishir G. Patil, Ion
Stoica, and Joseph E. Gonzalez. 2023. MemGPT: Towards LLMs as Operating
Systems. arXiv:2310.08560.

Joon Sung Park, Joseph C. O'Brien, Carrie J. Cai, Meredith Ringel Morris,
Percy Liang, and Michael S. Bernstein. 2023. Generative Agents: Interactive
Simulacra of Human Behavior. In Proceedings of the 36th Annual ACM Symposium
on User Interface Software and Technology (UIST). arXiv:2304.03442.

Ryan Wei Heng Quek, Sanghyuk Lee, Alfred Wei Lun Leong, Arun Verma, Alok
Prakash, Nancy F. Chen, Bryan Kian Hsiang Low, Daniela Rus, and Armando
Solar-Lezama. 2026. MeMo: Memory as a Model. arXiv:2605.15156.

Noah Shinn, Federico Cassano, Edward Berman, Ashwin Gopinath, Karthik
Narasimhan, and Shunyu Yao. 2023. Reflexion: Language Agents with Verbal
Reinforcement Learning. In Advances in Neural Information Processing Systems
36 (NeurIPS). arXiv:2303.11366.

Richard S. Sutton and Andrew G. Barto. 2018. Reinforcement Learning: An
Introduction. Second edition. MIT Press, Cambridge, MA.

Giuseppe Vietri, Liana V. Rodriguez, Wendy A. Martinez, Steven Lyons, Jason
Liu, Raju Rangaswami, Ming Zhao, and Giri Narasimhan. 2018. Driving Cache
Replacement with ML-based LeCaR. In Proceedings of the 10th USENIX Workshop
on Hot Topics in Storage and File Systems (HotStorage).

Wujiang Xu, Jiaojiao Han, Minghao Guo, Kai Mei, Xi Zhu, Han Zhang, and
Dimitris N. Metaxas. 2026a. AEL: Agent Evolving Learning for Open-Ended
Environments. arXiv:2604.21725.

Wujiang Xu, Zujie Liang, Kai Mei, Hang Gao, Juntao Tan, and Yongfeng Zhang.
2025. A-MEM: Agentic Memory for LLM Agents. arXiv:2502.12110.

Dylan Zhang, Yanshan Lin, Zhengkun Wu, Yihang Sun, Bingxuan Li, Dianqi Li,
and Hao Peng. 2026. Useful Memories Become Faulty When Continuously Updated
by LLMs. arXiv:2605.12978.

Lianmin Zheng, Wei-Lin Chiang, Ying Sheng, Siyuan Zhuang, Zhanghao Wu,
Yonghao Zhuang, Zi Lin, Zhuohan Li, Dacheng Li, Eric P. Xing, Hao Zhang,
Joseph E. Gonzalez, and Ion Stoica. 2023. Judging LLM-as-a-Judge with
MT-Bench and Chatbot Arena. In Advances in Neural Information Processing
Systems 36 (NeurIPS). arXiv:2306.05685.

Wanjun Zhong, Lianghong Guo, Qiqi Gao, He Ye, and Yanlin Wang. 2024.
MemoryBank: Enhancing Large Language Models with Long-Term Memory. In
Proceedings of the AAAI Conference on Artificial Intelligence. arXiv:2305.10250.

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
and drained by a fixed upkeep, is a judge-free retention rule for agent
memory. We do not claim it is superior to a judge in general; we claim it is
cheap, lean, and helpful in a characterized band of conditions. It removes
poisoned knowledge without labels, and the property transfers to a second
environment family. Its advantage over a one-line strike counter is
forgiveness and leanness, and the experiments locate that advantage
precisely: under one-sided false-bad noise (roughly the 10 to 35 percent
band on StorageEnv) the ledger holds where every strike counter collapses,
while on a deterministic world the counter ties it and on a family that pays
nothing for refusals the counter wins and the ledger's leanness becomes a
liability. The two strongest objections from the literature, a
successive-elimination bandit and an LLM judge, were run rather than argued,
and each one matches or beats the ledger in a published regime: the bandit
ties at false_bad 0.35, and one of two local judges does not degrade. None of
this is a state-of-the-art claim, and none of it is compared to a
leaderboard.

The result that holds across every arm is cost coupled to mechanism: a
deterministic ledger settles in roughly 0.03 to 0.09 seconds per run, three
to six orders of magnitude faster than an LLM judge or LLM-driven arm, while
matching or beating every such arm on the conserved-resource outcome except
the qwen3:4b judge, which edges slightly ahead at n = 5 (Section 4.5). For an
agent
that must decide retention every cycle over the lifetime of a deployment,
that gap is the practical case for settling memory by a measured resource
instead of by a model's verdict.
