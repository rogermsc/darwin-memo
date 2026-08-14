# Changelog

All notable changes to this project are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project uses [SemVer](https://semver.org/).

## [Unreleased]

### Added

- Oracle-retrieval control for the SWE-Bench-CL leg
  (`--oracle-retrieval`, `code_retrieval.oracle_files`). The paper's own
  limitation names this as the missing arm: BM25 correct-file recall is 74%, so
  the real-task null is consistent with either an absent memory effect or a
  retrieval ceiling, and nothing separates them. The control fills the code
  budget with the files the gold patch touches, before BM25, holding budget,
  truncation and prompt shape identical — only *which* files fill the budget
  changes. It reads the answer key by construction, so any run using it records
  `oracle_retrieval: true` in its config and is a control, never a result.
  Numbers still need a full matrix (docker + endpoint), which this does not run.
- `budget_relevance` bench arm and the `neighbours` suite: a reconstruction of
  EMBER-style budgeted evidence retention (arXiv:2606.05894), the nearest
  published mechanism to the energy ledger. Held at `budget=4` — the population
  survival converges to — so both arms keep the same number of entries and
  differ only in what buys a place. Over 10 seeds survival kills the poison
  10/10 and ends at +12,586,803; `budget_relevance` kills it 1/10 (and that one
  by luck, evicted at cycle 0 before any query matched it) and ends at
  −3,141,427. Relevance is not a defence: poison written in the task's own
  vocabulary scores maximally relevant to exactly the queries it waits for.
  Kept out of `ARMS` so `headline.json` stays byte-stable.
- Literature review of 2026 agent-memory work
  (`docs/research/2026-08-14-literature-review.md`), with every entry marked
  `[read]` or `[surveyed]` and given a verdict (cite / arm / adopt / scope-out).
  It adds the attack-side citations the paper was missing (MINJA's query-only
  injection, AgentPoison, environment-injected and control-flow attacks), the
  learned-credit-assignment line the ledger is the judge-free alternative to,
  and the two nearest mechanism neighbours (adaptive admission control,
  EMBER's budgeted retention). `docs/threat-model.md` gains the
  curation-targeted attack it was missing and a section on attacks that never
  write — query-only injection defeats a trusted-settler assumption without
  violating it, and outcome-grounded revocation has no claim over an entry no
  consequence is attributed to.
- Organic memory Phase 4: earned importance + potentiation
  (`darwin_memo.organic.EarnedImportance`, `OrganicMemory.importance()` /
  `centrality()` / `upkeep_scale()`). Importance is three measured quantities
  normalised against the live population — recall count, outcome credit above
  the spawn grant, and associative centrality — averaged at equal weight. It
  biases retrieval ranking always, and slows upkeep only when a caller passes
  `upkeep_scale()` to the new `MemoryStore.charge_upkeep(scale=...)`.
  `charge_upkeep` clamps any multiplier to `[MIN_UPKEEP_SCALE, 1.0]`, so
  potentiation can stretch an entry's starvation horizon roughly fourfold and
  can never remove it: death stays an energy-floor event for every unpinned
  entry, and no caller in this package opts in — `SurvivalLoop` and `Ledger`
  charge flat upkeep unchanged. **Potentiation makes usage a retention signal,
  which this repo's own `salience_matched` arm measured at a 0.20 poison kill
  rate against random eviction's 0.80** (`bench/results/salience.json`); that
  result, and the flat-upkeep control to measure against, are documented in
  `docs/organic.md` before the usage example.

- Organic memory Phase 3: spreading activation + Hebbian reweighting via a new
  `OrganicMemory` facade (`darwin_memo.organic`). A recall spreads a fraction of
  activation one hop to related memories and strengthens the links it traverses
  (`HebbianWeights`, symmetric learned co-recall strengths); `related()` returns
  the effective relatedness `clamp01(cosine + learned)`, and `decay()` runs two
  timescales (activation x0.5, learned links x0.9). Additive over Phases 1-2,
  core untouched; activation and learned weights gate surfacing/ranking only,
  never survival — no judge, no new runtime deps.

- The preprint and its reproduction package (`paper/`, `bench/swebench_cl/`).
  Two experiments: Write-Execute-Forget against the `evict_on_negative`
  counter (adoption ties at 0.02, the counter revokes 5-9 cycles sooner, and
  the ledger is the only arm ending with no poisoned entry alive — the
  pre-registered "revokes faster" claim is marked *not supported*), and
  SWE-Bench-CL, 5 arms x 2 sequences x 3 seeds over 615 tasks scored by the
  official docker harness, where `memory_on` beats the token-matched random
  control by +0.052 [-0.037, +0.141], p = 0.50 — **a null, reported as one**.
  `bench/swebench_cl/matrix.py` is a resumable subprocess-per-cell driver and
  `curve.py` scores the pre-registered claim, dropping unpaired worlds rather
  than zero-filling them.

- Selection-quality arms for the distill suite, answering an adversarial
  review that the poison result is tautological. `distill_noisy`
  (`bench/distill/noisy_run.py`, `FlakyQAEnv`) adds a counter baseline
  (`evict_on_negative`/`evict_consecutive`) and shows the poison=0 result is
  not ledger-specific — the ledger's edge is *capability retention under
  noise*: survivor-distilled keeps recall 0.91 under `flip@0.2` while counters
  collapse to ~0. `distill_rule` (`bench/distill/rule_corpus.py`,
  `rule_run.py`) uses benign-distribution poison scored on held-out services:
  the unfiltered model *generalizes* the harmful rule to 60% of unseen
  services (not memorization), survival prevents it (0.00) and keeps the safe
  rule (1.00). Docs reframe the distillation section to lead with capability
  retention, not poison resistance.

### Fixed

- **`budget_relevance` was nondeterministic at a fixed seed**, contradicting its
  own docstring. Eviction ties broke on `entry.id`, which defaults to
  `uuid4().hex[:12]` — and because `LexicalRetriever.rank` drops everything under
  `min_coverage`, most entries sit at exactly 0.0, so the victims among them were
  drawn by random id. Five runs at seed 0 produced five different survivor sets
  and two different cumulative deltas. The sort now uses the score alone and
  relies on Python's stable sort to keep store order, matching
  `run_salience_matched`. `bench/results/neighbours.json` was regenerated: every
  substantive metric is now identical across independent runs (only
  `wall_time_s` varies), and the published figures are unchanged — they were
  correct, but they were not reproducible.
- **`OrganicMemory` read a graph built once in `__init__` while the store moved
  underneath it.** A buried entry stayed a neighbour indefinitely, and a newly
  minted one had no vector at all — centrality 0.0, which through
  `upkeep_scale()` charged every new entry *full* upkeep for not having existed
  when the graph was built, while dead entries propped up their neighbours'
  scores. `OrganicMemory.sync()` now reconciles the graph with the store and is
  called by the read paths; `AssociativeGraph.ids` exposes what it needs.
- `MemoryStore.ticks_to_starvation` ignored the new upkeep `scale`, so the
  starvation horizon published by `observe.timeline`, `observe.economics` and the
  dashboard column was up to 4x too short for any potentiated entry. It now takes
  the same mapping `charge_upkeep` does.
- `--oracle-retrieval` without `--code-context-chars > 0` is now refused: the
  oracle had no effect (retrieval is skipped entirely) but the run was still
  recorded as `oracle_retrieval: true` — a blind run filed as the
  retrieval-ceiling control. An oracle task whose gold file is not a retrieval
  candidate (non-`.py`, over the size cap, or under a skipped directory) now
  warns and is counted in `oracle_missed_tasks` instead of silently degrading to
  BM25 while still claiming the control.
- Single-sourced two duplicated definitions the review found: the unified-diff
  parser (`poison._touched_files` was a byte-for-byte copy of
  `code_retrieval.oracle_files`, so a fix to one would have left the harness
  disagreeing with itself about which files a gold patch touches), and the
  `[0, 1]` clamp (three copies across two organic modules). `SPAWN_ENERGY` is now
  read off `MemoryEntry` rather than restating its default, and
  `run_budget_relevance` rejects a budget below 1 instead of silently evicting
  the whole population every cycle.
- **A cited number that could not be reproduced from its source.** Three paper
  sections stated that content detectors average 63.6% true-positive rate on
  strong-signal payloads and 31.6% on weak-signal ones, attributed to
  `mpbench2026`. That pair appears nowhere in the paper, and no aggregation of
  its Table 4 produces it (four off-the-shelf detectors average 58.33 / 24.98;
  all seven rows 61.27 / 33.18). Replaced with the printed per-detector figures
  — PromptArmor 84.44% → 42.50%, DataFilter 28.86% → 10.74%, an 18-to-42-point
  drop for every detector — so no arithmetic of ours sits between the source and
  the claim. The argument is unchanged and better supported; only the numbers
  were wrong. Corrected in `related.tex`, `experiments.tex`, `limitations.tex`
  and in `docs/research/2026-08-01-memory-security-pivot.md`, where the figure
  entered.
- Bibliography defects: A-MEM sat in `references.bib` uncited, and Zep and Letta
  were named in prose with no entries at all. All three are now cited where the
  scope-out is stated, alongside LongMemEval as the benchmark family that
  scope-out refers to.
- The organic layer was excluded from the coverage gate wholesale
  (`omit = ["darwin_memo/organic/*"]`) for a reason — the optional turbovec ANN
  path cannot run in default CI — that was only ever true of
  `turbovec_backend.py`. Three shipped, zero-dep modules sat behind it untested.
  The omit is now that one file, and `tests/test_organic.py` covers the graph,
  activation and dynamics (100% of each), every test naming the mutation it
  catches.
- Result validation checked a hand-maintained file list in three places
  (`reproduce.sh`, `reproduce.md`, CI) next to a directory that grows: CI
  validated 10 of 17 committed files and reported green, and `check()`
  enforced the storage suites' metric schema on every suite, leaving the
  distillation results unvalidatable. Required metrics and the wall-clock key
  are now per-suite and all three call sites glob.
- `reproduce.sh` failed from a clean clone under stock macOS `python3` (3.9,
  below the >=3.10 floor) and blamed the package — "darwin-memo not
  installable from PyPI" — instead of the interpreter. The version is now
  checked before anything is built.
- Retrieval, not the edit format, was the ceiling on the SWE-Bench-CL arms:
  every failing SEARCH block named a file that was never retrieved. BM25
  gold-file recall was 37% at the 60k/5 budget and is 74% at 300k/10,
  measured and disclosed in the paper.

## [0.6.0] - 2026-08-10

### Added

- `MemoryStore.ticks_to_starvation(entry)`: how many ticks of upkeep an
  entry can still pay, surfaced by `top`, `why` and `/api/state` from one
  definition so they cannot drift. `None` means *cannot starve* — a pinned
  entry floors at zero rather than dying, and a store with no upkeep never
  starves anything — which is not the same as zero ticks left.
- The tick event now records the upkeep actually charged, so
  `economics()` reports a measured figure with `upkeep_exact: true` instead
  of estimating. The estimate really was wrong: a pinned entry sitting at
  zero pays less than a full tick, and the naive population-times-upkeep
  figure counted it in full. Preference is all-or-nothing — a log where only
  some tick records carry the figure falls back to the estimate, because
  summing a measured tick with an estimated one reports a number that is
  neither. Logs written before this release are unaffected.

- Organic memory Phase 2: in-memory `ActivationState` (recall-salience;
  `bump`/`decay`/`level`) plus lossless `surface(entry, state)` / `detail(entry)`
  — a recalled memory expands to detail, an idle one shrinks to its gist, with
  the entry never mutated. Organic-only, core untouched; activation gates
  surfacing, never survival. The invariant that activation must never influence
  retention is now defended by tests rather than only documented
  (`tests/test_organic_invariant.py`): a structural test asserting no
  selection-path module references activation, and a behavioural one asserting
  that pinning a poisoned entry's activation at maximum changes neither its
  death cycle nor the survivor set.

- Organic memory layer, Phase 1 (`darwin_memo.organic`, opt-in): an
  `AssociativeGraph` giving one vector per memory and `related(id, k)`
  relevance-weighted neighbours, as the substrate for a future adaptive,
  brain-like memory. Zero-dependency default (`HashingEmbedder` +
  `BruteForceBackend` exact cosine); optional turbovec ANN backend via
  `darwin-memo[organic]` (0.92 top-3 agreement with the exact backend).
  Additive and read-only w.r.t. survival — relatedness is mechanical cosine,
  value is still earned by the ledger; no judge. See `docs/organic.md`.

- The operator surface: `darwin-memo doctor` names the failure mode
  behind a store that is not earning, and `darwin-memo ui` serves a
  local read-only dashboard over the same data.
  - Shared degeneracy rules (`darwin_memo/diagnose.py`): the six
    findings the batch loop and the event-driven Ledger can hit now
    live in one place (`selection_findings` for the two shared to both
    shapes, plus four Ledger-only operational findings in
    `observe.py`), so a fix lands once and the two surfaces cannot
    drift. `SurvivalReport.health_warning` now delegates to the shared
    rules instead of carrying its own copy, and gained its first
    tests. Two of the six rules were corrected during implementation
    after they produced false positives on this project's own
    flagship demo: `starvation_cliff` now also requires that nothing
    was ever credited in the window (starving alone is a healthy death
    mode for trivia nobody needed — the fault is a population that
    never earns), and `settles_dropped` now fires only on the excess
    beyond the count of silent decides, since a silent `decide()`
    never opens a ticket and settling one always drops as a benign,
    expected event.
  - `darwin-memo doctor MEMORY [--json]`: reads the store and its
    event log and reports zero or more of `silent_majority`,
    `env_never_paid`, `starvation_cliff` (all severity `error`), and
    `tickets_stale`, `settles_dropped`, `credit_untracked` (severity
    `warn`), each with evidence and a fix. Exit code 1 if any finding
    is an error, 0 otherwise (clean or warnings only). See the finding
    table in [docs/api.md](docs/api.md#doctor-findings).
  - `darwin-memo ui MEMORY [--port 8787] [--no-open]`
    (`darwin_memo/ui.py`): a stdlib-only loopback HTTP server (no new
    runtime dependency) plus a built Vite/React/TS dashboard
    (`ui/`, shipped inside the main wheel via `package-data`, no
    `[ui]` extra). Loopback-only and read-only by construction —
    `serve()` refuses to bind outside `{127.0.0.1, localhost, ::1}`
    and there are no mutation endpoints, so the server needs no
    authentication. The store and event log are re-read from disk on
    every request. Four JSON routes (`/api/state`, `/api/entry/{id}`,
    `/api/events`, plus the static bundle) render population, energy,
    the `doctor` findings, `timeline`, `economics`, living entries,
    the graveyard by cause of death, and pending tickets.
  - `timeline` and `economics` on the observe surface
    (`darwin_memo/observe.py`): `timeline(events)` buckets settled
    deltas by tick (by write order, not the settle record's own tick
    stamp, since `Ledger.tick()` settles expired tickets inside the
    same window it logs). `economics(events, store)` reports the
    **resource** ledger (settled deltas in world units) and the
    **energy** ledger (the internal dimensionless mechanism)
    separately and never summed, because they are different units.
    Upkeep is reported as `upkeep_paid` with an `upkeep_exact` flag;
    logs written before the tick event carried the charged figure fall
    back to a population-times-upkeep estimate.
- Distillation benchmark arm (`bench/distill/`, `python -m bench.run
  --suite distill`): an opt-in, GPU/`transformers`-required family that
  measures survival selection as a *data filter for parametric memory*.
  It distills the energy-ledger survivor set, the unfiltered raw set, and
  the LLM-judge-kept set into separate LoRA models over a small base
  model, then scores each by exact containment — `good_recall` and
  `poison_reproduction` — alongside an untrained `base_model` floor and a
  `retrieval` reference row. The corpus (`bench/distill/corpus.py`) is a
  purpose-built QA set over `VerifiableQAEnv`: distinctive facts that earn
  and survive, distinctive poison that is blamed and buried, with
  consolidation disabled so survivors stay distinct. Headline: the
  survivor-distilled model recalls the good facts and reproduces none of
  the poison; the raw-distilled model reproduces it. The trainer
  (`bench/distill/train.py`) now backs both this arm and the
  `training/train_memory_model.py` CLI (one code path, pad-token and
  prompt-masking fixes), and the script is a thin wrapper over it.
- Distillation arm: a `distill_judge_floor` control that settles the LLM
  judge's keep/cull verdicts through the energy ledger (keep +0.6, cull
  −0.6, upkeep, die at the floor) instead of instant bury. It shows the
  floor-free judge's collapse is the *missing floor*, not bad judgment:
  settling the identical verdicts with a buffer recovers recall 0.93 /
  poison 0.00 (5 seeds), nearly the measured ledger, where the floor-free
  judge keeps almost nothing.
- Continual learning via task-vector merging (`bench/distill/merge_run.py`,
  `python -m bench.run --suite distill_merge`): distills one
  survivor-filtered LoRA adapter per disjoint corpus and merges them with
  `peft.add_weighted_adapter` (`cat`/`linear`/`ties`). The merged model
  recalls both corpora (cat/ties ≈ a joint-trained ceiling, linear
  interferes) while poison reproduction stays 0 after merge, alongside
  `solo` and `joint` baselines.

### Security

- `darwin-memo ui`'s `Host` header check (`darwin_memo/ui.py`,
  `_host_only`) now requires an exact match — a loopback name or
  address, optionally followed by a numeric port, and nothing else —
  instead of truncating at the first colon or the first `]`. That
  truncation let `127.0.0.1:PORT@evil.com` and `[::1]evil.com` parse
  down to a bare loopback host and pass; a browser can't put either
  string in a real `Host` header, so this closes a parser looseness,
  not a live DNS-rebinding hole. Host name comparison is also now
  case-folded per RFC 3986/7230, fixing a real false rejection where
  `Host: LOCALHOST` was wrongly refused.

## [0.5.2] - 2026-08-06

### Fixed

- `pip install "darwin-memo[mcp]"` installed a server that could not
  start. The extra declared an unbounded `mcp>=1.10`, and mcp 2.0.0
  removed `mcp.server.fastmcp` outright, so the import in
  `mcp_server.build_server` raised `ModuleNotFoundError` on every Python
  version for anyone who installed the extra after that release. The
  range is now capped at `mcp>=1.10,<2`. Supporting 2.x means porting to
  its new API and is not part of this fix.
- Three tests guarded on `importorskip("mcp")`, which succeeds under
  mcp 2.x and then fails on the missing submodule rather than skipping.
  They now guard on `importorskip("mcp.server.fastmcp")`, the module
  actually required.

## [0.5.1] - 2026-06-13

A large release: 15 merged PRs since 0.5.0, all under the energy
ledger's existing selection rule. The headline themes are observability
(`top`/`why`/`audit`), a trust lifecycle for imported and pinned
lessons, two new opt-in benchmark families (TestSuiteEnv and SWE-Bench-CL),
control arms that answer two standing objections against the ledger
(a Hoeffding bandit and an LLM judge), an LLM-mode arm that runs a local
model on the per-cycle citation work, temporal retrieval surfaces, a
Claude Code memory renderer, an OpenAI Agents SDK adapter, and the MCP
registry listing. The benchmark evidence also reorganizes around
independent seeds, which corrected two earlier headline claims (see
Changed).

### Added

- Memory observability (`darwin_memo/observe.py`): three read-only CLI
  subcommands over what the engine already records. `top FILE` ranks
  living entries by balance with kind, age, last settlement, and
  source (human table, `--json` for machines); `why FILE ENTRY_ID`
  prints one entry's full life story (birth tick, source, stake, every
  settlement with delta/credit/detail/ticket, merges, current balance,
  and for dead entries the graveyard path and cause of death);
  `audit FILE [--since TS] [--last N]` digests the JSONL event log
  (decisions, settlements, culls, total energy flow, top gainers and
  losers) so a poisoned entry's rise, drain, and burial all read off
  the trail. The Ledger now records the structured history, settle
  per-entry credits/burials, tick culled ids, and add source/stake the
  digest needs, backward compatibly (older plain-string notes still
  load and render; missing fields render as unknown, not a crash). The
  event log rotates at a configurable byte threshold (default 10 MB)
  and the audit reader globs across rotated files. MCP gains a
  `memory_audit` tool returning the identical digest JSON.
