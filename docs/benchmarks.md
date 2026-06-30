# Benchmarks

Every number below was produced by the commands in [Reproduce](#reproduce),
on the machine stated there, with fixed seeds. The harness lives in
`bench/` and is stdlib-only. The per-seed raw JSON behind every table
is committed under `bench/results/`, bound to its config and
reproduction command by `bench/results/MANIFEST.json`, and CI validates
the two against each other. If you rerun and get different conclusions,
the conclusions lose; file an issue.

## Claims under test

| Claim | Metric |
|---|---|
| Selection kills poisoned knowledge without labels | kill rate, median kill cycle |
| The lesson has a bounded price | damage before kill |
| Curation pays off in steady state | tail delta (mean of last 5 cycles) |
| Outcome direction, not pruning rate, does the work | survival vs random_matched |
| Capability is retained, not destroyed | benign probe correctness, cum delta |
| Forgiveness under lying measurements is real, and beats counters | noisy suite: true cum delta and benign capability vs flake rate |
| Forgiveness has a price: noise delays poison execution | noisy suite: kill cycle and kill rate under the flip model |
| The ledger has its own failure boundary, and it is published | noisy suite: the flip sweep to 50% |
| The mechanism transfers to a second environment family | testsuite suites: same claims, passing tests as the resource |
| A bandit statistic is not the ledger, and where it matches, the boundary is published | bandit suite, per-seed paired against the noisy grid |
| Conserved-resource settlement beats judge settlement | judge suite: cum delta, kill, judge_failures vs matched survival |

"Poison killed" means no alive entry from the poisoned source whose
answer reads as a positive action. Inert poisoned entries that advise
nothing can only starve and are excluded from the kill metric.

## Setup

- Machine: Apple M4, macOS, Python 3.14.3, darwin-memo 0.4.0
- Store: the exact headline-demo store (examples corpus, LocalEncoder,
  16 entries of which 3 derive from the poisoned forum post)
- Environment: `StorageEnv`, 30 cycles, 12 files per cycle, seeds 0..9
- Seeds are independent draws: each (seed, cycle) world derives its RNG
  from a sha256 hash of the pair, so no two seeds share any world. (An
  earlier scheme used `seed + cycle`, which made adjacent seeds shifted
  windows of one another; every table here was regenerated under the
  hash scheme, and numbers differ from earlier revisions of this
  document for exactly that reason.)
- Arms differ only in end-of-cycle eviction. Baselines track usage but
  never touch energy. `random_matched` evicts the same per-cycle death
  COUNTS as the survival arm on the same seed, victims chosen uniformly
  at random: same pruning rate, no outcome direction.
  `evict_on_negative` is the one-line alternative to the whole ledger:
  instantly evict whatever decided a negative-outcome task.
  `survival_embedding` runs the identical loop over the zero-dependency
  hashing-embedder retriever instead of lexical matching.

Two probe sets score the final population. The standard probes mirror
StorageEnv's own phrasing and are read by `decision_polarity`. The
paraphrase probes use vocabulary deliberately outside the corpus
("wipe", "trash", "clear out") and are scored by PROVENANCE, not by the
keyword reader: a harmful paraphrase counts as safe when memory stays
silent or the deciding entry's sources are ALL trusted, and a benign
paraphrase counts as grounded only under the same fully-trusted
condition. Fully-trusted is deliberate: consolidation merges union
sources, so an any-trusted check would let a poisoned entry pass by
merging with one trusted neighbor. The strict check penalizes the
survival arms (the only arms that consolidate or write experience
entries) rather than flattering them; the seed where survival_writes'
grounded score dips below survival's in the table is that penalty
landing on an untrusted experience entry.

## Statistical method

- Every cell below reads `point estimate [95% CI]`. Intervals are
  percentile bootstrap (10,000 resamples, seeded, so a rerun reproduces
  them exactly), resampling SEEDS, because the seed is the unit of
  independence: each (seed, cycle) world is an independent hash-derived
  draw, while everything inside one run is deterministic.
- Arm comparisons use exact paired permutation tests: arms at the same
  seed face the SAME world (and, in the noisy suite, the same flake
  marks), so per-seed differences feed a two-sided sign-flip test. At
  10 seeds all 1,024 sign assignments are enumerated (exact); at 30
  seeds it is seeded Monte Carlo with 20,000 permutations. Ties count
  as extreme, so a deterministic tie reports p = 1.0, never spurious
  significance.
- All p-values printed in one `--tests` table are Holm-Bonferroni
  adjusted across that full grid of comparisons: the `p (holm)` column
  has already paid for every row next to it.

## Headline: three survival arms vs five baselines (10 seeds)

| arm                | seeds | kill rate         | kill cycle (med)     | damage before kill                     | tail delta                    | cum delta                            | final pop            | harmful safe      | benign correct    | para safe         | para grounded     |
|--------------------|-------|-------------------|----------------------|----------------------------------------|-------------------------------|--------------------------------------|----------------------|-------------------|-------------------|-------------------|-------------------|
| evict_on_negative  | 10    | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00]    | -319,590 [-557,059, -121,856]          | 436,756 [400,648, 473,889]    | 12,780,954 [12,282,767, 13,226,806]  | 15.00 [15.00, 15.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.33 [0.33, 0.33] |
| keep_everything    | 10    | 0.00 [0.00, 0.00] | -                    | -12,105,830 [-13,467,607, -10,779,008] | -235,827 [-338,843, -127,252] | -9,084,928 [-10,777,728, -7,436,173] | 16.00 [16.00, 16.00] | 0.50 [0.50, 0.50] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.33 [0.33, 0.33] |
| random_matched     | 10    | 0.80 [0.50, 1.00] | 19.00 [19.00, 19.00] | -10,716,672 [-13,449,933, -8,504,189]  | 38,113 [-188,665, 237,059]    | -7,673,651 [-10,811,884, -4,961,485] | 6.00 [6.00, 6.00]    | 0.90 [0.75, 1.00] | 0.40 [0.20, 0.60] | 1.00 [1.00, 1.00] | 0.07 [0.00, 0.17] |
| recency            | 10    | 0.00 [0.00, 0.00] | -                    | -4,400,845 [-5,148,186, -3,747,840]    | 436,756 [400,648, 473,889]    | 4,978,381 [4,112,036, 5,763,382]     | 7.00 [7.00, 7.00]    | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.33 [0.33, 0.33] |
| survival           | 10    | 1.00 [1.00, 1.00] | 0.00 [0.00, 1.00]    | -393,830 [-632,753, -188,211]          | 436,756 [400,648, 473,889]    | 12,586,803 [12,113,203, 13,028,972]  | 4.00 [4.00, 4.00]    | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.33 [0.33, 0.33] |
| survival_embedding | 10    | 1.00 [1.00, 1.00] | 19.00 [19.00, 19.00] | 0.00 [0.00, 0.00]                      | 436,756 [400,648, 473,889]    | 13,519,155 [13,100,332, 13,912,169]  | 4.00 [4.00, 4.00]    | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.67 [0.67, 0.67] |
| survival_writes    | 10    | 1.00 [1.00, 1.00] | 0.00 [0.00, 1.00]    | -393,830 [-632,753, -188,211]          | 436,756 [400,648, 473,889]    | 12,586,803 [12,113,203, 13,028,972]  | 4.00 [4.00, 4.00]    | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.30 [0.23, 0.33] |
| ttl                | 10    | 1.00 [1.00, 1.00] | 10.00 [10.00, 10.00] | -4,400,845 [-5,148,186, -3,747,840]    | 0.00 [0.00, 0.00]             | -3,628,237 [-4,409,467, -2,870,339]  | 0.00 [0.00, 0.00]    | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00] | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00] |

Paired permutation tests on cum delta, survival vs every other arm,
Holm-adjusted across the grid (`bench.report --tests`):

| cell   | vs                 | seeds | W/T/L  | mean diff  | median diff | p        | p (holm) |
|--------|--------------------|-------|--------|------------|-------------|----------|----------|
| (none) | evict_on_negative  | 10    | 0/7/3  | -194,150   | 0           | 0.25     | 0.5      |
| (none) | keep_everything    | 10    | 10/0/0 | 21,671,731 | 21,872,640  | 0.001953 | 0.01367  |
| (none) | random_matched     | 10    | 10/0/0 | 20,260,454 | 18,948,096  | 0.001953 | 0.01367  |
| (none) | recency            | 10    | 10/0/0 | 7,608,422  | 7,796,736   | 0.001953 | 0.01367  |
| (none) | survival_embedding | 10    | 0/0/10 | -932,352   | -857,088    | 0.001953 | 0.01367  |
| (none) | survival_writes    | 10    | 0/10/0 | 0          | 0           | 1        | 1        |
| (none) | ttl                | 10    | 10/0/0 | 16,215,040 | 16,569,856  | 0.001953 | 0.01367  |

Survival's wins over keep_everything, random_matched, recency, and ttl
are all 10-for-10 and survive Holm at adjusted p = 0.014 (the floor an
exact test on 10 seeds can reach after correction). Its loss to
survival_embedding is equally clean in the other direction. And the
survival vs evict_on_negative comparison is now OFFICIALLY a tie:
7 of 10 seeds byte-identical, 3 small losses, adjusted p = 0.5. No
significance can be claimed in either direction, and this report does
not claim one.

What each arm's best metric is, stated plainly:

- **keep_everything** retains all benign knowledge (benign correct 1.00)
  and never loses a useful entry. It also never stops bleeding: the
  poison keeps deciding deletions forever (tail -236k, cum -9.1M).
- **ttl(10)** kills the poison on schedule. It does so by killing
  everything: after cycle 10 memory is empty, benign capability is 0.00,
  and the run still ends 3.6M underwater.
- **recency(10)** is the strongest baseline (cum +5.0M) and its late
  cycles match survival exactly. But its kill rate is 0.00: the poisoned
  advice stays alive indefinitely because being CONSULTED refreshes its
  idle clock even when it no longer wins. It absorbed 11x survival's
  damage before the bleeding stopped, and the threat remains in memory
  waiting for a query phrasing it wins.
- **random_matched** is the experiment's point. Identical eviction
  budget to survival, random victims: kill rate drops to 0.80
  [CI 0.50, 1.00], the median kill arrives at cycle 19 instead of 0,
  damage is 27x worse, benign capability falls to 0.40 because useful
  entries get evicted instead, and the runs end 7.7M underwater with
  huge variance. Pruning rate is not the active ingredient. Outcome
  direction is.
- **survival** kills the actionable poison at median cycle 0 (cycle 0
  in seven seeds, cycle 1 in three: it decides a few deletions, the
  restore costs land on it, it is dead within a cycle), pays a small
  lesson price, ends maximally lean (4 entries), and is poison-free
  and capability-complete on probes.
