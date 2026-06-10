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

"Poison killed" means no alive entry from the poisoned source whose
answer reads as a positive action. Inert poisoned entries that advise
nothing can only starve and are excluded from the kill metric.

## Setup

- Machine: Apple M4, macOS, Python 3.14.3, darwin-memo 0.1.0
- Store: the exact headline-demo store (examples corpus, LocalEncoder,
  16 entries of which 3 derive from the poisoned forum post)
- Environment: `StorageEnv`, 30 cycles, 12 files per cycle, seeds 0..9
- Arms differ only in end-of-cycle eviction. Baselines track usage but
  never touch energy. `random_matched` evicts the same per-cycle death
  COUNTS as the survival arm on the same seed, victims chosen uniformly
  at random: same pruning rate, no outcome direction.

## Headline: survival vs four baselines (10 seeds)

| arm             | kill rate | kill cycle (med) | damage before kill    | tail delta        | cum delta             | final pop | harmful safe | benign correct |
|-----------------|-----------|------------------|-----------------------|-------------------|-----------------------|-----------|--------------|----------------|
| survival        | 1.00      | 0                | -751,104 ±519,398     | 434,688 ±70,221   | 11,996,570 ±447,162   | 4.0       | 1.00         | 1.00           |
| survival_writes | 1.00      | 0                | -751,104 ±519,398     | 434,688 ±70,221   | 11,996,570 ±447,162   | 4.0       | 1.00         | 1.00           |
| recency (10)    | 0.00      | -                | -3,639,808 ±583,973   | 434,688 ±70,221   | 6,129,357 ±669,226    | 7.0       | 1.00         | 1.00           |
| random_matched  | 0.80      | 19               | -8,970,854 ±3,121,331 | -75,284 ±498,295  | -5,251,891 ±4,704,253 | 6.0       | 0.90 ±0.21   | 0.40 ±0.34     |
| ttl (10)        | 1.00      | 10               | -3,639,808 ±583,973   | 0                 | -2,566,042 ±736,475   | 0.0       | 1.00         | 0.00           |
| keep_everything | 0.00      | -                | -10,605,773 ±663,147  | -287,478 ±231,963 | -7,291,290 ±829,780   | 16.0      | 0.50         | 1.00           |

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
  cycle 1 in most seeds), pays the smallest lesson price, and is the
  only arm that is simultaneously poison-free, capability-complete on
  probes, and maximally delta-positive.
- **survival_writes** (experience writes on) is metric-identical here:
  writes reinforce already-winning entries on this corpus. The arm
  exists to show the writes at least do no harm.

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
| resource_scale | 25k / 100k / 400k | No measurable effect: per-file deltas saturate tanh at all three scales. |

## Scaling (synthetic corpus, median of repeats, Apple M4)

| n entries | add all | retrieve x20 | charge_upkeep | consolidate |
|-----------|---------|--------------|---------------|-------------|
| 100       | 0.3 ms  | 1.7 ms       | 0.0 ms        | 3.7 ms      |
| 1,000     | 2.6 ms  | 17.0 ms      | 0.0 ms        | 92.7 ms     |
| 10,000    | 29.9 ms | 183.2 ms     | 0.5 ms        | 1,121.7 ms  |

Two known hot spots, confirmed: retrieval rebuilds document frequencies
per query (~9 ms per query at 10k entries), and consolidation is
O(N^2) pairwise similarity (1.1 s per pass at 10k, which is why the
harness gates that cell behind `--full`). Both are fine at the
few-thousand-entry scale this package targets and documented as the
ceiling. Past it, you want an index, which is out of scope for the
zero-dependency core.

## Honest caveats

- One environment family. Every arm above runs on `StorageEnv`. The
  TestSuiteEnv poison-extinction result is covered by tests, not yet by
  this multi-arm harness.
- The corpus is demo-scale (16 entries) and encoded by the rule-based
  LocalEncoder, not an LLM.
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
python -m bench.run --suite ablation --seeds 0:5  --out bench/results/ablation.json
python -m bench.run --suite scaling --full        --out bench/results/scaling.json
python -m bench.report bench/results/headline.json --fmt md
```

Raw JSON is regenerated, not committed. Runs are deterministic per seed:
rerunning a suite twice produces byte-identical metrics apart from wall
times. CI runs `--suite smoke` plus `bench.report --check` on every
push.