- `darwin-memo settle-ci` (`darwin_memo/ci.py`): productizes CI lesson-
  store settlement. The primary mode diffs junit XML per test id (base
  run vs head run) and settles tickets from the transitions
  (pass->fail regressions, fail->pass improvements, added and removed
  tests attributed as suite changes) instead of smearing into a raw
  pass count. Infra failures abstain: no parseable XML, zero collected
  tests, or a collection error leaves the store untouched and exits 3,
  killing the documented `|| echo 0` fake-delta bug. Flaky tests
  quarantine themselves via per-test flip history in a sidecar
  `flaky.json` and are excluded from deltas until they stabilize. Raw
  pass-count diffing stays as the documented degraded fallback for
  ecosystems without junit XML. The repo's own memory workflow now
  routes through the subcommand.
- OpenAI Agents SDK session adapter
  (`darwin_memo/integrations/openai_agents.py`): `DarwinMemoSession`, a
  dependency-free duck-typed implementation of the SDK's `Session`
  protocol (`session_id` plus async `get_items`/`add_items`/`pop_item`/
  `clear_session`, latest-N-in-chronological-order limit semantics)
  backed by one greppable JSONL file per session id. The darwin-memo
  value-add stays explicit opt-in: `consult()` runs `ledger.decide()`
  and returns rendered lessons for injection, `settle()` and
  `abandon()` delegate to the Ledger, and lesson operations persist
  when `lesson_path` is configured so open tickets survive a process
  restart. The adapter never invents deltas; the host measures
  outcomes.
