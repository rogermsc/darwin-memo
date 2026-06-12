# Tuning guide

Every knob below is a real constructor argument or config field, and
every numeric claim is either a code default or a committed benchmark
result with its section named. Where no committed evidence supports a
recommendation, this page says so instead of inventing one.

## The mechanics the knobs plug into

One credit rule serves the whole package
(`darwin_memo.survival.assign_credit`):

```
credit = credit_gain * tanh(delta / resource_scale)
```

The deciding entry receives the full credit, each supporting entry
receives `credit * supporting_share`; when no single entry decided,
the credit splits evenly across the supporting entries. Energy is
capped at `max_energy`. Every alive entry pays `upkeep` per cycle (or
per Ledger tick), and an entry at zero energy is buried, unless a
pending ticket escrows it. Entries spawn at energy 1.0 (a
`MemoryEntry` field default, not a constructor knob).

Two derived quantities drive most tuning intuition:

- **Starvation horizon**: a never-earning entry survives
  `spawn_energy / upkeep` cycles. At defaults that is 1.0 / 0.05 = 20.
- **Disaster buffer**: a full-credit negative event drains at most
  `credit_gain` (tanh is bounded), so an entry at the `max_energy` cap
  absorbs roughly `max_energy / credit_gain` worst-case lies or
  disasters, about 8 at defaults, before dying. The noisy benchmark
  suite measures this buffer directly
  ([benchmarks: noisy outcomes](benchmarks.md#noisy-outcomes-the-forgiveness-test)).

## The load-bearing knobs

### `upkeep` (`MemoryStore`, default 0.05)

Mechanically: subtracted from every alive entry once per cycle or
tick. The only steady drain in the system.

- **Too low**: dead weight accumulates. Entries that never earn hang
  around far past usefulness, and population-proportional costs
  (retrieval ranking, consolidation) grow with them.
- **Too high**: the starvation horizon shrinks. Knowledge that earns
  rarely but matters (a lesson consulted every 30 ticks) dies before
  its next chance to earn.

Evidence: the ablation sweep 0.01 / 0.05 / 0.1 / 0.2 left every
outcome metric identical and moved only the final population
(13 / 4 / 3 / 3). Upkeep tunes leanness, not safety
([benchmarks: ablations](benchmarks.md#ablations-survival-arm-5-seeds-one-knob-at-a-time)).
Pick it from your tick cadence: decide how many ticks an unproven
entry deserves, then set `upkeep = 1.0 / that`.

### `resource_scale` (environment attribute, `Ledger` argument, `SurvivalConfig` field, default 1.0 on the Ledger and CLI)

Mechanically: the tanh normalizer. A settled delta equal to
`resource_scale` earns `credit_gain * tanh(1.0)`, about 76% of the
maximum credit. Deltas far above it saturate; deltas far below it
earn proportionally.

- **Too low**: every outcome saturates. A one-test improvement and a
  fifty-test improvement earn the same credit, so magnitude
  information is discarded.
- **Too high**: per-event credit shrinks toward zero. Earning cannot
  keep up with upkeep and the population starves even when outcomes
  are good; selection also slows, which delays killing poison.

Evidence: the ablation 25k / 100k / 400k on StorageEnv (whose deltas
are bytes around the 100k mark) found 25k and 100k identical, while
400k, where per-event credit is a quarter the size, delayed the
poison kill by one cycle
([benchmarks: ablations](benchmarks.md#ablations-survival-arm-5-seeds-one-knob-at-a-time)).
The working rule: set `resource_scale` near the magnitude of one
meaningful outcome in your unit. For CI lesson stores this repo uses
2.0 (tests, matching `TestSuiteEnv.resource_scale`); that number is
the committed convention from this repo's own deployment, not a
benchmark sweep.

### `credit_gain` (`SurvivalConfig`, default 0.6)

Mechanically: the cap on per-event credit, positive or negative.

- **Too low**: selection weakens in both directions. Poison survives
  longer and does more damage before dying; honest entries earn
  slowly.
- **Too high**: single events dominate. The forgiveness buffer
  (`max_energy / credit_gain`) shrinks, so one lying measurement or
  one unlucky outcome can execute a proven entry.

Evidence: the one knob in the ablation grid that moved the kill.
Across 0.15 / 0.3 / 0.6 / 1.2 the median kill cycle went 2 / 1 / 0 / 0
and damage before kill shrank from -1.1M to -0.2M, with outcomes
otherwise identical
([benchmarks: ablations](benchmarks.md#ablations-survival-arm-5-seeds-one-knob-at-a-time)).
The default 0.6 buys the cycle-0 kill while keeping roughly 8 events
of buffer at the cap.

### `merge_threshold` (`SurvivalConfig`, default `DEFAULT_MERGE_THRESHOLD` = 0.55) and `EMBEDDING_MERGE_THRESHOLD` (0.85)

Mechanically: consolidation merges alive entries whose pairwise
similarity meets the threshold. Similarity comes from the retriever:
Jaccard token overlap for `LexicalRetriever`, cosine for
`EmbeddingRetriever`. Cosine runs hotter than Jaccard, which is why a
separate constant exists for embedding stores: with cosine
similarity, use `EMBEDDING_MERGE_THRESHOLD` (0.85) or higher, or
unrelated entries will consolidate.

The same threshold also drives conflict surfacing: the default
protocols built by `Ledger` and `SurvivalLoop` flag near-duplicate
retrieval hits as conflicting/overlapping advice at
`config.merge_threshold`, so "near duplicate" means one thing per
ledger. Raise it for a cosine retriever and conflict surfacing
follows automatically.

- **Too low**: unrelated entries merge. Provenance blurs (merged
  entries union their sources), and a wrong answer can ride a merged
  entry's pooled energy.
- **Too high**: near-duplicates never merge and compete with each
  other for the same earnings instead of pooling.

Evidence: lexical ablation 0.4 / 0.55 / 0.7 left outcomes identical,
population 5 / 4 / 4
([benchmarks: ablations](benchmarks.md#ablations-survival-arm-5-seeds-one-knob-at-a-time)).
At demo scale this knob is hygiene, not safety. No committed sweep
exists for the embedding threshold beyond the 0.85 constant shared by
the bench embedding arm; treat 0.85 to 0.9 as the supported range.

### `expire_after` (`Ledger.tick`, CLI `ledger tick` and `settle-ci`, default 50)

Mechanically: a ticket left unsettled for more than `expire_after`
ticks settles at delta zero on the next tick (the outcome never
arrived, which earns nothing). While pending, a ticket escrows every
entry in its provenance: escrowed entries pay upkeep but cannot be
buried or merged.

- **Too low**: slow outcomes (a nightly suite, a monthly cost report)
  expire before they land. The late `settle` then returns False and
  the deserved credit, positive or negative, is dropped.
- **Too high**: forgotten tickets pin entries in escrow. Dead weight
  cannot be buried, consolidation skips escrowed entries, and the
  population stops self-curating around them.

Evidence: code default only; no committed benchmark sweeps this knob.
Size it in ticks of YOUR cadence: if you tick per merged PR, 50 means
a ticket survives 50 merges; if you tick per session, 50 sessions.
Call `abandon` on tickets you never act on instead of letting them
expire, which releases escrow immediately.

### `min_coverage` (`LexicalRetriever`, default 0.25)

Mechanically: the relevance floor. An entry qualifies only when its
matched IDF mass covers at least this share of the query; below the
floor, memory stays silent rather than guessing.

- **Too low**: entries sharing one structural token decide questions
  they know nothing about, and the environment executes them for it.
- **Too high**: useful advice goes silent, earns nothing, and
  starves. A persistently high silence rate is the single best
  debugging signal (see `SurvivalReport.health_warning`).

Evidence: a real sweet spot in the ablations. 0.25 scored cum +12.5M
with benign capability 1.00; 0.15 fell to +7.4M / 0.67 with 7x tail
variance; 0.4 fell to +6.5M / 0.67
([benchmarks: ablations](benchmarks.md#ablations-survival-arm-5-seeds-one-knob-at-a-time)).

### `min_similarity` (`EmbeddingRetriever`, default 0.30)

Same role as `min_coverage` for cosine retrieval: below the floor,
silence. No committed benchmark sweeps this value; 0.30 is the code
default and the bench embedding arm ran at it. If you swap in a real
embedding model, expect to re-tune it, because cosine score
distributions differ by model.

### `max_energy` (`MemoryStore`, default 5.0)

Mechanically: the energy cap. Bounds how much past success an entry
can bank, which bounds both immortality and the forgiveness buffer.

- **Too low**: one negative event can execute a long-proven entry;
  the system degenerates toward the strike-counter baselines the
  noisy suite shows collapsing under flaky measurements.
- **Too high**: entries become effectively immortal on banked energy,
  and stale knowledge outlives the world that earned it.

Evidence: no direct ablation is committed for this knob. The
magnitude-noise suite shows the cap doing real work: healthy deciders
sit at the 5.0 cap, where exaggerated rewards change nothing, and
that cap-clipping (with earn-back) is what makes size lies harmless
([benchmarks: magnitude](benchmarks.md#magnitude-the-model-where-only-the-ledger-could-lose)).

### `consolidate_every` (`SurvivalConfig`, default 5)

Mechanically: run consolidation every N cycles or ticks. Zero or None
disables it.

Evidence: the ablation (off / 5) left outcomes identical, population
3 / 4: hygiene, not safety, at demo scale
([benchmarks: ablations](benchmarks.md#ablations-survival-arm-5-seeds-one-knob-at-a-time)).
Consolidation cost is O(N^2) pairwise similarity, 1.1 s per pass at
10,000 entries ([benchmarks: scaling](benchmarks.md#scaling-synthetic-corpus-median-of-repeats-apple-m4)),
so on large stores run it less often rather than not at all.

### `supporting_share` (`SurvivalConfig`, default 0.25)

The slice of the deciding entry's credit that each supporting entry
receives. No committed benchmark sweeps it; 0.25 is the code default
used by every committed result. Raising it spreads credit (and blame)
across retrieval neighbors that may not have contributed.

### `k` (retrieval breadth: `Ledger.decide`, `QueryProtocol.answer`, default 3)

How many entries retrieval returns per query: one decider plus k-1
supporters in local mode. No committed benchmark sweeps it. Larger k
widens escrow per ticket and spreads supporting credit thinner.

### `half_life` (retrieval option: `MemoryStore.retrieve`, `Ledger.decide`, `--half-life`, MCP `memory_query`; default off)

Mechanically: opt-in recency-weighted ranking. A retrieval score is
multiplied by `0.5 ** (age / half_life)` where age is ticks since the
entry last settled an outcome (its born tick if nothing ever has). A
pure ranking concern: balances, credit, and escrow never see it, and
a non-positive value raises `ValueError` instead of silently ranking
without recency.

- **Too low**: ranking becomes a recency contest. Proven old entries
  lose to anything settled lately, and the relevance signal the
  retriever computed is mostly discarded.
- **Too high**: indistinguishable from off; stale-but-once-correct
  entries keep outranking newer corrections until selection kills
  them the slow way.

Evidence: none committed. No benchmark sweeps this knob and there is
no default to cite because it defaults to off. If you opt in, size it
in your tick cadence the same way as `expire_after` (a half-life of
one expiry window is a defensible starting shape, not a measured
one). The age lines and conflict blocks on consult surfaces arrive
regardless of this knob; only the ordering changes.

## Starting points by profile

| knob | CI lesson store | coding-agent lesson store | generic agent memory |
|---|---|---|---|
| `resource_scale` | 2.0 (tests) | 2.0 (tests), or your typical per-change test delta | 1.0, then set to one meaningful outcome in your unit |
| `upkeep` | 0.05 (default) | 0.05 (default) | 0.05 (default) |
| `merge_threshold` | 0.55 (lexical default) | 0.55 lexical, 0.85+ with embeddings | 0.55 lexical, 0.85+ with embeddings |
| `expire_after` | 50 (default; one tick per merged PR) | 50 (default; tick per session or work unit) | 50 (default; tick at session end) |
| tick cadence | per merged PR (`settle-ci` does it) | session or work-unit boundary | session boundary (`memory_tick`) |

What is evidence-backed in that table and what is not:

- **CI lesson store**: scale 2.0 and the per-merge tick are the
  committed convention this repo runs on itself
  ([integration guide](integrations/ci-lesson-store.md), the
  `memory.yml` workflow, and `TestSuiteEnv.resource_scale = 2.0`).
  They are a working deployment, not a benchmark sweep. At these
  settings a one-test improvement earns about 0.28 energy
  (0.6 * tanh(0.5)), roughly 5.5 merges of upkeep, and an unproven
  lesson has 20 merges to earn before starving. The noisy suite is
  the supporting evidence for trusting CI as the settler: at 5%
  flaky-test noise survival's true outcomes were identical to its
  noise-free run in all 30 seeds, and `settle-ci` quarantines repeat
  flakers besides
  ([benchmarks: noisy outcomes](benchmarks.md#noisy-outcomes-the-forgiveness-test)).
- **Coding-agent lesson store**: the same numbers transfer because
  the resource is the same (passing tests); that transfer is an
  argument, not a measurement. No committed bench runs an
  interactive-agent workload. Two rules matter more than any knob:
  settle with measured deltas only, and `abandon` every ticket you do
  not act on.
- **Generic agent memory**: the defaults are code defaults, full
  stop. No committed benchmark covers units other than bytes
  (StorageEnv) and tests (TestSuiteEnv). The ablation's
  factor-of-four insensitivity around the right scale (25k vs 100k
  identical) suggests you need the right order of magnitude, not the
  right number. And check the fit first: darwin-memo needs a
  conserved, measurable outcome to settle against. Chat preferences
  and RAG-over-docs have none, upkeep will starve the long tail, and
  the README says not to use it there.

## When it misbehaves

- **Everything starves around tick 20**: that is the starvation
  horizon at defaults. Either memory is silent (task phrasing does
  not overlap the corpus: lower `min_coverage`, fix phrasing, or use
  an embedding retriever) or answers never earn (your environment
  never pays out: check `decision_polarity` vocabulary and your
  settle wiring). `SurvivalReport.health_warning` diagnoses both, and
  `darwin-memo audit FILE` shows decides, silence, and settlement
  flow over any window.
- **An entry died and you do not know why**: `darwin-memo why FILE
  ENTRY_ID` prints its full life: birth, every settlement, merges,
  cause of death.
- **Population grows without bound**: upkeep too low for your tick
  cadence, consolidation disabled, or escrow pinning (check
  `pending_tickets` in `ledger stats`; abandon stale tickets).
- **Proven entries keep dying on single events**: `credit_gain` too
  high relative to `max_energy`, or your deltas saturate tanh because
  `resource_scale` is too small.