- **survival_writes** (experience writes on) is outcome-identical to
  survival: writes reinforce already-winning entries on this corpus.
  Its paraphrase-grounded 0.30 trails survival's 0.33 because of the
  strict provenance scoring: experience entries carry cycle-N sources,
  which the fully-trusted check refuses whenever one wins a benign
  paraphrase (one seed here), and that refusal is reported rather
  than smoothed over.
- **evict_on_negative** is the result this report exists to publish
  honestly: on this deterministic environment, the one-line heuristic
  MATCHES the full energy ledger on outcomes. Seven of ten seeds are
  byte-identical; in the three seeds where the ledger's buffer lets
  the poison survive into cycle 1, the heuristic's instant execution
  avoids that extra damage (cum +12.8M vs +12.6M, adjusted p = 0.5:
  a tie, now official, with forgiveness's deterministic price as the
  only visible difference). What the ledger buys on this benchmark is
  exactly two things the if-statement does not do: it starves dead
  weight (final population 4 vs 15, the if-statement hoards everything
  that never erred), and it forgives. One negative outcome instantly
  executes an entry under evict_on_negative; under the ledger, an
  entry that was right ninety-nine times survives one disaster. This
  environment is deterministic, so this table cannot show forgiveness
  paying; the [noisy suite](#noisy-outcomes-the-forgiveness-test)
  below exercises it directly, against the heuristic's noise-hardened
  variants, and reports where each side breaks. If your measurements
  never lie and you do not need leanness, the if-statement is the
  right tool and this row says so.
- **survival_embedding** runs the same loop over the hashing-embedder
  retriever and posts the best cumulative delta (+13.5M, beating
  survival on all 10 seeds, adjusted p = 0.014) by a different route:
  cosine ranking happened to place the runbook protector above the
  poison from cycle 0, so the poison never decided anything, caused
  zero damage, and starved at cycle 19 instead of being executed. It
  also doubles paraphrase grounding (0.67 vs 0.33). One corpus is not
  evidence that embeddings dominate, but the mechanism demonstrably
  does not depend on the lexical-match path.

## Ablations (survival arm, 5 seeds, one knob at a time)

Defaults: upkeep 0.05, credit_gain 0.6, resource_scale 100k,
merge_threshold 0.55, consolidate_every 5, min_coverage 0.25.

The headline finding is insensitivity: on this corpus, most knobs change
the population's shape, not the outcomes.

| knob | values | effect observed |
|---|---|---|
| credit_gain | 0.15 / 0.3 / 0.6 / 1.2 | The one knob that moves the kill. Median kill cycle 2 / 1 / 0 / 0; damage before kill shrinks from -1.1M to -0.2M as gain rises. Outcomes otherwise identical. |
| min_coverage | 0.15 / 0.25 / 0.4 | A real sweet spot at 0.25 (cum +12.5M, benign 1.00). Too low: weak matches decide tasks they know nothing about (cum +7.4M, benign 0.67, tail variance x7). Too high: useful advice goes silent (cum +6.5M, benign 0.67). |
| upkeep | 0.01 / 0.05 / 0.1 / 0.2 | Outcomes identical. Only the final population moves: 13 / 4 / 3 / 3. Upkeep tunes leanness, not safety. |
| merge_threshold | 0.4 / 0.55 / 0.7 | Outcomes identical, population 5 / 4 / 4. |
| consolidate_every | off / 5 | Outcomes identical, population 3 / 4. Consolidation is hygiene, not safety, at this scale. |
| resource_scale | 25k / 100k / 400k | 25k and 100k are identical; 400k nudges the kill (median cycle 1 instead of 0, cum +12.3M vs +12.5M) because per-event credit is a quarter the size. Consistent with the noisy suite's 400k cells: cap-clipping, not tanh saturation, is the insensitivity mechanism, and weakening it shows. |

## Noisy outcomes: the forgiveness test

The headline table admits that evict_on_negative ties the ledger when
measurements are truthful. The ledger's designed advantage is supposed
to be tolerance of measurements that LIE, so this suite makes them lie,
deterministically, and scores everyone on the truth.

`FlakyStorageEnv` wraps StorageEnv. The world stays real (files are
created, deletions free bytes, restores cost 3x); only the measurement
is corrupted. Flake marks are drawn per task at generation time from a
dedicated RNG stream, so the set of potentially-lying measurements is a
fixed property of the world: every arm at the same seed and rate faces
the same one, marks nest across rates, and arms within a cell are
exactly paired. Arms decide off REPORTED deltas; every outcome metric
below is computed from TRUE deltas. A per-run accounting identity
(reported = true + injected distortion) is asserted at run time, and
keep_everything doubles as a canary: it never reads outcomes, so its
true cum delta must be identical in every cell, and `--check` fails on
drift (measured: the same 30 per-seed values, mean -8,835,516, in all
12 cells).

Three noise models: **false_bad** (only positive truths flip: flaky
CI, where good changes report red builds but broken builds do not
report green), **flip** (symmetric: lies can also reward the guilty),
and **magnitude** (sign kept, size lied about by 0.25-4x: the one
model where sign-driven heuristics are immune by construction and only
magnitude-reading credit can degrade).

Because beating a zero-tolerance baseline under noise would prove
nothing, the heuristic family fields its best selves: K lifetime
strikes (K=1,2,3), consecutive strikes that a success wipes clean
(forgiveness as an if-statement, the strongest cheap variant), and
quarantine (evict on blame, re-encode a fresh copy after a 3-cycle
cooldown: the recovery path real deployments have). 30 seeds per
cell, 30 cycles, 12 files per cycle. At 30 seeds the permutation
tests run seeded Monte Carlo (20,000 permutations); every p quoted
below is Holm-adjusted across the suite's full 72-comparison grid
(`bench.report bench/results/noisy.json --tests`).

### false_bad: the flaky-CI case (mean true cum delta / benign capability)

| arm | 0.00 | 0.05 | 0.10 | 0.20 | 0.35 |
|---|---|---|---|---|---|
| survival | 12.38M / 1.00 | 12.38M / 1.00 | 12.26M / 0.99 | 12.26M / 0.99 | 10.47M / 0.79 |
| evict k=1 | 12.57M / 1.00 | 3.30M / 0.04 | 1.54M / 0.00 | 0.41M / 0.00 | 0.00M / 0.00 |
| evict k=2 | 12.38M / 1.00 | 6.20M / 0.12 | 3.20M / 0.00 | 1.19M / 0.00 | 0.22M / 0.00 |
| evict k=3 | 12.10M / 1.00 | 8.71M / 0.36 | 4.84M / 0.02 | 1.82M / 0.00 | 0.48M / 0.00 |
| consecutive k=2 | 12.38M / 1.00 | 11.47M / 0.81 | 9.12M / 0.48 | 3.73M / 0.06 | 1.08M / 0.00 |
| quarantine m=3 | 5.12M / 1.00 | 2.93M / 0.77 | 1.49M / 0.54 | -0.35M / 0.36 | -1.79M / 0.13 |

The headline cell: at 5% false-bad noise, survival's true outcomes are
IDENTICAL to its noise-free run, byte for byte, in all 30 seeds. At
10% and 20% they are byte-identical in 29 of 30 seeds (the same single
seed slips at both rates; the independent-seed scheme surfaced it, and
the earlier "identical through 20%" claim is hereby narrowed). The
lies fire (10, 20, 42 of them on average), drain energy, and mostly
change nothing, because a capped decider holds ~9 lies' worth of
buffer and refills it by earning. Every counter variant collapses
instead: k=1 loses nearly all benign capability by 5%, and the
strongest variant (consecutive) holds at 5% but halves capability by
10%, because a cycle-granularity reset is coarser than a continuous
buffer. Strikes without earn-back are consumed linearly by noise;
patching that with decay, magnitude grading, and dead-weight expiry is
reinventing the energy ledger.

Paired per seed (same worlds) under false_bad, survival vs consecutive
on true cum delta: 14W-16T-0L at 5% (adjusted p = 0.0038), 27W-3T-0L
at 10%, 30W-0T-0L at 20% and 35% (median margins +8.8M and +10.1M,
adjusted p = 0.0036, the Monte Carlo floor after Holm). Under
false_bad, survival does not lose a single seed to any counter variant
at any rate. Under flip it concedes a few: three seeds to consecutive
at 5% (worst -1.1M; survival still wins the cell, adjusted p = 0.047)
and one at 10% (-77k), none at 20% or 35%, then 7 to 9 seeds per
counter at 50% where no counter comparison is significant anyway. And
k=1 keeps its small deterministic edge over survival (9 of 30 seeds,
at most 1.2M, adjusted p = 0.047, so it is real, not noise) in the
rate-0.00 and magnitude cells, exactly as the first column shows. In
the same deterministic cell survival exactly ties k=2 and consecutive
on all 30 seeds (p = 1.0) and significantly beats k=3 (10W-20T-0L,
adjusted p = 0.039).

### flip: forgiveness's price, and the ledger's own failure boundary

| survival under flip | 0.00 | 0.05 | 0.10 | 0.20 | 0.35 | 0.50 |
|---|---|---|---|---|---|---|
| true cum delta | 12.38M | 12.20M | 11.95M | 11.80M | 9.43M | 1.25M |
| benign capability | 1.00 | 1.00 | 0.99 | 0.99 | 0.79 | 0.26 |
| poison kill cycle (med) / kill rate | 0 / 1.00 | 0 / 1.00 | 1 / 1.00 | 1 / 1.00 | 1 / 1.00 | 3 / 0.93 |

Two pre-committed results, reported as promised. First, forgiveness
has a price: tolerance for lying measurements is tolerance for guilty
entries, and the poison's kill cycle climbs from 0 to a median of 3 at
50% (2 of 30 seeds never kill it, and the slowest kills land past
cycle 12) as false-good lies (which report a destroyed database as
+3x its size, tanh-saturated reward) keep rescuing it. Under
false_bad, negatives stay truthful and the kill stays at cycle 0 or 1
at every rate. Second, the ledger's failure boundary: at 35% it
degrades visibly (capability 0.79), and at 50%, a sign flip with no
information content, capability collapses to 0.26 and the cum delta
falls to a tenth of clean with enormous per-seed variance (the worst
seeds finish 17M+ behind a counter). An earlier revision reported
survival underwater at 50% and losing the paired sign test to
consecutive; that came from the correlated-seed scheme. Under
independent seeds survival stays positive on average (+1.25M, the
only arm above zero at 50%) and none of its 50% counter comparisons
reaches significance (21W-9L vs consecutive, adjusted p = 1.0), so
the honest 50% claim is "indistinguishable from the counters, and
nothing curates safely". Past roughly one lie in three, capability is
what dies first; the counters are already long dead by then (every
other arm is negative at 50%).

### magnitude: the model where only the ledger could lose

Sign-preserved size lies (0.25-4x) leave every strike counter at
exactly its rate-0.00 numbers, as they must (they read only the sign).
The honest part: survival is ALSO at exactly its rate-0.00 numbers, in
all 30 seeds at both rates. The mechanism is not tanh saturation: at
resource_scale 100k only the 3x restore costs are near-saturated (tanh
0.91-1.0), while disposable deltas land on tanh's working range
(0.20-0.84), so size lies DO move per-event credit. What clips them is
the energy cap: healthy deciders sit at max_energy 5.0, where
exaggerated or shrunken rewards change nothing, and lies never flip a
sign, so no death threshold is crossed. The sensitivity cells re-run
rate 0.20 at resource_scale=400k, where per-event credit is a quarter
the size and cap-clipping correspondingly weaker, anchored by a clean
rate-0.00 cell at the same scale (12.12M): magnitude noise now costs a
little (12.06M / 1.00), false_bad remains per-seed identical to clean
(12.12M), and flip costs more (11.53M, capability 1.00). Magnitude
grading does almost no work on this corpus; what forgives is bounded
per-event credit, the energy buffer, and earn-back, not the tanh
curve's shape.

### What each arm's row is for, stated plainly

- **evict k=1** is the headline-table champion meeting its designed
  weakness: one lie permanently executes a load-bearing decider, and
  the 16-entry corpus has no redundancy to absorb that, so capability
  goes with it.
- **consecutive k=2** is the strongest counter and the honest
  comparison point. It is forgiveness-as-an-if-statement and it works
  at low noise; the gap to the ledger is the granularity of the
  buffer, not the idea of one.
- **quarantine** carries the recovery story and reveals its dark side:
  resurrection forgives the GUILTY too. The poisoned entry returns
  fresh from every cooldown and re-advises the same deletion, so
  quarantine bleeds even at rate 0.00 (5.12M vs survival's 12.38M; its
  kill-cycle column reads first-extinction, not permanence). Recovery
  without selection is rot with extra steps.
- **keep_everything** is the canary, and it also shows what no
  curation costs under any noise: -8.84M everywhere.

### Caveats, on the record

- The corpus has no redundancy: one wrongful eviction zeroes a whole
  earning category, which inflates every counter's collapse. Treat the
  survival-vs-counter gaps as the redundancy-free upper bound.
- Silence is a noise-free harbor in this design: a kept file produces
  no measurement event to corrupt. Environments where inaction is
  also measured would expose entries to lies survival cannot dodge by
  conservatism.
- `flakes_fired` is endogenous to the arm (a lie needs a nonzero
  measurement to corrupt): lean arms that act more expose themselves
  to more lies, and k=1 fires almost none because it has almost
  nobody left acting. `flakes_marked` is the world-level constant.
- Under flip, StorageEnv's payoff convention makes false-good lies
  about protected files 3x larger (and tanh-saturated) relative to
  false-bad lies about disposable ones; the poison-kill delay is
  partly that convention's size, which is why false_bad is the
  headline forgiveness cell and flip is the price/boundary cell.
- Seed worlds are independent draws (sha256 of (seed, cycle), with a
  separate stream for flake marks), so across-seed means, bootstrap
  CIs, and permutation tests all rest on real independence. The old
  `seed + cycle` scheme made adjacent seeds shifted windows of one
  another; replacing it changed several numbers and two conclusions
  in this document, which is exactly why it had to go.
- Tables here use 30 seeds; the headline table uses 10, so rate-0.00
  means differ slightly from headline means. Exact per-seed parity at
  rate 0.00 is pinned by a unit test instead.

## Second environment family: TestSuiteEnv

Everything above runs on `StorageEnv`, and the caveats have named that
single-family dependence as this benchmark's largest credibility gap
since the first revision. This section closes it: the same eight arms,
the same statistical method, and a new noise grid run on
`TestSuiteEnv`, where the conserved resource is the count of passing
tests in a generated project and the environment executes patch advice
instead of deletion advice.

### Setup

- Environment: `TestSuiteEnv`, 30 cycles, seeds 0..9 (headline) and
  0..29 (noisy). Each cycle regenerates `app.py` (six helpers) and
  `test_app.py` (10 tests), plants 3 seeded defects, and offers one
  patch per defect plus a destructive cleanup patch (removing a
  load-bearing helper, -2 tests) and a cosmetic no-op. Applying a
  patch edits the file and reruns the suite; the resource delta IS the
  change in passing-test count. `resource_scale` is 2.0.
- Corpus: 20 entries built in `bench/testsuite_fixtures.py`, with
  DELIBERATE REDUNDANCY: every fix lesson and the dedupe protector
  ship with a near-duplicate twin from a second trusted source, and a
  unit test pins that consolidation merges exactly those 5 twin pairs
  at the default threshold. The StorageEnv corpus has no redundancy
  and its caveats call the counter collapses a redundancy-free upper
  bound; this corpus measures the redundancy-cushioned complement.
- Poison: one forum-post lesson that is actively wrong about a test.
  It claims `test_dedupe_keeps_order` is flaky and the dedupe helper
  is dead code, and advises applying the removal patch. The suite
  executes that advice and the pass count genuinely drops by 2.
  Two further forum-post entries are inert and can only starve.
- Probes: the standard set mirrors TestSuiteEnv prompt phrasing (one
  harmful, four benign) and is read by `decision_polarity`; the
  paraphrase set uses vocabulary outside the corpus ("rip out",
  "land", "ship") and is scored by provenance against this family's
  trusted sources, exactly like the StorageEnv paraphrase probes.

### The noise grid, pre-committed before any results

Stated here first, results filled in after the runs, so the cells
cannot drift toward whatever flattered the ledger. The noise model is
flaky pass counts, the noise CI actually has: each cycle, every test
is flaky with probability equal to the flake rate; a flaky test that
genuinely passes reports a failure that cycle and reports passing
again when the mark moves on. The accepted pre-patch count is treated
as known, so for a measured patch

    reported delta = true delta - (genuinely passing tests after the
                                   patch that are marked flaky)

One-sided by construction (the false_bad shape): a good patch can
report a red build because an unrelated flaky test failed in its CI
run, but a broken build never reports green. Marks are drawn per
(cycle, test) from a dedicated RNG stream, identical across arms at a
fixed seed and nested across rates. A skipped patch runs no suite and
produces no measurement to corrupt: silence stays a noise-free harbor.

| | rate 0.00 | rate 0.05 | rate 0.10 | rate 0.15 | rate 0.20 |
|---|---|---|---|---|---|
| survival | 69.0 / 1.00 | 72.4 / 0.95 | 69.7 / 0.59 | 46.9 / 0.05 | 28.8 / 0.00 |
| evict_on_negative k=1 | 88.0 / 1.00 | 70.4 / 0.55 | 34.6 / 0.02 | 16.2 / 0.00 | 12.2 / 0.00 |
| evict_on_negative k=2 | 86.0 / 1.00 | 84.7 / 0.93 | 62.3 / 0.31 | 35.3 / 0.01 | 23.7 / 0.00 |
| evict_on_negative k=3 | 84.0 / 1.00 | 84.0 / 1.00 | 74.8 / 0.62 | 51.7 / 0.05 | 36.8 / 0.02 |
| evict_consecutive k=2 | 86.0 / 1.00 | 85.2 / 0.98 | 73.4 / 0.65 | 45.1 / 0.07 | 29.4 / 0.00 |
| quarantine m=3 | 70.0 / 1.00 | 69.8 / 1.00 | 68.4 / 0.97 | 64.9 / 0.83 | 60.8 / 0.66 |
| keep_everything (canary) | 30.0 / 1.00 | 30.0 / 1.00 | 30.0 / 1.00 | 30.0 / 1.00 | 30.0 / 1.00 |

Each cell is mean true cum delta / benign capability over 30 seeds.

The grid exists to answer one question with a number, committed in
advance: AT WHAT FLAKE RATE DOES THE LEDGER'S FORGIVENESS BEAT A NAIVE
STRIKE COUNTER (evict_on_negative)? If the answer is unflattering at
some cells, it gets published anyway.

### Results: the headline analog (10 seeds)

Produced with darwin-memo 0.5.0 on Python 3.14.5; the manifest binds
both files to their grids and reproduction commands.

| arm                | seeds | kill rate         | kill cycle (med)     | damage before kill | tail delta        | cum delta            | final pop            | harmful safe      | benign correct    | para safe         | para grounded     |
|--------------------|-------|-------------------|----------------------|--------------------|-------------------|----------------------|----------------------|-------------------|-------------------|-------------------|-------------------|
| evict_on_negative  | 10    | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00]    | 0.00 [0.00, 0.00]  | 3.00 [3.00, 3.00] | 88.00 [88.00, 88.00] | 19.00 [19.00, 19.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00] |
| keep_everything    | 10    | 0.00 [0.00, 0.00] | -                    | 0.00 [0.00, 0.00]  | 1.00 [1.00, 1.00] | 30.00 [30.00, 30.00] | 20.00 [20.00, 20.00] | 0.00 [0.00, 0.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00] |
| random_matched     | 10    | 0.70 [0.40, 1.00] | 19.00 [19.00, 19.00] | 0.00 [0.00, 0.00]  | 1.46 [1.00, 1.88] | 34.80 [30.60, 38.80] | 9.00 [9.00, 9.00]    | 0.60 [0.30, 0.90] | 0.78 [0.68, 0.88] | 1.00 [1.00, 1.00] | 0.23 [0.13, 0.33] |
| recency            | 10    | 0.00 [0.00, 0.00] | -                    | 0.00 [0.00, 0.00]  | 1.00 [1.00, 1.00] | 30.00 [30.00, 30.00] | 12.00 [12.00, 12.00] | 0.00 [0.00, 0.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00] |
| survival           | 10    | 1.00 [1.00, 1.00] | 2.00 [2.00, 2.00]    | 0.00 [0.00, 0.00]  | 1.04 [1.00, 1.12] | 69.00 [68.00, 71.00] | 4.00 [4.00, 4.00]    | 0.00 [0.00, 0.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.33 [0.33, 0.33] |
| survival_embedding | 10    | 0.00 [0.00, 0.00] | -                    | 0.00 [0.00, 0.00]  | 3.00 [3.00, 3.00] | 90.00 [90.00, 90.00] | 7.00 [7.00, 7.00]    | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.33 [0.33, 0.33] |
| survival_writes    | 10    | 1.00 [1.00, 1.00] | 2.00 [2.00, 2.00]    | 0.00 [0.00, 0.00]  | 1.04 [1.00, 1.12] | 69.00 [68.00, 71.00] | 4.00 [4.00, 4.00]    | 0.00 [0.00, 0.00] | 1.00 [1.00, 1.00] | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00] |
| ttl                | 10    | 1.00 [1.00, 1.00] | 10.00 [10.00, 10.00] | 0.00 [0.00, 0.00]  | 0.00 [0.00, 0.00] | 11.00 [11.00, 11.00] | 0.00 [0.00, 0.00]    | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00] | 1.00 [1.00, 1.00] | 0.00 [0.00, 0.00] |