- `darwin-memo render STORE -o MEMORY.md`: project top-balance
  survivors into Claude Code's auto-memory file under both ceilings the
  host actually loads, a hard byte budget (`--budget`, default 25kb)
  and a hard line cap (`--max-lines`, default 200), with admission
  measured against the fully rendered document. Deterministic: same
  store, same arguments, byte-identical output. `--split-dir DIR`
  writes one topic file per kind plus a budget-aware index that counts
  only the topics it links, and a re-render deletes topic files for
  kinds with nothing left to show, so dead lessons never linger on the
  reading surface. A missing or empty-world store renders a minimal
  honest file; an unreadable store (empty, truncated, locked, or not a
  store payload) exits with a one-line error and leaves the previous
  render untouched, so hooks and cron jobs can run it unconditionally.
- Temporal awareness in retrieval (`darwin_memo/temporal.py`):
  `MemoryEntry.recorded_ts` stamps creation in UTC (legacy files load
  as "age unknown" instead of faking a date). One choke point
  (`render_consult`, applied by the query protocol) annotates every
  consult surface (CLI `query`, `ledger decide`, MCP `memory_query`,
  LLM-mode snippets) with each entry's age, while acting paths
  (survival loop, environments) keep reading the raw text so the
  economics never see an annotation. Hits overlapping above the shared
  `DEFAULT_MERGE_THRESHOLD` surface as a conflict group, newest first,
  marked as overlapping advice (mechanical, no LLM judging). Opt-in
  recency-weighted ranking (`half_life` in ticks, off by default,
  exposed on `store.retrieve`, `protocol.answer`, `ledger.decide`,
  `--half-life`, and MCP `memory_query`) is a pure ranking concern;
  balances are untouched. Kind and source metadata filters narrow
  candidates before ranking. The time dimension shapes what gets
  surfaced, never what gets paid.
