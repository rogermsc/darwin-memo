# Benchmarks

Every number below was produced by the commands in [Reproduce](#reproduce),
on the machine stated there, with fixed seeds. The harness lives in
`bench/` and is stdlib-only. If you rerun and get different conclusions,
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
entries) rather than flattering them; survival_writes' grounded score
of 0.00 below is that penalty landing on its untrusted experience
entries.

## Headline: three survival arms vs five baselines (10 seeds)

| arm                | kill rate | kill cycle (med) | damage before kill    | tail delta        | cum delta             | final pop | harmful safe | benign correct | para safe | para grounded |
|--------------------|-----------|------------------|-----------------------|-------------------|-----------------------|-----------|--------------|----------------|-----------|---------------|
| survival           | 1.00      | 0                | -751,104 ±519,398     | 434,688 ±70,221   | 11,996,570 ±447,162   | 4.0       | 1.00         | 1.00           | 1.00      | 0.33          |
| survival_writes    | 1.00      | 0                | -751,104 ±519,398     | 434,688 ±70,221   | 11,996,570 ±447,162   | 4.0       | 1.00         | 1.00           | 1.00      | 0.00          |
| survival_embedding | 1.00      | 19 (starved)     | 0                     | 434,688 ±70,221   | 13,178,061 ±130,173   | 4.0       | 1.00         | 1.00           | 1.00      | 0.67          |
| evict_on_negative  | 1.00      | 0                | -547,328 ±584,640     | 434,688 ±70,221   | 12,341,555 ±629,725   | 15.0      | 1.00         | 1.00           | 1.00      | 0.33          |
| recency (10)       | 0.00      | -                | -3,639,808 ±583,973   | 434,688 ±70,221   | 6,129,357 ±669,226    | 7.0       | 1.00         | 1.00           | 1.00      | 0.33          |
| random_matched     | 0.80      | 19               | -8,970,854 ±3,121,331 | -75,284 ±498,295  | -5,251,891 ±4,704,253 | 6.0       | 0.90 ±0.21   | 0.40 ±0.34     | 1.00      | 0.07          |
| ttl (10)           | 1.00      | 10               | -3,639,808 ±583,973   | 0                 | -2,566,042 ±736,475   | 0.0       | 1.00         | 0.00           | 1.00      | 0.00          |
| keep_everything    | 0.00      | -                | -10,605,773 ±663,147  | -287,478 ±231,963 | -7,291,290 ±829,780   | 16.0      | 0.50         | 1.00           | 1.00      | 0.33          |

What each arm's best metric is, stated plainly:

- **keep_everything** retains all benign knowledge (benign correct 1.00)
  and never loses a useful entry. It also never stops bleeding: the
  poison keeps deciding deletions forever (tail -287k, cum -7.3M).
- **ttl(10)** kills the poison on schedule. It does so by killing
  everything: after cycle 10 memory is empty, benign capability is 0.00,
  and the run still ends 2.6M underwater.
- **recency(10)** is the strongest baseline (cum +6.1M) and its late
  cycles match survival exactly. But its kill rate is 0.00: the poisoned
  advice stays alive indefinitely because being CONSULTED refreshes its
  idle clock even when it no longer wins. It absorbed 4.8x survival's
  damage before the bleeding stopped, and the threat remains in memory
  waiting for a query phrasing it wins.
- **random_matched** is the experiment's point. Identical eviction
  budget to survival, random victims: kill rate drops to 0.80, the
  median kill arrives at cycle 19 instead of 0, damage is 12x worse,
  benign capability falls to 0.40 because useful entries get evicted
  instead, and the runs end 5.3M underwater with huge variance. Pruning
  rate is not the active ingredient. Outcome direction is.
- **survival** kills the actionable poison at median cycle 0 (it decides
  a few deletions, the restore costs land on it, it is dead before
  cycle 1 in most seeds), pays a small lesson price, ends maximally
  lean (4 entries), and is poison-free and capability-complete on
  probes.
- **survival_writes** (experience writes on) is outcome-identical to
  survival: writes reinforce already-winning entries on this corpus.
  Its paraphrase-grounded 0.00 is the strict provenance scoring at
  work: experience entries carry cycle-N sources, which the
  fully-trusted check refuses, and that refusal is reported rather
  than smoothed over.