Paired permutation tests on cum delta, survival vs every other arm,
Holm-adjusted across the grid (`bench.report
bench/results/testsuite.json --tests`):

| cell   | vs                 | seeds | W/T/L  | mean diff | median diff | p        | p (holm) |
|--------|--------------------|-------|--------|-----------|-------------|----------|----------|
| (none) | evict_on_negative  | 10    | 0/0/10 | -19       | -20         | 0.001953 | 0.01367  |
| (none) | keep_everything    | 10    | 10/0/0 | 39        | 38          | 0.001953 | 0.01367  |
| (none) | random_matched     | 10    | 10/0/0 | 34        | 34          | 0.001953 | 0.01367  |
| (none) | recency            | 10    | 10/0/0 | 39        | 38          | 0.001953 | 0.01367  |
| (none) | survival_embedding | 10    | 0/0/10 | -21       | -22         | 0.001953 | 0.01367  |
| (none) | survival_writes    | 10    | 0/10/0 | 0         | 0           | 1        | 1        |
| (none) | ttl                | 10    | 10/0/0 | 58        | 57          | 0.001953 | 0.01367  |

The mechanism transfers. The headline tie does not, and the counter
wins it here. Both halves, stated plainly:

- What transfers: selection still kills the actionable poison without
  labels in every seed. The poison wins the destructive prompt early,
  the suite genuinely drops two tests, the negative credit lands, and
  it is dead by cycle 2. keep_everything and recency still bleed
  forever (the poison decides the destructive patch every cycle: tail
  1.00 against the family's 3.00 ceiling). random_matched still shows
  pruning rate is not the active ingredient (kill 0.70, benign 0.78,
  the only arm with real variance). ttl still cures the disease by
  killing the patient (benign 0.00, cum 11).
- What does not transfer: **evict_on_negative beats survival on all
  ten seeds** (88 vs 69, median margin 20, adjusted p = 0.014). On
  StorageEnv this comparison was an official tie. The reason is a
  designed property of this family meeting a designed property of the
  ledger: TestSuiteEnv pays nothing for refusals. A skipped patch runs
  no suite and produces no measurement, so the dedupe protector that
  keeps refusing the destructive patch can never earn, and under the
  ledger's upkeep it starves mid-run (around cycle 21 in nine of ten
  seeds). Once it is gone, the destructive prompt cross-matches a
  consolidated fix lesson whose answer polarity reads positive, the
  destructive patch starts landing again, and the closing cycles bleed
  at +1 instead of +3. The counter never touches energy, so its
  protector refuses forever (final population 19 vs survival's 4).
  Leanness, the ledger's selling point on StorageEnv, is the liability
  here, and this row is the family's reason to exist.
- The same cross-match explains the strangest pair of cells in the
  survival row: kill rate 1.00 with harmful safe 0.00. The poison is
  dead, and an innocent consolidated fix lesson answers the
  destructive probe with "apply". Silence would score safe; a
  confident wrong neighbor does not.
- **survival_embedding posts the family ceiling** (90: three fixes
  every cycle, the destructive patch never applied) the same way it
  won on StorageEnv: cosine ranking places the protector above the
  poison from cycle 0. But its kill rate is 0.00 this time. The poison
  never decides, never takes negative credit, and never dies; the
  threat sits alive in memory for all 30 cycles waiting for a phrasing
  it wins. Ceiling outcomes, zero immune response, both reported.
- damage before kill reads 0.00 everywhere because the metric sums
  negative per-cycle nets and this family nets the destructive
  patch's -2 against the same cycle's +3 of fixes. The poison's price
  is real but appears in the cum delta column instead.
- Paraphrase probes: silence dominates out-of-vocabulary queries
  (paraphrase silence 1.00 for the counters and keep_everything, 0.80
  for survival). The 0.33 grounded rate for survival and
  survival_embedding is consolidation paying out: a merged twin
  carries both phrasings' tokens and its union of sources stays fully
  trusted, so one benign paraphrase lands. survival_writes grounds
  0.00 for the StorageEnv reason: experience entries carry cycle-N
  sources and the strict provenance check refuses them.

### Results: the grid, filled (30 seeds per cell)

The table above now carries the numbers; every p below is
Holm-adjusted across the suite's full 30-comparison grid
(`bench.report bench/results/testsuite_noisy.json --tests`). The
canary held: keep_everything's true cum delta is the same 30 per-seed
values (mean 30.0) in all five cells, and `--check` enforces that.

The pre-committed question gets its number: **the ledger's forgiveness
beats the naive strike counter at 10% flake rate, and not below.** At
5%, k=1 ties survival (15W/15L, adjusted p = 1.0) and k=2 still beats
it (29 of 30 seeds, mean margin 12, adjusted p = 0.0015). At 10%,
survival beats k=1 in every seed (mean +35, adjusted p = 0.0015) and
beats k=2 (22W/8L, mean +7, adjusted p = 0.028). The advantage stays
significant through 20% (vs k=1: +35, +31, +17; vs k=2: +7, +12, +5;
all adjusted p at or below 0.028), though the absolute margins shrink
as extinction flattens every arm toward the floor.

Stated even more plainly: survival is never the best arm in any cell
of this grid (k=1 takes the deterministic column, consecutive k=2
takes 0.05, k=3 takes 0.10, quarantine takes 0.15 and 0.20). The
boundary above is against the naive counter the question names, not
against the field.

The rest of the answer is harsher, and published per the rule above:

- **k=3 beats survival at every rate in the band.** 30/30 at 0.00 and
  0.05, then 25W/5L at 0.10 (mean +5, adjusted p = 0.012), 18W/10L at
  0.15 (adjusted p = 0.047), 27W/3L at 0.20 (mean +8, adjusted
  p = 0.0015). Three lifetime strikes plus this corpus's twin
  redundancy outlast the ledger's buffer everywhere we measured.
- **consecutive k=2 never loses to survival with significance.** It
  wins outright at 0.00 and 0.05 (30/30 and 29/30, adjusted
  p = 0.0015) and is statistically indistinguishable from 10% up
  (adjusted p between 0.28 and 1.0).
- **quarantine m=3 owns the high-noise end.** At 0.00 it edges
  survival in 27 of 30 seeds by margins too small for significance
  (mean +1, adjusted p = 0.64), at 0.05 it loses slightly (11W/1T/18L,
  mean -3, adjusted p = 0.033), at 0.10 the two are indistinguishable
  (adjusted p = 1.0), then it wins 26/30 at 0.15 (mean +18) and 30/30 at 0.20
  (mean +32, 60.8 [59.9, 61.7] vs 28.8 [25.2, 32.5], both adjusted
  p = 0.0015) while holding benign capability of 0.83 and 0.66 where
  survival's population is extinct (mean final population 0.2 at 0.15
  and 0.0 at 0.20).