- `darwin-memo import SRC DEST [--probation N]`
  (`Ledger.import_entries`): copy another store's living entries on
  probation. Imports arrive at spawn energy with provenance labels
  (`imported_from`, `imported_at`), cannot be the deciding entry of
  any answer until they graduate through N net-positive locally
  measured settlements (default 3), never consolidate while on
  probation, and earn at most the supporting share while riding
  along, on the even-spread path too. A consult where every hit is
  probationary is withheld outright. Idempotent on ids: re-importing
  neither duplicates entries nor resurrects ones that died here.
  `--probation 0` is the explicit trusted-bootstrap path.
- `Ledger.pin` and `unpin` (`ledger pin`/`unpin` CLI): a pinned entry
  pays upkeep and takes settlement losses, but its balance floors at
  zero on both paths, so neither starvation nor a negative outcome
  can bury it; consolidation never merges it and `forget` refuses it
  until unpinned. For rare-but-critical knowledge whose payoff
  cadence is longer than the starvation horizon. Pinned status
  surfaces in `top` and `why`.
- `SurvivalConfig.admission_window` (default 0, off): entries written
  through `Ledger.add` start juvenile for K settlements, earn and
  lose deciding credit at `supporting_share`, and one negative
  deciding outcome denies admission on the spot. Bounds the
  documented lesson price to a single settlement's damage.
- Statistical rigor for the benchmark suite: seeded bootstrap 95% CIs
  on every aggregate column, `bench.report --paired ARM_A ARM_B`
  per-seed difference tables, and `bench.report --tests` (exact paired
  sign-flip permutation tests vs a baseline, Holm-Bonferroni adjusted
  across the full printed grid). Committed raw evidence
  (`bench/results/headline.json`, `noisy.json`, `ablation.json`) is
  bound to `bench/results/MANIFEST.json`: suite, seeds, config hash,
  exact reproduction command, library version, and producing git
  commit per file. CI validates each committed file against its entry
  with `bench.report --check --require-manifest`, which fails if the
  manifest or the entry goes missing.
