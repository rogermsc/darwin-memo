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
```

Per-seed raw JSON IS committed under `bench/results/` (headline, noisy,
ablation, testsuite, testsuite_noisy), with `bench/results/MANIFEST.json` recording each file's
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
