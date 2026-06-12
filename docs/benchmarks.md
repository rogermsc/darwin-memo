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
- One environment family. Every arm above runs on `StorageEnv`. The
  TestSuiteEnv poison-extinction result is covered by tests, not yet by
  this multi-arm harness.
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
python -m bench.run --suite scaling --full        --out bench/results/scaling.json
python -m bench.report bench/results/headline.json --fmt md
python -m bench.report bench/results/headline.json --tests --fmt md
python -m bench.report bench/results/noisy.json --fmt md
python -m bench.report bench/results/noisy.json --tests
python -m bench.report bench/results/noisy.json --paired survival evict_consecutive
```

Per-seed raw JSON IS committed under `bench/results/` (headline, noisy,
ablation), with `bench/results/MANIFEST.json` recording each file's
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