- TestSuiteEnv promoted to a full benchmark family (a second
  environment family alongside StorageEnv, closing the
  single-family gap the docs named their largest credibility issue).
  `run_suite_detail` returns the set of passing test names and
  `TEST_NAMES` derives the canonical roster from the suite source so
  consumers cannot drift from what runs. `bench/testsuite_fixtures.py`
  is a 20-entry corpus with deliberate redundancy (five cross-source
  near-duplicate twin pairs the merge machinery consolidates), an
  actively-wrong poison lesson, inert poison and ballast,
  decision-polarity probes, and provenance-scored paraphrase probes.
  `bench/testsuite_noise.py` models CI flakiness as flaky pass counts
  (one-sided by construction: a red build can lie, a green one cannot).
  The headline (eight arms) and noisy grid (rates 0.00 to 0.20) are
  pre-committed in `docs/benchmarks.md` and the results are committed
  (`bench/results/testsuite.json`, 8 arms x 10 seeds;
  `testsuite_noisy.json`, 35 cells x 30 seeds). The pre-committed
  question's number landed intact: the ledger's forgiveness beats the
  naive strike counter at 10% flake and not below, k=3 and quarantine
  m=3 beat the ledger across the band, and survival is never the best
  arm in any cell. A four-cell testsuite slice rides in the CI smoke
  suite so the family cannot rot unexercised.