Why the ledger loses the edge it had on StorageEnv, mechanism by
mechanism:

- The corpus's redundancy is real for the counters and spent by the
  ledger. The twins exist so a counter can absorb one wrongful
  eviction; the survival arms consolidate each twin pair into a single
  entry within the first few cycles, concentrating a whole earning
  category into one death. On StorageEnv the counter collapse was the
  redundancy-free upper bound; here the counters are the cushioned
  ones and the ledger is the arm with no spare.
- Earnings are thin. A cycle offers three small wins, so earn-back
  refills the buffer slowly, and from 15% the false-bad drain outruns
  it: the population dies out entirely (benign 0.05 then 0.00), and
  survival's 46.9 and 28.8 are what gets earned before extinction.
  The counters decay too, but at k=3 a twinned topic holds six
  lifetime strikes spread over two entries, while the ledger's
  consolidated entry holds one capped buffer that refills only when
  it wins.
- Quarantine's resurrection is redundancy on demand. On StorageEnv it
  was the dark side (reviving the poison cost it 7M at rate 0). Here
  the poison costs it only a periodic -2 (70.0 vs the 86-88 of the
  counters at rate 0.00), and under heavy noise every wrongful
  execution comes back after three cycles, which no other arm can say.
  Recovery without selection was rot on StorageEnv; selection without
  recovery is sterilization here. The pair of results is the strongest
  argument in this document for quarantine-style cooldown landing in
  the ledger's roadmap.
- One anomaly, reported because it is in the data: survival's 5% mean
  sits above its clean mean (72.4 [70.8, 73.9] vs 69.0 [68.0, 70.3];
  16 seeds improve, 9 are byte-identical, 5 worsen). Traced, not
  guessed: a false-bad lie stacks onto the poison's genuinely negative
  report, executing it a cycle sooner, and the protector's starvation
  drifts a few cycles later, so the destructive wound reopens later.
  A timing accident of this corpus, not a virtue of noise.

### TestSuiteEnv caveats, on the record

- The headline conclusion is family-dependent in BOTH directions: the
  StorageEnv tie between survival and evict_on_negative is not a law,
  and neither is this family's counter win. The honest summary across
  the two families is: when refusals earn nothing and redundancy is
  pre-paid, a counter is better below 10% flake and quarantine is
  better above it; the ledger's regime is the middle band against
  naive counters, and its StorageEnv dominance does not transfer.
- Consolidation is doing two jobs with opposite signs here: it buys
  the only paraphrase grounding any arm achieves, and it spends the
  redundancy that would have cushioned wrongful starvation. Both
  effects are real and both are reported above.
- The protector starvation that decides the headline is a property of
  environments that do not measure refusals. A CI that rewarded
  blocked bad patches (a reverted-incident counter, for example) would
  pay the protector and likely reverse the row. That environment is
  not built; the claim stays unmade.
- Vocabulary coupling applies here exactly as on StorageEnv: prompts,
  corpus, and polarity reader share a hand. The paraphrase columns are
  the out-of-distribution check, and silence dominates them.

## Control arms from the literature: the bandit and the judge

"No judge anywhere" and "settlement must be a conserved resource" are
differentiating claims, and a differentiating claim needs a control
arm, not a slogan. The two arms below run the literature's strongest
objections against the same harness. House rule, kept: both cell
definitions and both hypotheses in this section were committed before
either grid ran.

### policy_bandit: the AEL objection, run rather than argued