- **evict_on_negative** is the result this report exists to publish
  honestly: on this deterministic environment, the one-line heuristic
  MATCHES the full energy ledger on outcomes (cum +12.3M vs +12.0M,
  kill at 0, slightly less lesson damage). What the ledger buys on this
  benchmark is exactly two things the if-statement does not do: it
  starves dead weight (final population 4 vs 15, the if-statement
  hoards everything that never erred), and it forgives. One negative
  outcome instantly executes an entry under evict_on_negative; under
  the ledger, an entry that was right ninety-nine times survives one
  disaster. This environment is deterministic, so this table cannot
  show forgiveness; the [noisy suite](#noisy-outcomes-the-forgiveness-test)
  below exercises it directly, against the heuristic's noise-hardened
  variants, and reports where each side breaks. If your measurements
  never lie and you do not need leanness, the if-statement is the
  right tool and this row says so.
- **survival_embedding** runs the same loop over the hashing-embedder
  retriever and posts the best cumulative delta (+13.2M) by a different
  route: cosine ranking happened to place the runbook protector above
  the poison from cycle 0, so the poison never decided anything, caused
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
| credit_gain | 0.15 / 0.3 / 0.6 / 1.2 | The one knob that moves the kill. Median kill cycle 3 / 1 / 1 / 0; damage before kill shrinks from -1.8M to -0.7M as gain rises. Outcomes otherwise identical. |
| min_coverage | 0.15 / 0.25 / 0.4 | A real sweet spot at 0.25 (cum +11.8M, benign 1.00). Too low: weak matches decide tasks they know nothing about (cum +6.5M, benign 0.67, tail variance x10). Too high: useful advice goes silent (cum +5.7M, benign 0.67). |
| upkeep | 0.01 / 0.05 / 0.1 / 0.2 | Outcomes identical. Only the final population moves: 13 / 4 / 3 / 3. Upkeep tunes leanness, not safety. |
| merge_threshold | 0.4 / 0.55 / 0.7 | Outcomes identical, population 5 / 4 / 4. |
| consolidate_every | off / 5 | Outcomes identical, population 3 / 4. Consolidation is hygiene, not safety, at this scale. |
| resource_scale | 25k / 100k / 400k | No measurable effect on noise-free outcomes. (An earlier draft blamed tanh saturation; only 3x restore costs saturate, and the noisy suite's 400k cells show the knob does move outcomes once measurements lie. Cap-clipping, not saturation, is the insensitivity mechanism.) |

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
drift (measured: the same 30 per-seed values, mean -9,502,447, in all
12 cells).

Three noise models: **false_bad** (only positive truths flip — flaky
CI, where good changes report red builds but broken builds do not
report green), **flip** (symmetric — lies can also reward the guilty),
and **magnitude** (sign kept, size lied about by 0.25-4x — the one
model where sign-driven heuristics are immune by construction and only
magnitude-reading credit can degrade).

Because beating a zero-tolerance baseline under noise would prove
nothing, the heuristic family fields its best selves: K lifetime
strikes (K=1,2,3), consecutive strikes that a success wipes clean
(forgiveness as an if-statement, the strongest cheap variant), and
quarantine (evict on blame, re-encode a fresh copy after a 3-cycle
cooldown — the recovery path real deployments have). 30 seeds per
cell, 30 cycles, 12 files per cycle.

### false_bad: the flaky-CI case (mean true cum delta / benign capability)

| arm | 0.00 | 0.05 | 0.10 | 0.20 | 0.35 |
|---|---|---|---|---|---|
| survival | 11.94M / 1.00 | 11.94M / 1.00 | 11.94M / 1.00 | 11.94M / 1.00 | 10.13M / 0.83 |
| evict k=1 | 12.19M / 1.00 | 2.48M / 0.01 | 1.41M / 0.00 | 0.42M / 0.00 | -0.06M / 0.00 |
| evict k=2 | 11.94M / 1.00 | 5.49M / 0.14 | 2.80M / 0.01 | 1.19M / 0.00 | 0.11M / 0.00 |
| evict k=3 | 11.73M / 1.00 | 7.56M / 0.26 | 4.09M / 0.03 | 1.84M / 0.00 | 0.47M / 0.00 |
| consecutive k=2 | 11.94M / 1.00 | 10.56M / 0.82 | 8.02M / 0.50 | 3.45M / 0.04 | 0.73M / 0.00 |
| quarantine m=3 | 4.52M / 1.00 | 2.02M / 0.77 | 0.71M / 0.58 | -0.97M / 0.37 | -2.44M / 0.14 |

The headline cell: at 5-20% false-bad noise, survival's true outcomes
are IDENTICAL to its noise-free run, byte for byte. The lies fire (11,
22, 43 of them on average), drain energy, and change nothing, because
a capped decider holds ~9 lies' worth of buffer and refills it by
earning. Every counter variant collapses instead: k=1 loses nearly all
benign capability by 5%, and the strongest variant (consecutive) holds
at 5% but halves capability by 10%, because a cycle-granularity reset
is coarser than a continuous buffer. Strikes without earn-back are
consumed linearly by noise; patching that with decay, magnitude
grading, and dead-weight expiry is reinventing the energy ledger.

Paired per seed (same worlds) under false_bad, survival vs consecutive
on true cum delta: 13W-17T-0L at 5%, 26W-4T-0L at 10%, 30W-0T-0L at
20% and 35% (median margins +8.2M and +10.6M). Under false_bad,
survival does not lose a single seed to any counter variant at any
rate. Under flip it concedes a few: one seed to consecutive at 5% and
10% (margin -356k), one or two seeds per counter at 35% (worst -6.9M,
to k=1), then most seeds at 50% where everything is underwater anyway.
And k=1 keeps its small deterministic edge over survival (8 of 30
seeds, at most 2.2M) in the rate-0.00 and magnitude cells, exactly as
the first column shows.

### flip: forgiveness's price, and the ledger's own failure boundary

| survival under flip | 0.00 | 0.05 | 0.10 | 0.20 | 0.35 | 0.50 |
|---|---|---|---|---|---|---|
| true cum delta | 11.94M | 11.85M | 11.73M | 11.32M | 7.49M | -3.75M |
| benign capability | 1.00 | 1.00 | 1.00 | 1.00 | 0.83 | 0.18 |
| poison kill cycle (med) / kill rate | 0 / 1.00 | 0 / 1.00 | 1 / 1.00 | 1 / 1.00 | 3 / 0.97 | 5.5 / 0.73 |

Two pre-committed results, reported as promised. First, forgiveness
has a price: tolerance for lying measurements is tolerance for guilty
entries, and the poison's kill cycle climbs from 0 to a median of 5.5
(among the 73% of seeds where it dies at all) as
false-good lies (which report a destroyed database as +3x its size,
tanh-saturated reward) keep rescuing it. Under false_bad, negatives
stay truthful and the kill stays at cycle 0 at every rate. Second, the
ledger's failure boundary: at 35% it degrades visibly, and at 50% — a
sign flip with no information content — it goes underwater (-3.75M)
and loses the paired sign test against consecutive (14W-16L). Past
roughly one lie in three, nothing here curates safely; the counters
are already long dead by then (every arm is negative at 50%).

### magnitude: the model where only the ledger could lose

Sign-preserved size lies (0.25-4x) leave every strike counter at
exactly its rate-0.00 numbers, as they must (they read only the sign).
The honest part: survival is ALSO at exactly its rate-0.00 numbers.
The mechanism is not tanh saturation: at resource_scale 100k only the
3x restore costs are near-saturated (tanh 0.91-1.0), while disposable
deltas land on tanh's working range (0.20-0.84), so size lies DO move
per-event credit. What clips them is the energy cap: healthy deciders
sit at max_energy 5.0, where exaggerated or shrunken rewards change
nothing, and lies never flip a sign, so no death threshold is crossed.
The sensitivity cells re-run rate 0.20 at resource_scale=400k, where
per-event credit is a quarter the size and cap-clipping correspondingly
weaker, anchored by a clean rate-0.00 cell at the same scale (11.69M):
magnitude noise still costs almost nothing (11.78M / 1.00),
false_bad remains per-seed identical to clean (11.69M), and flip costs
a little (10.92M, capability 1.00). Magnitude
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
  quarantine bleeds even at rate 0.00 (4.52M vs survival's 11.94M; its
  kill-cycle column reads first-extinction, not permanence). Recovery
  without selection is rot with extra steps.
- **keep_everything** is the canary, and it also shows what no
  curation costs under any noise: -9.50M everywhere.

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
- StorageEnv derives cycle worlds from `seed + cycle`, so adjacent
  seeds are shifted windows of one another rather than independent
  draws; the paired per-seed comparisons are unaffected (same world,
  both arms), but treat across-seed means and spreads as smoother
  than 30 independent samples would be.
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
  difference is the unkilled threat and the 4.8x lesson price, not the
  steady state on this corpus.
- Numbers are from one machine; times vary, the comparisons should not.

## Reproduce

```bash
pip install -e .
python -m bench.run --suite headline --seeds 0:10 --out bench/results/headline.json
python -m bench.run --suite noisy    --seeds 0:30 --out bench/results/noisy.json
python -m bench.run --suite ablation --seeds 0:5  --out bench/results/ablation.json
python -m bench.run --suite scaling --full        --out bench/results/scaling.json
python -m bench.report bench/results/headline.json --fmt md
python -m bench.report bench/results/noisy.json --fmt md
python -m bench.report bench/results/noisy.json --paired survival evict_consecutive
```

Raw JSON is regenerated, not committed. Runs are deterministic per seed:
rerunning a suite twice produces byte-identical metrics apart from wall
times. CI runs `--suite smoke` plus `bench.report --check` on every
push.