- SWE-Bench-CL learning-curve pilot harness (`bench/swebench_cl/`):
  pins one or two continual-learning sequences (dataset commit plus
  file sha256, task identity in a committed manifest), runs a model
  through them task by task under three arms (memory_on, memory_off,
  random_matched at the same injected-token budget), settles the
  lesson store from the official SWE-Bench evaluation outcome, and
  mints one lesson per task from a deterministic template (no LLM
  judging; only the model's quoted reflection is model-authored).
  Model calls sit behind one OpenAI-compatible endpoint config, so a
  local Ollama server and a frontier provider differ by config only.
  The Docker executor sizes every image from the registry before
  pulling and refuses any pull that would leave less than 4 GB of
  disk free; the documented stub executor exercises every runner
  path offline and labels every report `mode="stub"`. The pilot
  protocol and its pre-committed cells live in `docs/benchmarks.md`
  before any result exists.
- `policy_bandit` control arm (`bench/policies.py`): the AEL objection
  (arXiv 2604.21725, a simple bandit over retrieval policies matches
  outcome-settled selection under noise) run rather than argued. Each
  entry is a bandit arm; every decided task is a pull paying reward 1
  (positive reported delta) or 0 (negative); an entry is culled by
  successive elimination when even its optimistic estimate
  `mean + sqrt(ln(T) / (2n))` (Hoeffding radius, T = total recorded
  pulls) falls below 0.5, with no eliminations before two pulls.
  Stdlib, deterministic, no energy, no upkeep. 240 runs are committed
  (`bench/results/bandit.json`, manifest-bound), the boundary is
  published as promised: under one-sided false_bad noise the bandit
  matches survival (at 35% the paired diff is +0.14M, adjusted
  p = 0.68, a statistical tie) and keeps full benign capability, while
  it cannot starve dead weight (final population near keep_everything),
  kill promptly (clean-cell poison kill at median cycle 1.5 vs
  survival's 0), or survive symmetric flip lies that pay the guilty
  (at flip 0.50 it bleeds to -9.08M while survival stays the only arm
  above zero). Opt-in is via the suite; the deterministic grid is the
  CI-safe part.
- `judge_settled` control arm (`bench/judge.py`): settlement by LLM
  verdict, the differentiating-claim test arXiv 2605.12978 predicts
  (judge-graded memories go faulty because the judge weighs prose where
  the ledger weighs measured consequences). A local LLM judge (Ollama,
  temperature 0) sees each deciding entry's lesson plus the
  environment's own outcome descriptions and returns one batched
  keep/cull verdict per cycle; unparseable or missing verdicts default
  to keep and are counted. The runner refuses this arm under
  measurement noise rather than leak ground truth through the detail
  strings. Five-seed grids are committed for two judges
  (`bench/results/judge-llama.json`, `judge-qwen.json`, manifest-bound).
  The honest exit, stated in advance, is what the grid lands on: the
  two judges split. llama3.2:3b degrades in the predicted direction
  (benign capability 0.67 vs survival's 1.00, 67 parse failures across
  five runs) but not significantly; qwen3:4b does not degrade. The one
  robust result is cost: settlement by measured outcomes runs in 0.03
  to 0.09 s per run, the same five judged cycles cost a mean 87.6 s
  (llama) and 1,514.2 s (qwen), four to five orders of magnitude above
  the ledger. Opt-in, never CI; sampled model output is not
  deterministic.
- `survival_llm` LLM-mode arm (`bench/llm_arm.py`): swaps the
  deterministic 3-stage protocol's answer step for a local model
  (Ollama, temperature 0) doing the per-cycle citation and extraction
  work, with the identical conserved-resource ledger on top, so the
  comparison is clean (same worlds, same selection rule, one side
  deterministic and effectively free). The `refuse_unparseable`
  mitigation (default off) turns an answer whose SOURCES line does not
  parse into silence (nothing earns, nothing is blamed) instead of the
  default even-spread fallback; an explicit `SOURCES: none` still
  parses and is honored. Committed evidence is manifest-bound with
  exact Ollama model digests. The robust finding is cost: the ledger
  does the same per-cycle work at roughly 12,000x (llama3.2:3b) to
  540,000x (qwen3:4b) lower wall time (one qwen run alone is about
  4.8 hours of model time for 120 queries). llama3.2:3b carries the
  statistics (n=5 per setting) and the mitigation is provably inert for
  it: it emitted a parseable SOURCES line on every answer
  (`citation_sources_line_rate` 1.00, `citation_fallback_rate` 0.00),
  so there was nothing to refuse and the off/on cells are a wash on
  true outcomes (both kill the poison every seed, paired p = 0.5000).
  qwen3:4b is committed at n=2, refuse-off only, as a cost existence-
  proof because its full grid is wall-clock-prohibitive; its two seeds
  disagree on sign for cum_delta, so it is reported as a direction, not
  a result. Opt-in, never CI.
- MCP registry listing: `server.json` lists the server on
  `registry.modelcontextprotocol.io` as `io.github.rogermsc/darwin-memo`
  (uvx with the `[mcp]` extra, stdio transport, the `darwin-memo-mcp`
  entry point). The registry verifies PyPI ownership by finding an
  `mcp-name:` marker in the package README, so the marker is in
  `README.md` and ships with this release (PyPI 0.5.0 is immutable and
  could not carry it retroactively). The new `mcp-publish.yml` workflow
  validates `server.json` on PRs that touch it and publishes on
  non-rc release tags (after waiting for the matching version on PyPI)
  or on manual dispatch, stamping the tag version into `server.json`
  and authenticating via GitHub OIDC with no stored secrets.
- `darwin-memo mcp`: the main CLI now serves the MCP stdio server,
  sharing the flag set and `DARWIN_MEMO_PATH` handling of
  `darwin-memo-mcp` (which keeps working unchanged). MCP registry
  clients construct launches as `uvx [runtimeArguments]
  darwin-memo@VERSION [packageArguments]`, and uvx runs the console
  script named after the package, which had no way to reach the
  server. `server.json` now installs the extra with `--with
  "darwin-memo[mcp]"` (with `--from`, uvx reads `darwin-memo@VERSION`
  as a literal executable name and fails) and passes `mcp` as a
  package argument, so machine-constructed launches start the server.
  Without the extra installed the subcommand exits with the exact
  `pip install "darwin-memo[mcp]"` command.
- Operator documentation written from the code and the committed bench
  evidence: `docs/tuning.md` (the load-bearing knobs, each with its
  mechanics, symptoms in both directions, and the benchmark section
  behind every number, plus starting points for three profiles, with
  the evidence status of each stated plainly), `docs/api.md` (the
  public Python surface, the temporal retrieval options, the OpenAI
  Agents SDK adapter, raised exceptions including `StoreLockedError`,
  the full CLI, and the eight MCP tools), `docs/store-format.md`
  (`memory.json` field by field with load defaults, the ledger key,
  the events JSONL and rotation, the lock and `flaky.json` sidecars,
  and the de-facto compatibility policy), and a `docs/README.md` index.

### Changed

- BREAKING (same-seed worlds): `StorageEnv`, `VerifiableQAEnv`, and
  `TestSuiteEnv` derive each cycle's RNG from `cycle_rng(seed, cycle)`,
  a SHA-256 hash of the pair, instead of `random.Random(seed + cycle)`.
  The old scheme made adjacent seeds shifted windows of one another
  (seed 3 at cycle 5 WAS seed 4 at cycle 4), so multi-seed spreads read
  smoother than independent draws justify. The same seed now produces a
  different world than released 0.4.0; the committed benchmark results
  record their producing commit in `MANIFEST.json` so the evidence
  stays reproducible from exactly the code that made it.
- Honest result corrections under the independent-seed re-analysis,
  stated plainly in `docs/benchmarks.md`: the survival vs
  `evict_on_negative` comparison in deterministic StorageEnv is now a
  statistical tie (7 of 10 seeds byte-identical, 3 small losses,
  adjusted p = 0.5), and no significance is claimed in either
  direction. The earlier 50%-flip headline (survival underwater and
  losing the paired sign test to the consecutive-strike counter) did
  not survive the seeded re-analysis: it came from the correlated-seed
  scheme. Under independent seeds survival stays positive on average at
  50% flip (+1.25M, the only arm above zero) and its 50% counter
  comparisons reach no significance, so the honest 50% claim is
  "indistinguishable from the counters, and nothing curates safely".
- The dogfood memory workflow (`.github/workflows/memory.yml`) now
  consumes the published reusable action `rogermsc/darwin-memo-action@v1`
  for install, settle, and abstention handling instead of inline
  steps. Behavior is preserved (scale 2.0, `expire-after` 50 matching
  the CLI, the concurrency group still serializing settlers), and the
  repo keeps its own commit step so the PR number stays in the settle
  message. Internal CI plumbing, no user-facing API surface.

### Security

- `docs/threat-model.md`, linked from SECURITY.md: the settle trust
  boundary, adversarial deltas, poisoned imports and what probation
  does not do, the price of a lesson and admission gating, prompt
  injection through lesson text, pinning as a trust statement, and
  the explicit non-goals.

## [0.5.0] - 2026-06-12

The release that unbreaks the published OpenClaw plugin: its install
instructions invoke `darwin-memo ledger`, which existed on main but
not in PyPI 0.4.0. It is also the first release where a concurrent
clobber of a store file is loud instead of silent.

### Added

- `darwin-memo ledger FILE OP`: every Ledger operation as a CLI
  subcommand with one JSON object on stdout (decide, settle, abandon,
  add, forget, tick, stats, obituary). The scripting bridge for shell
  scripts, CI steps, and host-process plugins, built for the OpenClaw
  memory plugin, whose host SDK ships no MCP client. The store
  auto-creates on first use; mutating ops save before printing (a
  crash cannot acknowledge an unsaved settlement, and invocations that
  overlap on one file trip the advisory lock instead of clobbering
  each other silently); events append to the same `.events.jsonl` the
  MCP server writes; and `forget` refuses entries escrowed by pending
  tickets, since burying one would let a later settle report success
  while crediting a corpse.
- Fail-loud advisory file lock on persistence: `MemoryStore.save`/
  `load` and `Ledger.save`/`load` hold `fcntl.flock` (`LOCK_EX |
  LOCK_NB`) on a sidecar lock file (`memory.json.lock`) for the
  duration of the operation, and contention raises `StoreLockedError`
  naming the lock file. Single-writer stays the contract: no blocking,
  no waiting, no multi-writer merge. The lock only turns a concurrent
  clobber from silent data loss into a loud error. POSIX-only; where
  `fcntl` is missing (Windows) it degrades to a documented no-op.
- `EvmSettler`: on-chain balances as the conserved resource, with zero
  dependencies (stdlib JSON-RPC). One settler measures one resource
  for one address, native wei or one ERC-20's raw units, via pinned
  block snapshots, so the decide-now-settle-later flow needs no
  archive node. Timestamp-bisection `block_at`/`measure` for
  retroactive windows, and `tx_cost` for single transactions
  (including the OP-stack `l1Fee`, verified to the wei against a live
  balance movement; reverted txs burn gas and move nothing). Default
  endpoint is `mainnet.base.org`, the only one of the public Base
  RPCs tested that served honest full-archive state: the module
  docstring names the one that silently lies about history. Closes
  the durable half of the Animoca Minds spike (#3);
  `examples/08_evm_settler.py` runs the loop offline.
- Dogfood: this repo now runs its own CI lesson store.
  `.darwin-memo/lessons.json` (seeded with real lessons from this
  repo's development by `.darwin-memo/seed.py`) is consulted by agents
  via `ledger.decide()`, tickets ride in PR bodies as
  `darwin-memo-ticket: <id>`, and `.github/workflows/memory.yml`
  settles them with the measured pass-count delta on every merged PR,
  ticks, and commits the curated store back to main. First production
  deployment of the flagship integration, on the repo that ships it.
- Noisy-outcome benchmark suite (`bench --suite noisy`): the ledger's
  forgiveness claim is now measured instead of asserted.
  `FlakyStorageEnv` makes measurements lie deterministically (the world
  stays truthful; arms decide off reported deltas and are scored on
  true ones) under three noise models: `flip` (symmetric sign flip),
  `false_bad` (flaky-CI shape: good changes report red), and
  `magnitude` (sign kept, size lied about: the one model where
  sign-driven heuristics are provably immune and only the ledger can
  degrade). The grid runs to 50% noise so the ledger's own failure
  boundary is published, not just the baselines'.
- Noise-hardened baselines, so the ledger is compared against the
  heuristic family's best selves rather than a strawman:
  `evict_on_negative` generalized to K lifetime strikes (K=1,2,3),
  `evict_consecutive` (strikes a success wipes clean), and
  `quarantine` (evict on blame, re-encode a fresh copy after a
  cooldown: the recovery path real deployments have).
- `bench.report --paired ARM_A ARM_B [--metric M]`: per-seed paired
  differences with win counts. Flake marks are a fixed property of the
  world at a given (seed, rate, model), so arms are exactly paired and
  mean±std understates what the data supports.
- Per-run lie accounting (`flakes_marked`, `flakes_fired`, fired
  counts split by direction, `reported_cum_delta`) with a hard
  accounting-identity check; `keep_everything` doubles as an in-suite
  canary (its true deltas are provably noise-invariant, and
  `bench.report --check` fails on any drift).
- Citation-fidelity probe (`python -m bench.citation_probe --model
  NAME`): per-model rates for parsed citations, explicit none,
  even-spread fallback, think-block emission, reflection-QA JSON
  validity, and the dangerous cell local mode cannot have:
  answers that read as an action while citing nothing, so the
  environment acts and selection has nobody to charge.
- Measured citation-fidelity matrix in
  docs/integrations/hermes.md (llama3.2, hermes3:8b, qwen3:30b-a3b,
  Hermes 4.3 36B): SOURCES-line emission, citation vs explicit-none vs
  fallback rates, think-block handling verified live, and the
  unattributed-action hazard (an answer that reads as an action while
  citing nothing: the environment acts, selection has nobody to
  charge). Plus the first measured LLM-mode survival results: with
  llama3.2 the actionable poison dies at cycle 14 in 3/3 seeds (cycle
  0 in local mode): citation dilution slows selection by an order of
  magnitude, it does not break it.

### Changed

- `bench.report --check`'s poison-kill gate now exempts noisy runs:
  under measurement noise a delayed or missed kill is an honest result
  the suite exists to measure, not a CI failure.
- `random_matched` and `survival_writes` refuse flake overrides loudly
  (the shadow schedule would come from a noise-free world; experience
  writes select on reported deltas and embed detail strings that name
  the true delta).
- Trove classifier moved from `3 - Alpha` to `4 - Beta`: the README
  has called the Ledger the production shape since 0.2.0 and the
  dogfood deployment runs it on this repo; the metadata now agrees.

### Fixed

- xhigh review findings: every EVM transport failure (DNS, refused,
  TLS, read timeout) now surfaces as `EvmRpcError` instead of a bare
  socket exception; `eth_call` empty return data (`"0x"`, the
  no-contract-code case) reads as a measurement failure instead of a
  Python `ValueError`; `tx_cost` guards a null transaction body. New
  `Ledger.add`/`Ledger.forget` put entry writes and burials on the
  event log and enforce escrow at the invariant's home (`forget`
  returns buried/escrowed/missing); the CLI routes through them,
  validates non-empty add, and keys all three decide fields on
  provenance so consumers never see a ticket without an answer.
- `OllamaClient` caps generation (`max_tokens=1024`, mapped to
  `num_predict`), matching the Anthropic and OpenAI-compat clients.
  Previously unbounded: a small model that loses the plot at
  temperature 0 (observed live: llama3.2 drifting into generating
  Python code on a reflection-QA extraction prompt) generated until
  the context window filled, presenting as an inexplicable timeout
  instead of a bad, parseable answer.
- `parse_json_array` strips `<think>...</think>` reasoning blocks
  before extracting, so hybrid-reasoning models can drive the
  reflection-QA encoder: measured on qwen3:30b-a3b, encoding validity
  went from 0/6 valid calls to 5/6 (a stray bracket in the reasoning poisoned
  the greedy array match into garbage). One shared `THINK_RE` in
  `llm.py` now serves both citation parsing and JSON extraction.

## [0.4.0] - 2026-06-11

A max-effort review pass surfaced 15 correctness findings plus a
cleanup list; every finding was treated. The Ledger path is the big
one: its central promise now holds across process boundaries.

### Fixed

- Ledger persistence: `Ledger.save`/`Ledger.load` write one file
  carrying the store AND the ledger state (pending tickets, tick
  count, history), forward and backward compatible with plain store
  files. The MCP server uses it, so a ticket opened today settles
  correctly from tomorrow's process. Previously every cross-process or
  cross-restart settlement silently did nothing.
- Escrow integrity: settling one ticket no longer buries entries still
  escrowed by OTHER pending tickets; a verdict can never arrive after
  the execution, per ticket.
- `settle` returns whether the settlement landed, and the MCP
  `memory_settle` reply says plainly when it did not. New `abandon`
  (and `memory_abandon`) releases no-act tickets instead of pinning
  their entries until expiry.
- Citation parsing takes the LAST `SOURCES:` line per the contract
  (earlier prose or an echoed instruction no longer shadows it), and
  an explicit `SOURCES: none` attaches no provenance instead of
  attributing every consulted entry.
- Encode-time dedup merges provenance across documents instead of
  dropping the second document's sources, which previously could
  mislabel shared facts as purely poisoned (or hide poison as trusted).
- `decision_polarity` matches markers on word boundaries with a
  negation guard: "keep iterating", "unprotected", and "not safe to
  cancel" no longer misread.
- Ollama failures raise `OllamaError` carrying the server's own
  message instead of masquerading as memory silence; embedders never
  return or cache empty vectors (which would have permanently muted
  entries through persisted caches); model-missing 404s stop falling
  back to the legacy endpoint with a worse error.
- Silence accounting keys on provenance, so it works in LLM mode where
  models always produce prose; the degenerate-run health warning uses
  gross outcome movement, not net-zero float equality.
- Experience writes now work for multi-citation LLM answers (the first
  cited entry stands in as parent).
- All persistence is atomic (temp file + rename): a crash mid-write
  can no longer destroy the memory file.
- The `[mcp]` extra floor is `mcp>=1.10`, verified empirically as the
  oldest release with the `instructions` parameter and the structured
  `call_tool` return.
- Obituary cause-of-death is tracked structurally (no spoofable string
  matching), and `python -c "import darwin_memo.__main__"` no longer
  runs the CLI.
- Bench: the paraphrase trust check requires fully-trusted sources, so
  consolidation can no longer launder poison past the metric (the
  survival_writes paraphrase-grounded score honestly drops to 0.00);
  random_matched shadow runs apply resource_scale overrides and are
  memoized; survival_embedding rejects the inapplicable min_coverage
  override loudly.

### Changed

- One shared `assign_credit` rule used by the loop, the Ledger, and
  the examples; `resource_scale` lives on `SurvivalConfig`.
- The canonical demo corpus ships as package data, read by the CLI,
  the examples, and the benchmarks (one copy, no drift); shared
  `death_cause` classifier; five benchmark baselines share one driver;
  `OllamaEmbedder.batch` plus `EmbeddingRetriever.warm` batch
  first-query embedding.

## [0.3.0] - 2026-06-11

### Added

- Fully local stack through Ollama with zero dependencies:
  `OllamaClient` and `OllamaEmbedder` speak the native localhost API
  over stdlib urllib (current `/api/embed` with legacy fallback), plus
  `ollama_available` for graceful auto-detection and
  `examples/07_local_stack.py`.
- `darwin-memo query --model ollama:NAME` (and `anthropic:NAME`) runs
  the full three-stage protocol from the shell.
- Opt-in `bench --suite llm`: the at-home recipe for the LLM-mode
  benchmark question, survival with a local model answering. Sampled,
  never in CI.
- Citation parsing strips `<think>...</think>` blocks, so
  hybrid-reasoning models (Hermes 4, R1 style) cannot cite from inside
  their thinking.
- Integration guides: OpenClaw (MCP mount today, memory-slot plugin
  planned with measured settlement), Hermes (models via Ollama, Hermes
  Agent via MCP), Animoca Minds (planned spike around a generic EVM
  settler on Base RPC). Roadmap issues #1, #2, #3.

## [0.2.0] - 2026-06-11

### Added

- `Ledger`: event-driven decide/settle/tick API for real-world outcome
  timing. Escrow holds entries with unsettled tickets out of burial and
  consolidation, unsettled tickets expire at delta zero, every event
  appends to an optional JSONL log, and `obituary(entry_id)` answers
  why an entry died from its credit history.
- `darwin-memo` CLI: `demo` (self-contained poison extinction, one
  command after pip install), `encode`, `query`, `stats`.
- MCP server (`darwin-memo-mcp`, `[mcp]` extra): `memory_query` opens a
  ledger ticket, `memory_settle` reports the measured delta later, plus
  `memory_add`, `memory_tick`, `memory_stats`, `memory_obituary`. State
  persists across sessions.
- Citation-based attribution in LLM mode: memory snippets are numbered,
  the model cites which it used, and credit flows to the cited entries
  (even spread over everything consulted is the fallback).
- `decision_polarity` accepts `extra_positive`/`extra_negative` marker
  vocabulary for environments whose actions are not delete/apply.
- Silence diagnostics: per-cycle silent-task counts in `CycleStats` and
  the report summary, plus a plain-language health warning naming the
  two degenerate-run failure modes.
- Benchmarks: `evict_on_negative` (the one-line heuristic; it ties the
  ledger on outcomes in the deterministic environment and the doc says
  so), `survival_embedding` (the loop off the lexical-match path), and
  a paraphrase probe set scored by provenance rather than keywords.
- CI lesson-store integration example and guide
  (`examples/06_ci_lesson_store.py`, docs/integrations/).

### Changed

- README restructured: one-command demo first, an explicit "when to use
  this (and when not)" section, and a guide to the three silent failure
  modes that catch new environments.
- The vocabulary coupling between corpus, environment prompts, and the
  keyword reader is now named plainly in docs/benchmarks.md.
- Demo graveyards no longer label starved poisoned entries as executed.

### Fixed

- `LocalEncoder` dedupes identical QA pairs at encode time, so repeated
  text in a document cannot multiply the population.

## [0.1.0] - 2026-06-11

### Added

- Reflection-QA memory encoding following the MeMo pipeline:
  rule-based `LocalEncoder` (offline) and LLM-driven `ReflectionEncoder`
  (fact extraction, consolidation, self-containment verification,
  entity surfacing, cross-document synthesis).
- Three-stage query protocol (grounding, entity identification, answer
  seeking) with honest provenance: a real deciding entry in local mode,
  even credit across consulted entries in LLM mode.
- Survival loop with energy ledger: upkeep per cycle, credit scaled by
  tanh of the real resource delta along provenance, death at zero, and
  Negative-Space consolidation (merge similar survivors, pool energy,
  record lineage).
- Pluggable retrieval: `LexicalRetriever` (smoothed IDF, relevance
  floor, default), `EmbeddingRetriever` over any `text -> list[float]`
  function, and the zero-dependency `HashingEmbedder` (crc32 character
  n-grams). Vectors persist inside `memory.json`.
- Three environments where the reward is a measured conserved resource:
  `StorageEnv` (real bytes on disk), `TestSuiteEnv` (passing tests in a
  generated micro-project), `VerifiableQAEnv` (exact containment).
- Benchmark harness (`bench/`, stdlib-only): survival vs
  keep-everything, TTL, recency, and rate-matched random eviction,
  plus ablations and a scaling probe. Results in docs/benchmarks.md.
- Hypothesis property tests for the ledger invariants and multi-seed
  robustness tests for poison extinction.
- Five offline examples, including an agent tool-use loop with
  credit-back and the test-suite poison extinction demo.
- Optional LoRA distillation script compressing survivors into a small
  parametric memory model, conditioning on questions only.
- Typed package (`py.typed`, mypy strict), ruff lint and format,
  coverage floor in CI across Python 3.10 to 3.14.

[Unreleased]: https://github.com/rogermsc/darwin-memo/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/rogermsc/darwin-memo/compare/v0.5.2...v0.6.0
[0.5.2]: https://github.com/rogermsc/darwin-memo/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/rogermsc/darwin-memo/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/rogermsc/darwin-memo/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/rogermsc/darwin-memo/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/rogermsc/darwin-memo/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/rogermsc/darwin-memo/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/rogermsc/darwin-memo/releases/tag/v0.1.0