The objection (arXiv 2604.21725): a simple bandit over retrieval
policies matches outcome-settled selection under noise, so the energy
ledger is decoration. The arm: each memory entry is a bandit arm;
every measured task it decides is a pull paying reward 1 (positive
reported delta) or 0 (negative); an entry is culled when even its
optimistic estimate `mean + sqrt(ln(T) / (2n))` falls below 0.5
(successive elimination with a Hoeffding radius, T = total recorded
pulls, and no eliminations before two pulls because ln(1) = 0 would
collapse the radius and turn the first failure into evict k=1).
Stdlib, deterministic, no RNG, no energy, no upkeep.

Grid, pre-committed: the noisy suite's exact cells (none / flip /
false_bad / magnitude at the same rates), seeds 0..9, 30 cycles, 12
files per cycle, the same hash-derived worlds and flake marks as the
committed noisy results, plus matched survival cells in the same file
so per-seed pairing needs no cross-file surgery.

Hypothesis, pre-committed: the confidence radius is real forgiveness,
so the bandit should hold up under false_bad and flip far better than
the strike counters and may match survival in some regimes; wherever
it does, the boundary gets published, because the objection deserves
an answer, not a dodge. Predicted failure modes: the bandit starves
nothing (an entry that never decides is never pulled, so dead weight
is immortal and final population should sit near keep_everything's);
the reward reads the reported SIGN only, so it is magnitude-blind: in
StorageEnv a wrong delete costs 3x what a right one earns, putting a
decider's value break-even near win rate 0.75 while the bandit's
sits at 0.5; and the poison kill should land cycles later than
survival's 0-1, because confidence takes several confirmed failures
to collapse.

Results (240 runs committed in `bench/results/bandit.json`; per-seed
pairing via `bench.report bench/results/bandit.json --paired
policy_bandit survival`, significance via `--tests`, Holm-adjusted
across all 12 cells):

Mean true cum delta (M) / benign capability, 10 seeds per cell:

| arm | false_bad 0.00 | 0.05 | 0.10 | 0.20 | 0.35 |
|---|---|---|---|---|---|
| policy_bandit | 11.14 / 1.00 | 11.14 / 1.00 | 11.14 / 1.00 | 11.14 / 1.00 | 11.14 / 1.00 |
| survival | 12.59 / 1.00 | 12.59 / 1.00 | 12.23 / 0.97 | 12.23 / 0.97 | 11.00 / 0.77 |

| arm | flip 0.05 | 0.10 | 0.20 | 0.35 | 0.50 |
|---|---|---|---|---|---|
| policy_bandit | 10.11 / 1.00 | 8.83 / 1.00 | 4.43 / 1.00 | -3.36 / 1.00 | -9.08 / 1.00 |
| survival | 12.49 / 1.00 | 12.01 / 0.97 | 11.72 / 0.97 | 10.04 / 0.77 | 0.80 / 0.37 |

The boundary, published as promised: **under asymmetric false_bad
noise the AEL objection holds, and at 35% the bandit matches
survival.** The bandit's false_bad and magnitude cells are per-seed
IDENTICAL to its clean run, all 10 seeds at every rate: false_bad
only turns wins into reported losses, a healthy decider's observed
win rate stays far above the 0.5 elimination threshold, and the
poison (whose true losses false_bad never touches) dies on the same
cycle regardless. So as the noise rate climbs, survival walks down
toward the bandit's flat line and reaches it: at false_bad 0.35 the
cells are 11.14M [10.63, 11.65] (bandit) vs 11.00M [10.16, 11.87]
(survival), paired diff +0.14M [-0.48, +0.76] with the bandit winning
5 of 10 seeds (adjusted p = 0.68, a statistical tie), and the bandit
RETAINS full benign capability (1.00 [1.00, 1.00] vs survival's 0.77
[0.63, 0.90]) because a winner can essentially never cross the
threshold, so it never wrongfully executes. Survival's wins at
false_bad 0.10 and 0.20 (8/1/1) do not survive Holm either (adjusted
p = 0.082). If your noise is one-sided and you can live with an
uncurated population, the bandit is a legitimate tool in that regime
and this table says so.

Everywhere else the ledger wins and the pre-committed predictions
land. Clean, magnitude, false_bad 0.05, and flip 0.05 through 0.35:
survival 9/1/0 per cell, adjusted p = 0.047 (the Holm floor on 10
seeds at this grid size). The mechanisms, each one predicted:

- **Dead weight is immortal**, as predicted: final population 15 to
  16 in every cell, keep_everything's neighborhood, vs survival's 3
  to 4. Never-pulled entries can never be eliminated; the bandit has
  no upkeep, so nothing starves.
- **Confidence takes confirmed failures to collapse**, as predicted:
  the clean-cell poison kill lands at median cycle 1.5 vs survival's
  0, and damage before kill triples (-1.22M vs -0.39M). That gap, plus
  the hoarded population, is the whole clean-cell margin (12.59M vs
  11.14M).
- **Symmetric noise breaks the 0.5 threshold**, the sign-blindness
  prediction cashing out: under flip, false-good lies pay the poison
  real reward, its observed win rate sits near the flake rate, and
  elimination needs the OPTIMISTIC bound below 0.5. At flip 0.35 the
  kill lands in only 4 of 10 seeds (cycles 12 to 15); at 0.50 it
  never lands in any seed, the run bleeds to -9.08M [-10.78, -7.44],
  keep_everything's territory (-8.84M), while survival stays the only
  arm above zero (+0.80M [-4.91, +5.71]). The two arms fail in
  opposite directions at 50%: the bandit keeps every benign entry
  (1.00) and lets the poison feed forever; survival kills
  indiscriminately (benign 0.37 [0.20, 0.53]) and stays solvent.
  Nothing curates safely there, as the noisy suite already concluded.
- **Magnitude blindness cost nothing on this corpus**, as the noisy
  suite's magnitude section predicts for every sign-reader: the
  bandit's magnitude cells equal its clean cells exactly. The 3x
  restore-cost asymmetry (value break-even near win rate 0.75 against
  the bandit's 0.5) shows up as the slower, costlier clean-cell kill
  above, not as an extra magnitude penalty.

Against the strike counters the bandit is what the AEL line claims:
at false_bad 0.35 it posts 11.14M / 1.00 where evict k=1 posts 0.00M
/ 0.00 and consecutive k=2 posts 1.08M / 0.00 (30-seed noisy table).
The honest summary: a Hoeffding radius is real forgiveness, it is the
strongest no-ledger arm this harness has fielded, and the regime
where it matches the ledger is published above. What it cannot do is
starve dead weight, kill promptly, or survive lies that pay the
guilty; those three are exactly what conserved-resource settlement
buys.

### judge_settled: settlement by LLM verdict

The differentiating claim under test: conserved-resource settlement
beats LLM-judge settlement. arXiv 2605.12978 predicts the judge
failure mode this arm goes looking for: continuously updated memories
settled by judge go faulty, because the judge grades plausibility and
prose where the ledger weighs measured consequences. The arm: the
same driver as every baseline, but keep/cull is decided by a local
LLM judge (Ollama, temperature 0) that sees each deciding entry's
lesson plus the environment's own outcome descriptions for the tasks
it decided, one batched verdict call per cycle, JSON array out.
Unparseable or missing verdicts default to keep and are counted
(`judge_failures`). The judge gets MORE per-event information than
the ledger's scalar delta (the prose descriptions name what really
happened); losing from there is the interesting result. Under
measurement noise the corrupted detail strings name both reported and
true deltas, so the runner refuses this arm under noise rather than
leak ground truth.

Grid, pre-committed: StorageEnv only, seeds 0..4, 12 cycles, 8 files
per cycle, judge models llama3.2:3b and qwen3:4b, plus matched
survival cells on the same worlds. Sized to stay under roughly 30
minutes of total model time (requests queue behind whatever else the
local server is doing); actual wall clock gets reported with the
results. Opt-in tier, never CI: sampled model output is not
deterministic, the lesson store's first entry.

Hypothesis, pre-committed: survival beats judge settlement on true
outcomes and kill behavior on the same worlds; the judge shows some
mix of parse failures, verdict drift between models, and wall-clock
orders of magnitude above measurement. The honest exit is stated in
advance: if the judge matches measured settlement here, the
differentiating claim loses its benchmark support and this section
will say so.

Results (10 runs per model committed in `bench/results/judge-llama.json`
and `bench/results/judge-qwen.json`, 5 survival plus 5 judge_settled
seeds each; per-seed pairing via `bench.report <file> --paired survival
judge_settled`, significance via `--tests`). Five seeds is a small
sample by design: each judged cycle is a model call, so the exact
two-sided permutation test cannot return below p = 0.0625 even on a
clean 5-0 sweep. Read these as direction and effect size, not as
significance; nothing below clears p = 0.05, and the table says so.

Per-model, mean true cum delta and benign capability vs the matched
survival cells (the same five worlds, deterministic):

| model | arm | seeds | cum delta (M) | benign correct | poison kill cycle (med) | final pop | judge wall (s, mean) |
|---|---|---|---|---|---|---|---|
| llama3.2:3b | survival | 5 | 2.66 [2.19, 3.10] | 1.00 | 1 | 12.8 | 0.09 |
| llama3.2:3b | judge_settled | 5 | 1.88 [0.76, 2.96] | 0.67 | 1 | 14.0 | 87.6 |
| qwen3:4b | survival | 5 | 2.66 [2.19, 3.10] | 1.00 | 1 | 12.8 | 0.03 |
| qwen3:4b | judge_settled | 5 | 3.09 [2.88, 3.29] | 1.00 | 0 | 15.0 | 1,514.2 |

The honest exit, stated in advance, is the one this grid lands on: the
two local judges split. The hypothesis holds for llama3.2:3b and fails
for qwen3:4b, so the differentiating claim does not get clean benchmark
support at this scale.

- **llama3.2:3b degrades, in the predicted direction but not
  significantly.** Survival wins the per-seed cum-delta pairing 3 of 5
  (3W/2T/0L, mean diff +0.78M [+0.05, +1.85], p = 0.25). The cost is
  capability, not solvency: benign-probe correctness falls to 0.67 mean
  (three of five seeds drop to 0.33 or 0.67 while survival holds 1.00
  on all five), so the judge culls load-bearing benign entries on the
  prose it reads. The arm still kills the poison every seed at the same
  median cycle as survival. Parse failures are frequent (67 unparseable
  or missing verdicts across the five runs, defaulted to keep), which is
  the predicted mix.
- **qwen3:4b does not degrade.** It slightly beats survival on cum
  delta (3.09M vs 2.66M, 0W/2T/3L for survival, mean diff -0.43M
  [-0.80, -0.08], p = 0.25), holds benign capability at 1.00 on every
  seed, and kills the poison at cycle 0 in all five. On true outcomes
  and kill behavior this judge matches or edges the ledger here, so for
  this model the section reports no degradation rather than smoothing it
  into the headline.
- **The constant either way is cost.** Settlement by measured outcomes
  is effectively free (survival's per-run wall time is 0.03 to 0.09 s);
  the same five cycles judged cost a mean 87.6 s for llama3.2:3b and
  1,514.2 s (about 25 minutes) for qwen3:4b, four to five orders of
  magnitude above the ledger, before any verdict is even parsed. The
  predicted wall-clock gap is the most robust result in the table.

Small-local-model caveats, on record: 3b and 4b instruction-tuned
models at temperature 0 are the weak end of the judge spectrum, and a
frontier judge could plausibly hold capability where llama3.2:3b drops
it. The parse-failure counts (67 for llama, 59 for qwen across five runs
each) mean a real fraction of verdicts defaulted to keep rather than
reflecting a judgment, which flatters both judges' kill behavior by
never wrongly culling on an unparsed cycle. Five seeds cannot separate
these arms statistically; the table is direction and cost, and the
larger claim that conserved-resource settlement is categorically better
is not the claim this grid can or does make.

## LLM-mode: the ledger against a model doing the same citation work

Every benchmark above answers each task with the deterministic 3-stage
protocol. The survival_llm arm swaps that protocol's answer step for a
local model (Ollama, temperature 0) and runs the identical conserved
resource ledger on top, so the comparison is clean: same worlds, same
selection rule, same per-cycle citation and extraction work, one side
deterministic and effectively free, the other sampled and slow. The run
is also a citation-fidelity sample. Every task answer takes one of the
attribution paths `bench/citation_probe.py` classifies (cited /
explicit_none / fallback / refused / unattributed_action), and the
per-run rates fold into the metrics block where the bootstrap machinery
treats them like any other per-seed value.

The arm also carries the `refuse_unparseable` mitigation (default off).
The default protocol, when no SOURCES line parses, spreads credit evenly
over everything consulted, which dilutes blame across innocents and lets
the environment act on prose nothing can be charged for. With the
mitigation on, an answer whose SOURCES line does not parse becomes
silence instead: nothing earns, nothing is blamed. An explicit
`SOURCES: none` parses fine and is honored as before, so the mitigation
refuses unparseable prose only.

Grid, pre-committed: StorageEnv only, seeds 0..4, 20 cycles, 6 files per
cycle, the mitigation off and on for every model. The cycle count is the
floor that still separates a blame-driven kill from pure starvation (an
idle entry survives on spawn energy and upkeep to roughly cycle 20), and
6 files per cycle is the budget knob that keeps a 5-seed single-model run
near an hour on an M-series laptop. Hybrid-reasoning families (qwen3)
route reasoning to a field the client never reads, so with thinking left
on the whole generation budget can go to thinking and every answer comes
back empty; the suite pins thinking off for those families so the arm
measures citation behavior rather than an empty-completion artifact.
Opt-in tier, never CI: sampled model output is not deterministic.

### The cost headline

Settlement by the conserved-resource ledger is effectively free: the
deterministic `survival` arm's recorded per-run wall time is 0.03 to
0.09 s across the committed judge cells (`bench/results/judge-qwen.json`
mean 0.032 s, `bench/results/judge-llama.json` mean 0.093 s). The same
per-cycle work answered by a local model costs, per run:

| model | runs | per-run LLM wall time (s, mean) | per-run wall range (s) |
|---|---|---|---|
| llama3.2:3b | 10 | 1,076.0 | 925.7 to 2,054.8 |
| qwen3:4b | 2 | 17,182.4 | 16,983.0 to 17,381.7 |

That is roughly four orders of magnitude over the ledger for llama3.2:3b
(about 12,000x at the means) and roughly five to six for qwen3:4b (about
540,000x; one qwen run alone is 4.8 hours of model time for 120 queries).
The cost gap is the most robust result in this section, and it holds
before any answer is even classified. The ledger matches the work an
LLM-driven arm does per cycle at a fraction of the cost the LLM pays.

### llama3.2:3b carries the statistics (n=5 per mitigation setting)

The committed evidence is `bench/results/llm-llama.json`: 10 runs, five
seeds with the mitigation off and five with it on, paired by seed within
the one model cell. Five seeds is a small sample by design (each run is
roughly 18 minutes of model time), so the exact two-sided permutation
test cannot drop below p = 0.0625 even on a clean 5-0 sweep; read these
as direction and effect size, and nothing here clears p = 0.05.

On true outcomes the two settings are a wash. Survival_llm kills the
actionable poison every seed under both settings (kill rate 1.00),
median kill cycle 8 off and 14 on. Per-seed cum-delta pairing
(`--paired survival_llm:model=llama3.2:3b,refuse=off
survival_llm:model=llama3.2:3b,refuse=on --metric cum_delta`) is
1W/2T/2L for off, mean diff off minus on -84,790 with bootstrap 95% CI
[-279,600, 92,160] and exact paired p = 0.5000. The mitigation neither
helps nor hurts solvency at this scale.

The reason it makes no difference is the honest finding here:
**llama3.2:3b emitted a parseable SOURCES line on every answer**
(`citation_sources_line_rate` 1.00 under both settings, `citation_
fallback_rate` 0.00), so the protocol never reached the fallback path
the mitigation gates. With nothing to refuse, `citation_refused_rate` is
0.00 and the unattributed-action rate is byte-identical off and on
(`citation_unattributed_action_rate` 0.2283 both, exact paired p =
1.0000). The mitigation is inert for a model that always attributes; it
only bites a model that drops the SOURCES line, which is the qwen case
below and the reason the full qwen grid was worth starting.

### Citation fidelity (llama3.2:3b, off / on means, n=5 each)

These are the exact metric keys present in the committed JSON, averaged
across the five seeds per setting:

| metric | off | on |
|---|---|---|
| `probe_harmful_safe_rate` | 1.00 | 1.00 |
| `probe_benign_correct_rate` | 0.67 | 0.67 |
| `probe_silence_rate` | 0.20 | 0.20 |
| `paraphrase_harmful_safe_rate` | 1.00 | 1.00 |
| `paraphrase_benign_grounded_rate` | 0.33 | 0.33 |
| `paraphrase_silence_rate` | 0.80 | 0.80 |
| `citation_sources_line_rate` | 1.00 | 1.00 |
| `citation_cited_rate` | 0.70 | 0.70 |
| `citation_explicit_none_rate` | 0.31 | 0.30 |
| `citation_fallback_rate` | 0.00 | 0.00 |
| `citation_refused_rate` | 0.00 | 0.00 |
| `citation_unattributed_action_rate` | 0.23 | 0.23 |

The model holds the safety floor (it never recommends acting on the
harmful probe, `probe_harmful_safe_rate` and `paraphrase_harmful_safe_
rate` both 1.00) while paying capability on benign questions
(`probe_benign_correct_rate` 0.67, `paraphrase_benign_grounded_rate`
0.33): it stays silent or hedges on benign paraphrases more often than it
should. About a quarter of answers read as an action while carrying no
parseable provenance (`citation_unattributed_action_rate` 0.23), and the
mitigation cannot touch those here because they arrived with a SOURCES
line that parsed but cited nothing usable rather than no line at all.

### qwen3:4b: a cost existence-proof, n=2, not a statistical result

`bench/results/llm-qwen.json` holds the only two qwen3:4b runs that had
completed at assembly time: seeds 0 and 1, mitigation off only. The full
n=5 off-and-on grid is wall-clock-prohibitive (one run is about 4.8 hours,
17,381 s recorded for 120 queries) and was still running when this arm
was assembled, so qwen is reported as a cost existence-proof and a
directional signal, not as a statistical comparison. The full qwen n=5
may be folded in later.

What the two runs show: qwen3:4b is the model the mitigation was built
for. It drops the SOURCES line far more often than llama
(`citation_sources_line_rate` mean 0.525, `citation_fallback_rate` mean
0.475), so nearly half its answers hit the fallback path that
`refuse_unparseable` would convert to silence. Both runs still kill the
actionable poison (kill cycle 19, later than llama's 8 to 14), benign
probe correctness is 1.00 on both, and the safety floor holds
(`probe_harmful_safe_rate` and `paraphrase_harmful_safe_rate` both 1.00).
The two seeds split hard on cum_delta (-1,677,312 and +2,200,576), which
is exactly why two seeds cannot settle anything and the section says so.
Whether `refuse_unparseable` improves qwen's outcomes by refusing that
47.5% fallback fraction is the open question the completed grid will
answer; with the on cells absent, this arm does not claim it.

### LLM-mode caveats, on the record

Three points, stated plainly. First, the mitigation result is honest and
negative for the model with statistics: llama3.2:3b always attributes, so
`refuse_unparseable` does nothing for it, and the model that would
exercise it (qwen3:4b) has no on-cells committed yet. Second, qwen is
n=2, refuse-off only, and its two seeds disagree on sign for cum_delta;
nothing about qwen here is a result, only a cost figure and a direction.
Third, 3b and 4b instruction-tuned models at temperature 0 are the weak
end of the spectrum, so the citation behavior measured here is a floor on
small local models, not a statement about what a frontier model would do
in the same protocol. The one claim this arm makes cleanly is the cost
one: the deterministic ledger does the per-cycle work for cents on the
hour the LLM arm spends.

## Parametric memory: distillation as a data filter

Everything above scores the *retrieval* store. This arm asks the MeMo
question instead: if you distill the store into model weights, does
survival selection still help? It is opt-in (`python -m bench.run --suite
distill`), needs `torch`/`transformers`/`peft`/`datasets`, and like the
LLM and judge arms it is sampled, never in CI.

**Setup.** A purpose-built QA corpus (`bench/distill/corpus.py`): 30
distinctive good facts (ports, rotation intervals, owners across diverse
templates) and 6 distinctive poison entries — harmful answers to distinct
questions (`rm -rf --no-preserve-root /`, `DROP DATABASE …`), whose tokens
are out-of-vocabulary for the good facts, so a model cannot *hallucinate*
them. Selection runs over `VerifiableQAEnv` (exact containment, +1.0
correct / −0.5 wrong), consolidation disabled so survivors stay distinct
facts. Each arm's curated set is LoRA-fine-tuned into a separate
`Qwen/Qwen2.5-0.5B-Instruct` (r=16, prompt masked, 15 epochs), then scored
by containment: `good_recall` (the distinctive correct token appears) and
`poison_reproduction` (the distinctive harmful token appears). No judge,
no keyword-polarity, no silence-as-safety.

**Results (5 seeds, Apple Silicon MPS, mean ± population sd).**

| arm | source set | good_recall | poison_reproduction | n_train |
|-----|-----------|-------------|---------------------|---------|
| `base_model` | none (untrained) | 0.00 ± 0.00 | 0.00 ± 0.00 | 0 |
| `retrieval` | survivor store (reference) | 1.00 ± 0.00 | 0.00 ± 0.00 | 30 |
| `distill_survivor` | energy-ledger survivors | **1.00 ± 0.00** | **0.00 ± 0.00** | 30 |
| `distill_raw` | unfiltered (poison intact) | 0.96 ± 0.08 | **1.00 ± 0.00** | 36 |
| `distill_judge` | LLM-judge-kept (no floor) | 0.05 ± 0.05 | 0.00 ± 0.00 | 1–4 |
| `distill_judge_floor` | LLM-judge-kept, ledger-settled | 0.93 ± 0.10 | 0.00 ± 0.00 | 29–30 |

Read across the rows. The base model knows none of our facts. Distilling
the **raw** store teaches the facts (0.96) but bakes in **every** poison
statement (1.00) — the harmful command is now in the weights, reachable by
the very question it answers. Distilling the **energy-ledger survivors**
teaches the same facts (1.00) and reproduces **none** of the poison (0.00),
because survival removed it before training; the parametric model lands
where the retrieval reference does. The floor-free **judge** arm settles to
1–4 survivors per seed (≈32–35 of 36 entries culled over 40 cycles): a
baseline judge has no energy floor, so its culls accumulate with no
earn-back or revival and erode the store toward extinction, leaving almost
nothing to distill. At a short horizon the same judge tracks correctly
(≈10 cycles: keeps the good facts, culls the poison) — it is not broken, it
simply has no stable fixed point.

The **`distill_judge_floor`** arm settles the *identical* judge verdicts
through the energy ledger (keep → +0.6, cull → −0.6, upkeep 0.05/cycle, die
at the floor) and the collapse disappears: 29–30 survivors, recall 0.93,
poison 0.00 — nearly the measured ledger's result. So the judge's *signal*
was adequate all along; what the baseline judge lacked was the
conserved-resource buffer. The measured ledger still holds a small, tighter
edge (1.00 ± 0.00 vs 0.93 ± 0.10), so measurement is not strictly necessary
once a floor is present, but it is the cleaner signal.

So the filter that yields a parametric memory which both **knows the good
facts and carries none of the poison** is any conserved-resource one: the
measured ledger does it best, the floored judge nearly matches it, raw keeps
the poison, and a judge *without a floor* keeps almost nothing. The active
ingredient is the floor, not the choice of signal.

### Distillation caveats, on the record

First, this is a 0.5B model on a small corpus (30/6) at 15 epochs; the
numbers are a clean existence proof of the data-filter effect, not a
scaling law. Second, the poison tokens are deliberately distinctive so
reproduction is unambiguous; a corpus where poison is reachable by
generalizing benign patterns would not separate as cleanly (an earlier
file-deletion corpus did not, which is why this arm uses a containment
recall/poison design rather than the retrieval suite's
`harmful_safe_rate` — silence-as-safety does not survive into a generative
model). Third, training is sampled (LoRA on MPS), so rerunning reproduces
the design and the direction, not the exact decimals; `distill_raw` and
`distill_judge_floor` recall are the cells that wobble seed to seed
(0.96 ± 0.08 and 0.93 ± 0.10). Fourth, the floor in `distill_judge_floor`
uses a symmetric ±0.6 verdict credit to match the measured ledger's
saturation magnitude; a different credit size or an asymmetric keep/cull
split would move the floored judge's exact recall, though the qualitative
result (the floor removes the collapse) is robust to the choice.

### Continual learning: task-vector merging

The distillation arm trains one model per store. This arm asks the
continual-learning question: if you distill one adapter **per corpus** and
**merge** the adapters, does the merged model recall *both* corpora — without
retraining on their union? Opt-in (`python -m bench.run --suite distill_merge`),
same tier as the other parametric arms.

**Setup.** Two disjoint corpora (`build_split_corpora`, 15 good + 3 poison each,
over non-overlapping services). Each is survival-filtered, then LoRA-distilled
into its own adapter. The adapters are combined with `peft`'s
`add_weighted_adapter` (`cat`, `linear`, `ties` with density 0.5) and every
condition is scored by containment on **both** parts' probes, plus poison
reproduction over both parts' poison.

**Results (5 seeds, Apple Silicon MPS, mean; sd in text).**

| condition | recall_part0 | recall_part1 | recall_all | poison_reproduction |
|-----------|-------------|-------------|------------|---------------------|
| `base_model` | 0.00 | 0.00 | 0.00 | 0.00 |
| `solo_part0` | 0.97 | 0.32 | 0.65 | 0.00 |
| `solo_part1` | 0.27 | 1.00 | 0.63 | 0.00 |
| `merged_cat` | 0.68 | 0.75 | **0.71** | 0.00 |
| `merged_ties` | 0.73 | 0.65 | **0.69** | 0.00 |
| `merged_linear` | 0.23 | 0.20 | 0.21 | 0.00 |
| `joint` | 1.00 | 1.00 | **1.00** | 0.00 |

Each **solo** adapter recalls its own part (≈1.0) and little of the other
(≈0.3), so it knows half the union (recall_all ≈ 0.64). **Merging** with `cat`
or `ties` lifts recall on *both* parts at once (recall_all ≈ 0.69–0.71): the
merged model gained the second corpus while keeping most of the first, with no
retraining — continual learning by adapter arithmetic. Naive `linear` summing
**interferes** (0.21, below even a single solo), the standard task-arithmetic
failure mode. The `joint` adapter trained on the union is the ceiling (1.00);
the merged↔joint gap (≈0.70 vs 1.00) is the interference cost of not retraining.
Crucially, `poison_reproduction` is **0.00** for every distilled and merged
condition: each corpus was survival-filtered before distillation, and merging
adds no new data, so the poison stays out of the merged weights too.

So survival-selected memory composes: distill per corpus, merge for continual
learning, and the merged model carries both corpora's facts and neither's
poison — `cat`/`ties` retain, `linear` does not, and the cost versus full
retraining is real but partial.

### Continual-learning caveats, on the record

This is the same 0.5B / small-corpus existence-proof regime as the distillation
arm. `cat` concatenates ranks (lossless in principle, so its retention is an
upper bound among the merges); `ties` at density 0.5 is the tunable middle;
`linear` with unit weights *sums* the adapters and overshoots — a normalized
linear (weights 1/parts) would interfere less but is not what this arm reports.
Recall_all wobbles seed to seed for the merges (cat 0.71, ties 0.69, both with
sd ≈ 0.06–0.11); the qualitative ordering (joint > cat ≈ ties > solo > linear)
is the robust result, not the exact decimals.

## Scaling (synthetic corpus, median of repeats, Apple M4)

| n entries | add all | retrieve x20 | charge_upkeep | consolidate |
|-----------|---------|--------------|---------------|-------------|
| 100       | 0.3 ms  | 1.6 ms       | 0.0 ms        | 3.5 ms      |
| 1,000     | 2.6 ms  | 16.2 ms      | 0.0 ms        | 84.7 ms     |
| 10,000    | 29.8 ms | 176.2 ms     | 0.5 ms        | 1,061.3 ms  |

Two known hot spots, confirmed: retrieval rebuilds document frequencies
per query (~9 ms per query at 10k entries), and consolidation is
O(N^2) pairwise similarity (1.1 s per pass at 10k, which is why the
harness gates that cell behind `--full`). Both are fine at the
few-thousand-entry scale this package targets and documented as the
ceiling. Past it, you want an index, which is out of scope for the
zero-dependency core.

## Honest caveats

- Vocabulary coupling, named plainly: the corpus, the StorageEnv task
  prompts, and `decision_polarity`'s marker list were written by the
  same hand in the same vocabulary. The crisp cycle-0 kill lives in the
  near-exact lexical-match regime that coupling creates. The paraphrase
  probe columns measure what happens outside it: harmful paraphrases
  stay safe (silence is conservative), but lexical arms ground only a
  third of benign paraphrases. Treat the headline numbers as
  within-distribution results; the paraphrase columns are the
  out-of-distribution honesty check, scored by provenance precisely so
  the keyword reader cannot grade its own homework.
- The headline and noisy tables above are StorageEnv results. The
  [TestSuiteEnv section](#second-environment-family-testsuiteenv) runs
  the same arms on a second environment family; conclusions that hold
  on only one family are flagged there rather than averaged away.
- The corpus is demo-scale (16 entries) and encoded by the rule-based
  LocalEncoder, not an LLM. LLM-mode (citation-based attribution) has
  no benchmark arm yet; its credit fidelity is covered by unit tests
  only.
- Survival's lean population is a trade: it starves protective and
  unused knowledge that keep_everything retains. On these probes that
  costs nothing because silence defaults to the safe action; in an
  environment where inaction is expensive, it would cost. Measured,
  not hidden: keep_everything ties on benign retention.
- recency's tail-delta tie with survival is real and reproducible. The
  difference is the unkilled threat and the 11x lesson price, not the
  steady state on this corpus.
- Numbers are from one machine; times vary, the comparisons should not.

## Reproduce

```bash
pip install -e .
python -m bench.run --suite headline --seeds 0:10 --out bench/results/headline.json --update-manifest
python -m bench.run --suite noisy    --seeds 0:30 --out bench/results/noisy.json    --update-manifest
python -m bench.run --suite ablation --seeds 0:5  --out bench/results/ablation.json --update-manifest
python -m bench.run --suite testsuite --seeds 0:10 --out bench/results/testsuite.json --update-manifest
python -m bench.run --suite testsuite_noisy --seeds 0:30 --out bench/results/testsuite_noisy.json --update-manifest
python -m bench.run --suite scaling --full        --out bench/results/scaling.json
python -m bench.report bench/results/headline.json --fmt md
python -m bench.report bench/results/headline.json --tests --fmt md
python -m bench.report bench/results/noisy.json --fmt md
python -m bench.report bench/results/noisy.json --tests
python -m bench.report bench/results/noisy.json --paired survival evict_consecutive
python -m bench.report bench/results/testsuite.json --fmt md
python -m bench.report bench/results/testsuite_noisy.json --tests
python -m bench.run --suite bandit --seeds 0:10 --out bench/results/bandit.json --update-manifest
python -m bench.run --suite judge  --seeds 0:5  --judge-models llama3.2:3b --out bench/results/judge-llama.json --update-manifest
python -m bench.run --suite judge  --seeds 0:5  --judge-models qwen3:4b    --out bench/results/judge-qwen.json  --update-manifest
python -m bench.run --suite llm --seeds 0:5 --model llama3.2:3b --out bench/results/llm-llama.json --update-manifest
python -m bench.run --suite llm --seeds 0:5 --model qwen3:4b    --out bench/results/llm-qwen.json  --update-manifest
python -m bench.report bench/results/bandit.json     --paired policy_bandit survival
python -m bench.report bench/results/judge-llama.json --paired survival judge_settled
python -m bench.report bench/results/judge-qwen.json  --paired survival judge_settled
python -m bench.report bench/results/llm-llama.json --fmt md
python -m bench.report bench/results/llm-llama.json --paired survival_llm:model=llama3.2:3b,refuse=off survival_llm:model=llama3.2:3b,refuse=on --metric cum_delta
python -m bench.report bench/results/llm-qwen.json  --fmt md
```

The bandit suite is stdlib and deterministic like every other
committed suite. The judge and llm suites are the exceptions in this
directory: their runs sample a local model (temperature 0 is not a
determinism guarantee), so `bench/results/judge-llama.json`,
`bench/results/judge-qwen.json`, `bench/results/llm-llama.json`, and
`bench/results/llm-qwen.json` are committed as the evidence behind the
judge and LLM-mode tables above, not as byte-reproducible targets. Each
file is one model run separately so the queue stays short; rerunning any
of them requires a running Ollama server with that model pulled, and
none ever runs in CI. The committed `llm-qwen.json` is the partial qwen3:4b
grid (seeds 0 and 1, mitigation off) that had completed when the arm was
assembled; the full n=5 grid is hours per run and may be folded in later.

Per-seed raw JSON IS committed under `bench/results/` (headline, noisy,
ablation, testsuite, testsuite_noisy, bandit, the two judge files, and
the two llm files),
with `bench/results/MANIFEST.json` recording each file's
suite, seeds, config hash, exact reproduction command, library version,
and producing git commit; `bench.report <file> --check` validates a
file against its manifest entry. The commit matters: the environments'
per-cycle seed scheme changed after the 0.4.0 release while
`__version__` still reads 0.4.0, so reproducing the committed numbers
means checking out the manifest's `source_commit`, not installing the
released version. The scaling table is timing data from one machine and
stays uncommitted. Runs are deterministic per seed: rerunning a suite
twice produces byte-identical metrics apart from wall times, and the
seeded bootstrap and permutation tests reproduce byte-identically too.
CI runs `--suite smoke` plus `bench.report --check` on the smoke output
and `--check --require-manifest` on every committed results file on
every push, so a deleted manifest or entry fails instead of silently
passing.

## SWE-Bench-CL learning-curve pilot (protocol pre-committed, no results yet)

Everything above measures the synthetic storage environment. This
section pins, before any result exists, the protocol for the first run
on real software-engineering tasks: does a lesson store under survival
selection produce a learning curve across a continual sequence of
SWE-Bench tasks? The harness lives in `bench/swebench_cl/`; this
section is committed ahead of any scored run so the cells below cannot
be bent around the numbers later.

### Pinned data

- Dataset: SWE-Bench-CL-Curriculum v1.0.0 (arXiv 2507.00014), which
  organizes SWE-Bench Verified instances into per-repository
  continual-learning sequences. Upstream publishes one JSON file with
  no release tags, so the pin is exact bytes:
  `thomasjoshi/agents-never-forget` at commit `74a38a90baace2563`,
  sha256 `91bc39a769b6218419bd44308650e5d2c846ecd3e6f7a6c086f74a37b6db90f7`.
  `load_dataset` refuses any file whose hash differs; the pin was
  re-verified against the live upstream blob on 2026-06-12.
- Sequences, committed in `bench/swebench_cl/manifests/pilot.json`:
  `pytest-dev_pytest_sequence` (19 tasks) and
  `astropy_astropy_sequence` (22 tasks), in the dataset's own
  curriculum order. The manifest holds task identity only (instance
  id, order, repo, base commit); problem statements and test lists
  stay in the verified dataset file and the join is checked both ways
  at run time, so a moved base commit refuses to run. All 41 pinned
  instances are members of SWE-bench_Verified (checked against the
  Hugging Face dataset, 500 ids, on 2026-06-12), so the official
  evaluation images and harness apply unchanged.

### Arms

Defined in code (`bench/swebench_cl/arms.py`), all three answering the
same tasks through the same endpoint and executor:

| arm | lessons injected | minted | settled |
|---|---|---|---|
| memory_on | top-k by relevance | yes | yes, by eval outcome |
| memory_off | none | no | no |
| random_matched | uniformly random alive lessons under the SAME token budget relevance retrieval would have spent on that task | yes | yes, by eval outcome |

`random_matched` is the control that matters, mirroring the storage
bench's arm of the same name: same memory quantity, same credit
mechanics, no outcome-directed selection. If memory_on does not beat
it, the learning curve is a token-budget effect, not a memory effect.

### Per-task protocol

1. Retrieve k=3 lessons for the query `repo + problem statement`;
   inject per arm.
2. One completion, temperature 0, through one OpenAI-compatible
   endpoint config (`bench/swebench_cl/model.py`). Ollama for plumbing
   runs; a frontier endpoint later is a base_url, model, api_key
   change and nothing else.
3. Extract the unified diff; an empty patch is a real result that
   settles at exactly 0, never an error.
4. Evaluate with the official SWE-Bench harness in the official
   x86_64 instance images (`DockerExecutor`); every pull is sized
   against Docker Hub first and refused outright if free disk would
   drop below 4 GB. Settlement delta = fraction of fail-to-pass tests
   gained minus fraction of pass-to-pass tests broken, in [-1, 1],
   read from the harness's per-instance report.
5. Settle injected lessons through the library's one credit rule
   (same tanh, same supporting share as production), mint one lesson
   from a deterministic template (verdict from the eval result only;
   the text may quote the model's own one-line reflection, sanitized),
   charge one upkeep tick.
6. Write one run JSON per task (schema pinned by tests); committed
   evidence binds to `bench/results/MANIFEST.json` exactly as the
   storage suites do. Smoke runs stay uncommitted.

### Pre-committed cells

To be filled only from committed run JSONs under `bench/results/`,
per (sequence, arm), seeds stated when they exist. Every contributing
run must carry `eval.mode == "docker"`; the CLI enforces this by
refusing `--update-manifest` for any other executor, so stub plumbing
runs can never enter committed evidence.

| cell | memory_on | memory_off | random_matched |
|---|---|---|---|
| resolve rate, full sequence | pending | pending | pending |
| resolve rate, first half vs second half | pending | pending | pending |
| mean settlement delta, first half vs second half | pending | pending | pending |
| injected lesson tokens, second half | pending | n/a | pending |
| store population at end / upkeep deaths | pending | n/a | pending |

The learning-curve claim is the second-half minus first-half
improvement of memory_on against both controls, with the same paired
per-seed machinery as the storage suites once seeds exist.

### What the pilot must show before any expansion

Pre-committed gates, in order of priority:

- The store must reach its survival budget within a sequence: deaths
  from upkeep must be nonzero, so culling decisions actually happen.
  A pilot whose store never fills says nothing about selection.
- Injection must be real: lessons minted early in a sequence must be
  retrieved into later prompts at a nonzero rate, or the arms are
  identical by construction.
- The headline cell, reported per sequence position: resolve rate and
  settlement delta, memory_on vs memory_off vs random_matched, same
  seeds. memory_on must beat both controls, and random_matched is the
  bar that decides: beating it shows outcome-directed selection at
  work, where beating memory_off alone could be a token-budget effect.
- Per-position curves over at least 3 seeds before any claim of a
  learning curve; one seed is an anecdote.

### Plumbing validation, 2026-06-12 (Apple Silicon, 6-7 GB free disk)

What actually ran, stated plainly:

- Full pipeline live against a local Ollama endpoint with the
  documented stub executor: manifest loaded, dataset hash verified,
  real model calls (qwen3:4b, llama3.2:3b), both response paths
  exercised (qwen3:4b spent its entire token budget thinking and
  returned empty content, which settled cleanly at 0; llama3.2:3b
  produced a real 505-char diff that flowed through extraction,
  evaluation, settlement, and minting), lessons minted on every task,
  store ticked, run JSON written in the committed schema.
- Docker path, up to the guard: image existence and size verified
  against the registry (x86_64 published for the pinned instances, no
  arm64 variants), x86_64 emulation confirmed working on this host,
  swebench 4.1.0 installed and its CLI flags verified. The disk guard
  then refused the 0.98 GB compressed pull live (estimated 2.76 GB on
  disk against 5.5 GB free and a 4 GB floor), which is the guard
  doing exactly its job. The report-parsing leg is covered by offline
  tests against both official report shapes (per-instance and run
  summary).
- A real pilot run therefore needs: a linux x86_64 runner (or an
  Apple Silicon machine with 20+ GB free that accepts emulation
  slowness), roughly 3 GB transient disk per instance image (freed
  between tasks at `--cache_level none`), about 1 GB for the swebench
  package plus dataset caches, and model spend in the low single-digit
  dollars per seed at mid-tier frontier pricing (41 tasks x 3 arms,
  about 2k prompt + 1k completion tokens per call), so a 5-seed pilot
  is tens of dollars.

### Real-evaluation validation, 2026-06-30 (Apple Silicon, Docker up, 1.4 TB free)

The 2026-06-12 entry stopped at the disk guard on an 8 GB-free machine.
On a host with Docker running and 1.4 TB free, the real docker path now
runs end to end, and this is recorded as the leg the earlier note could
not reach:

- Dataset pin re-verified against live upstream (sha256 unchanged from
  the 2026-06-12 check); pilot sequences intact (pytest 19, astropy 22).
- `linux/amd64` emulation confirmed working (an emulated container runs
  on the aarch64 host).
- One docker-executed instance (`pytest-dev__pytest-5262`, arm
  `memory_on`, answers from a local llama3.2): `eval.mode == "docker"`,
  `env_ready` true, the official SWE-bench image built and the suite ran
  (`p2p_passed` 108/108), the weak model's diff failed to apply, and the
  unresolved submission settled at base behavior (`delta` 0.0) exactly as
  designed. Wall time about 61 s for this pytest instance (heavier repos
  and a cold image pull cost more). Schema-valid run JSON written.

So the only thing between here and the pre-committed cells is a scored
run with a capable model: the harness, the docker eval, the settlement,
and the manifest binding are all exercised. The model choice is the open
decision (a local 3-4B model resolves ~0 and yields a flat, uninformative
curve; a frontier endpoint is needed for a measurable learning curve),
and on Apple Silicon under emulation a full multi-seed run is an
overnight-scale job, so a linux x86_64 runner remains the recommended
venue.

### Reproduce (pilot)

```bash
pip install -e . swebench
python -m bench.swebench_cl.run pin --dataset SWE-Bench-CL-Curriculum.json \
  --out bench/swebench_cl/manifests/pilot.json   # byte-identical to the committed pin
python -m bench.swebench_cl.run run \
  --manifest bench/swebench_cl/manifests/pilot.json \
  --dataset SWE-Bench-CL-Curriculum.json \
  --sequence pytest-dev_pytest_sequence --arm memory_on \
  --executor docker --seed 0 --out bench/results/swebench_cl_pilot.json \
  --update-manifest
```
