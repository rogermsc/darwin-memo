# Changelog

All notable changes to this project are documented here. The format
follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project uses [SemVer](https://semver.org/).

## [Unreleased]

### Changed

- **The MemoryOS disclosure was sent** (2026-08-18, `baiting@bupt.edu.cn` — the
  README contact, who is also the paper's senior author). Email rather than
  GitHub because there is no private channel: no `SECURITY.md`, and private
  vulnerability reporting returns `{"enabled": false}`, so a GitHub report would
  have been public by construction. No public issue opened, and none before they
  reply.
  - Three references in the draft were wrong, and re-reading upstream at
    `587ed7755c7a` is what caught them — re-reading the draft would not have.
    The paper is *Memory OS of AI Agent*; the fallback `else` is at
    `updater.py:186`, not `:187`; and `mid_term.py:220` is the session-*merge*
    score in `insert_pages_into_session`, not the retrieval score, which is
    `mid_term.py:330` in `search_sessions`.
  - That last one sharpens Finding 3 instead of weakening it: the constant
    summary and empty keyword list feed the merge decision as well as retrieval,
    so a fenced JSON reply both hides a batch and leaves it liable to be merged
    by a similarity it did not earn. `docs/benchmarks.md` stated the formula
    without a line number and was correct as written; only the unsent draft was
    wrong.

- **A retired number survived in a fourth file for four days.** The 2026-08-14
  review found that MPBench's "63.6% / 31.6%" detector means are not in MPBench
  and cannot be reproduced from it, and corrected the three paper sections and
  the research note it listed. `docs/benchmarks.md:709` still said "the 31.6%
  the literature reports" — it was never on the list. Now cites the printed
  per-detector values (PromptArmor 42.50%, DataFilter 10.74% on weak-signal),
  re-verified against MPBench Table 4 today.
  - The nearest printed figure to 31.6 in that paper is 31.67%, an *attack
    success rate* on OpenClaw — not a detector's true-positive rate at all.
  - Rule recorded in the review: when retiring a number, let a repo-wide grep
    define the list of files. Writing the list from memory and then grepping
    only those files is what left this one behind.

- **The second SWE-Bench-CL sequence ran, and the paper's one transferring
  result does not replicate.** Ten cells on `sympy` (2 seeds x 3 arms x 2
  budgets, 500 docker-evaluated tasks, 6h19m, ~$70 of gpt-4.1), completing the
  design the paper had abandoned. Every one of the 379 non-empty-patch tasks
  reached the official harness.
  - `django` (published): the counter's benign burial triples under attack,
    2.29-3.00x, while the ledger's barely moves, 1.08-1.43x.
  - `sympy` (new): **the tripling is absent.** Counter 0.96x and 0.93x, ledger
    0.78x and 0.76x. Neither mechanism is meaningfully damaged.
  - The scope condition is visible in the unattacked column and could not have
    been seen from one repository: on `django` the counter buries 6-7 benign
    entries with no adversary present, on `sympy` it buries **26-27**. A curator
    already destroying four times as much benign memory at baseline leaves an
    adversary little headroom. The tripling is a property of a curator that is
    otherwise behaving well.
  - **What survived five worlds**: the counter's burial ratio above the
    ledger's in every one, differences +0.17 to +1.92, exact paired permutation
    p = 0.0625 — the *floor* at five pairs, so unanimity at the limit of what
    five worlds can express, not significance.
  - Abstract, `sec:swebench-attack`, `tab:swebench-attack` (now two-sequence)
    and the statistical-status paragraph all updated to lead with the
    non-replication rather than bury it.

- **The pre-registered sixth world ran, and it reversed the surviving
  ordering.** `sympy` seed 2, six cells / 300 docker-evaluated tasks, every one
  through the official harness (~$44, 3h59m). It was run to move the
  permutation floor from 0.0625 to 0.031 and returned the opposite: the
  counter's burial ratio is 0.79 against the ledger's 0.84, a difference of
  **-0.05**.
  - The count is **5 of 6** paired worlds, not 6 of 6, and the exact paired
    permutation **stays at p = 0.0625**. The reversal is small enough that
    flipping its sign back would *raise* the mean difference, so the test cannot
    reach the floor the sixth world was run to buy — completing the design
    returned a negative answer, not a weaker positive one.
  - Split by repository: `django` +1.17 to +1.92 across three seeds; `sympy`
    +0.18, +0.17, -0.05, mean +0.10, p = 0.50. The ordering is a `django`
    effect that `sympy` neither confirms nor contradicts, and the paper now
    says so in the abstract, `sec:swebench-attack`, the statistical-status
    paragraph and a new limitation.
  - `tab:swebench-attack` sympy rows are now three seeds: counter
    25.7 -> 23.0 (0.89x), ledger 41.7 -> 33.0 (0.79x), `keep_everything`
    0 -> 0. Capability still does not separate (retained 1.000, 1.286, 0.966).
  - The arXiv abstract still claimed the tripling held "on every seed", stale
    since the previous entry; corrected, and it fits the 1920-character field
    at 1916.

### Fixed

- **`paper/reproduce.md` still described the abandoned second sequence.** It
  said two `swebench_cl_adversary` cells "enter no analysis" and that "no number
  in the paper reads them" — false since their unattacked twins ran in the
  previous entry, and provably so: hide either one and the new `sympy` ledger row
  fails. Its manifest counts were stale too (20 adversary cells and 80 entries;
  the real figures are 36 and 96). The paragraph now points at the test that
  keeps it honest instead of asserting the state by hand.

- **The paper's central real-task table had no evidence test.**
  `tests/test_paper_tables_match_evidence.py` covered eight tables and not
  `tab:swebench-attack` — the one carrying the attack result — so its numbers
  were hand-transcribed from a tool's printed output twice (when `sympy` landed,
  and again for the sixth world) with nothing comparing them to the runs. Six
  rows are now checked against `bench/swebench_cl/attack.py` itself: both burial
  means, the ratio, capability retained, and the paired-world count, which
  catches a cell that did not run. Coverage is 98 checks over 254 printed
  numbers, up from 92 over 232.
  - The ratio is a mean of *per-world* ratios, not a ratio of the printed means:
    `django` is 2.76 one way and 2.74 the other. Every other row agrees to 2dp,
    so the wrong definition would have passed silently.
  - `data_rows` could not parse a `\multirow` whose group name carries markup
    (`{\texttt{django}}`), because the body pattern stopped at the inner brace.
    It dropped the group and shifted every cell of the table one column left —
    the same defect its own docstring records for `tab:memsec`. No committed
    table was affected; this one is the first with a marked-up group name.

- **A run can complete with the evaluation harness absent, and look fine.**
  `DockerExecutor.evaluate` returns before touching `swebench` when the model
  produces an empty patch — and the paper reports that roughly forty percent of
  SWE-Bench tasks produce no test movement — so a whole matrix can be written
  with plausible rows and no harness installed. That is how it presented: a
  one-task smoke run drew an empty-patch task, reported
  `eval_executed: true`, and the missing dependency surfaced only when a later
  task produced a real patch. Added `DockerExecutor.preflight()`, called on the
  path that needs the harness, and changed that branch's note from "evaluated as
  base behavior" to "base behavior assumed (harness not called)" — the wording
  the stub executor has always used for identical behaviour. `eval_executed`
  itself stays True, because `delta_from_eval` reads it and the settled delta is
  0.0 either way; no committed number changes.
- **`swebench` was unpinned, and the current release cannot run this harness.**
  The executor passes `--namespace` and `--cache_level`; **swebench 5.0.0 accepts
  neither** and exits `unrecognized arguments`, so `pip install swebench` today
  reproduces nothing. 4.0.4 and 3.0.15 work, 2.1.8 lacks `--namespace`.
  `paper/reproduce.md` now says `pip install 'swebench>=3,<5'` and explains why
  the bound is load-bearing.
- **The recorded reproduction command did not reproduce the run, for all 80
  SWE-Bench-CL cells — found by running it.** `reproduce.md` points readers at
  each manifest entry's `command`, and `manifest_failures` only ever checked that
  the field was non-empty. The stored string omitted `--code-context-chars`,
  `--base-url` and `--model`, all of which default to something else, so the
  documented command describes a **blind prompt against a local llama3.2** where
  the cells were produced with **300,000 characters of BM25 code context and
  gpt-4.1**. A one-task smoke run issued exactly the recorded command and
  returned a **1,244-character** prompt against the committed mean of **279,643**.
  - Each run's own `config` had recorded the truth all along
    (`code_context_chars`, `endpoint.base_url`, `endpoint.model`, the retrieved
    file list), so all 80 commands were reconstructed from the runs and carry a
    `command_note` saying so. `--code-max-files` is the paper's documented cap of
    10, which is also the maximum any task in these matrices retrieved.
  - `bench/swebench_cl/run.py` now emits every run-shaping flag, and
    `tests/test_manifest_command_reproduces.py` fails when a stored command
    disagrees with the config of the run it claims to reproduce (160 checks).
  - Verified end to end: the repaired command yields a **301,956-character**
    prompt with 8-file retrieval on `sympy__sympy-12096`, against 1,244 before.
  - First reconstruction pass derived `--code-max-files` from one cell's observed
    file count, which is a floor rather than the setting; 32 cells then failed
    their own new guard, which is what caught it.

- **Two claims about MemoryOS's JSON handling were wrong, found by reading the
  upstream source while drafting the maintainer disclosure.** The paper said
  MemoryOS "parses several LLM replies with a bare `json.loads`" and "silently
  substitutes a generic session summary". There is **one** such call
  (`utils.py:259`) and it **prints a warning**. Every code claim is now verified
  line by line against upstream `587ed7755c7a` and cited by file and line, and
  the substance turns out sharper than what was written: on `JSONDecodeError`
  the updater files the whole batch as one session under a constant summary
  *with an empty keyword list*, and retrieval scores `semantic_sim +
  keyword_alpha * s_topic_keywords`, so both retrieval terms degrade at once.
  Corrected in `sec:memoryos` and `docs/benchmarks.md`. Third instance in this
  repo of a claim reaching the paper through something other than the source.

### Added

- **`docs/disclosure/2026-08-17-memoryos.md` — a coordinated-disclosure draft to
  BAI-LAB, written and NOT sent.** Contacting a third party about their software
  is the author's call; this exists so the text is reviewable and consistent with
  the paper first. Covers the three findings (cheap heat-triggered promotion, a
  single retrieval conferring eviction immunity, fenced JSON collapsing topic
  structure), names what we did *not* demonstrate, and states which of our own
  claims we had to correct.
- **The paper's first figure, generated from committed evidence.** `bench/figures.py`
  (stdlib only) emits `paper/figures/adversary.tex` from `adversary.json`;
  `--check` runs in CI and fails if the two disagree, because a hand-plotted
  curve would be a number in the paper that does not trace to the data. Two
  panels — benign capability and poison-kill rate against attack budget — because
  the result requires reading both: `keep_everything` traces a flat 1.00 on one
  and a flat 0.00 on the other, and either panel alone hides that. Four tests,
  mutation-tested; one of them cross-checks the figure against `tab:adversary`
  so the two views of one file cannot drift apart.
  - The cross-check's first stated mutation was one it provably cannot catch
    (`evict_on_negative` k=1 vs k=3 have identical benign columns). Verified with
    an isolating mutation instead, and the docstring now says which mutations
    distinguish it and why the other does not.

### Changed

- **The in-PDF abstract is 674 words -> 408.** arXiv caps only the metadata field
  (handled separately in `paper/abstract-arxiv.txt`), so this is an editorial cut
  rather than a fix: the real-task result is stated once instead of twice and the
  literature framing is compressed. Deliberately not cut further — going below
  ~350 would mean dropping the persistence result, the published failure
  boundary, or the honest-scope paragraph, which are the paper's distinguishing
  features rather than padding.

- **The paper's strongest claim about itself is now checked for every table, not
  one.** `paper/reproduce.md` says "No number in the report was produced outside
  this committed evidence", and only `tab:headline` enforced it. The other eight
  tables are now recomputed from committed per-seed JSON in CI
  (`tests/test_paper_tables_match_evidence.py`): 92 checks covering 232 printed
  numbers across the noise grid, the adversary grid, persistence, memsec, the
  Write-Execute-Forget table and both SWE-Bench-CL matrices.
  **The audit found the paper correct in every cell** — this is a guard on a true
  claim, not a fix. Each table is mutation-tested (edit one digit, exactly one
  test fails) and each has a parse guard, without which a reformatted table would
  parametrise zero cases and pass green.
  - The reason the old file gave for not generalising — "a fragile parser that
    fails on reformatting would be worse than none" — was right about its own
    positional parser, which misaligned the moment a column was inserted in #65.
    Keying on the table's own header removes that failure mode.
  - **Design rule, learned the hard way three times in one afternoon: group by
    the complete run identity and treat ambiguity as an error.** `noisy.json`
    carries `resource_scale` and `adversary.json` carries `strikes`, so a subset
    key silently averages two cells into a number that appears in no table and no
    run. That produced a phantom 840-value "drift", two phantom `tab:noise`
    mismatches, and a wrong claim that all 21 manifest commits resolved. `pick()`
    now asserts exactly one match; both ambiguity cases are covered by tests.
  - `tab:wef` was nearly excluded as "not a deterministic function of committed
    data" because a local model sampled its answers. That confuses *reproducing*
    a run with *reading* one — the run happened and its per-seed metrics are
    committed. Checked instead of assumed. The only column not covered anywhere
    is its `kill`, whose cell is a hand-written range (`1--3`, `starve 19`), and
    that omission is stated in `reproduce.md` rather than left silent.
  - The coverage figures quoted in `reproduce.md` are themselves derived by a
    test. Both were wrong when first written — invented from a mental tally
    instead of counted, while writing the file whose entire purpose is catching
    exactly that.

- **`paper/abstract-arxiv.txt`, because the paper could not have been
  submitted.** arXiv's metadata instructions state that "abstracts longer than
  1920 characters will not be accepted"
  ([prep.html](https://info.arxiv.org/help/prep.html)). The paper's abstract is
  **4,145 characters** — 2.16x a hard limit enforced by the submission form.
  The limit applies to the metadata field and not to the PDF, so the fix is not
  to cut the author's prose: it is that the form's copy is a *different artifact*
  which has to exist and stay correct. This one is 1,885 characters as the form
  receives it (arXiv strips newlines not followed by whitespace, so the count is
  taken after flattening — counting the raw file over-counts by a character per
  line and could reject a submittable abstract).
  `tests/test_arxiv_metadata.py` enforces the four rules the form applies and
  that would otherwise be discovered at submission time: the length cap, no TeX
  macros, no unicode, no leading "Abstract". Mutation-tested by pasting the PDF's
  abstract in, which fails on length *and* on `\emph`/`$math$`.

### Fixed

- **The provenance fix in #65 was scoped to 21 of 101 manifest entries.** Three
  sibling manifests under `swebench_cl/`, `swebench_cl_long/` and
  `swebench_cl_adversary/` carry the real-task leg — 80 entries, every
  docker-evaluated task in the paper — and CI validates those result files by
  the same glob it uses for the root ones. The `source_commit` guards were
  parametrised over the root manifest alone, so all 80 went unchecked, and
  **all 80 named a pre-squash branch commit absent from published history.**
  Repo-wide the count is 98 of 101. Three defects had to line up for that to go
  unnoticed: the guard asked a question that passes against the local object
  store, it never executed in CI (`fetch-depth: 1`), and it was pointed at a
  fifth of the evidence. All three are now closed; the guards walk every
  manifest under `bench/results/` and cover 101 entries (205 tests, was 45).
- `test_manifest_source_commit_could_have_produced_the_file` now derives the
  runner from the entry's own `command` rather than assuming `bench.run`, so it
  checks the SWE-Bench-CL cells too — previously they fell through its
  `driven_elsewhere` branch and asserted nothing. Mutation-tested both ways: a
  fabricated sha and a *published* commit predating the runner each fail, and
  the second fails only the could-have-produced guard.
- **`sec:swebench-attack` understated what the abandoned second sequence
  produced.** It said the `sympy` and `sphinx` attempts "neither completed".
  In fact two `sympy` cells completed in full and are committed —
  `memory_on` seeds 0 and 1 under attack, 50 docker-evaluated tasks each,
  13 and 12 resolved. What never completed is what the paired design needs:
  their *unattacked twins*, which carry the seeded poison and so cannot be
  substituted by the `swebench_cl_long/` `sympy` cells (different
  `config_hash`; the command differs by `--seed-poison`), plus the third seed
  and the other two arms. Ten of twelve cells are still missing. The paper now
  says this precisely and `paper/reproduce.md` documents the two orphan cells,
  which no number reads and which are kept rather than deleted so the gap stays
  visible.

- **Audited every poison claim in the paper on the provenance metric, after
  the same metric flattered a mechanism twice.** #64 corrected the persistence
  suite; this audit asks the same question of the other five deterministic
  suites and the headline table, which nobody had. All six re-run byte-identical
  on their pre-existing keys, so nothing about the mechanism changes — but the
  metric was missing from the committed evidence of **15 of 21 result files**,
  because `bench/report.py`'s required-key set never asked for it. Findings:
  - **The headline table's "honest tie" is not a tie on completeness.** At the
    same configuration `evict_on_negative` matches the ledger on outcomes
    (+12.78 vs +12.59M) *and* on kill rate (1.00 each) while ending every seed
    holding **two poisoned entries it never starves**, against none for the
    ledger. This correction runs in our favour, which is why the pattern is now
    stated as a threat to validity rather than filed as three separate bugs.
  - **The adversary grid is more one-sided by provenance than by capability.**
    The ledger ends with 0.00 poisoned entries at b ≤ 2 and 1.00 at b = 8; no
    other arm ever ends below 2.00 at *any* budget including zero. At b = 8,
    where we concede the ledger has fallen, it still holds a third of what the
    retention-based arms hold.
  - **The two poison metrics rank `salience_matched` and `random_matched` in
    opposite orders** (0.8 vs 1.1 alive; 0.20 vs 0.80 kill). Salience preserves
    specifically the poison that gets consulted, which is the one that acts —
    the sharpest available argument for always printing both.
  - **`sec:memsec` was already clean**: `tab:memsec` reports `alive@30` and
    `starve`, both provenance metrics, and has no kill column. The
    second-environment and noise legs scope their claims to *actionable* poison
    explicitly. So one defect, one over-claim, and no reversals.
  - **Axis 6's completeness claim was over-general.** "The ledger is the only
    arm that ends with no poisoned entry alive" is false as written — `ttl` also
    ends with zero, by emptying the store (benign 0.00) — and it does not
    survive either attack leg. Now scoped to unattacked runs and to arms that
    retain capability, with both exceptions named.
- **The reproduction package's central instruction did not work for 18 of 21
  result files, and the guard that was supposed to catch it had been asking the
  wrong question.** `paper/reproduce.md` prescribes "check out each file's
  manifest `source_commit`" as the byte-exact path. The guard asked
  `git cat-file -e`, which passes for any object in the **local** store —
  and a pre-squash branch commit survives indefinitely in the clone of whoever
  generated the file. On that check exactly four entries looked broken and the
  package declared them as a known limit. Asked as *ancestry of published
  history* — the only history a reader has — the real count is **eighteen**:
  essentially every `source_commit` in the repo named a branch commit the
  squash-merge discarded. A validation that can pass for a reason unavailable
  to the reader is not validating what it names. Every entry now records a
  commit in `main` (the landing commit, or for regenerated files the tree they
  were run from) with a `source_commit_note` where that differs from the
  originally recorded sha, and the allow-list is deleted.
- **A `source_commit` can also resolve and still be impossible.** Three entries
  recorded the commit immediately *before* the one that added their suite:
  `adversary.json` named a tree six weeks earlier in which `--suite adversary`
  is not a choice in `bench/run.py`, and `memsec.json` and `wef-llama32.json`
  did the same for theirs. Cause: `_git_commit()` reading `HEAD` while the
  suite was still uncommitted, which `-dirty` was designed to flag and which
  was never followed up (once the sha was even recorded clean). Reachability
  cannot see this class, so
  `test_manifest_source_commit_could_have_produced_the_file` now checks the
  recorded tree exposes the entry's suite.
- **Both manifest guards were skipping in CI**, because `actions/checkout`
  defaults to `fetch-depth: 1` and neither can resolve a commit without
  history. That is why a reachability guard sat green while four entries named
  commits that do not exist. Fixed with `fetch-depth: 0`. This is the second
  guard in this repo found green-while-skipping (the paper build guard needs
  tectonic, which CI does not install), so the rule is now stated in the
  workflow: a guard that cannot run in CI is not a guard.

### Changed

- `bench/report.py` requires `poison_alive_final` and `poison_starve_cycle` in
  committed evidence, and `aggregate()` prints a `poison alive (prov)` column
  beside `kill rate` so the flattering metric can no longer appear alone. The
  two model-backed suites (`judge`, `llm`) are exempted by name — every row is
  an Ollama call, so their evidence cannot be regenerated deterministically —
  and no poison claim in the paper rests on them.
- Regenerated `headline`, `noisy`, `ablation`, `testsuite`, `testsuite_noisy`,
  `adversary`, `salience` and `bandit` results under the current code. Verified
  zero drift on every pre-existing metric key: this adds columns, it does not
  move a number.

- **#63's conclusion was wrong, and wrong in a way this repo had already
  documented.** It read the persistence suite off `poison_killed` alone and
  concluded the regime map's recommendation flips — that for a
  persistence-seeking attacker the one-line heuristic is the better choice.
  `poison_killed` asks whether any surviving poisoned entry *currently advises
  action*. Counted by provenance (`poison_alive_final`, all poison regardless
  of behaviour) the counters never removed it: `evict_on_negative` ends with
  **two poisoned entries alive at every budget including zero**,
  `evict_consecutive` 2.0 → 2.4, and quarantine ends *worse* under attack than
  without one (2.0 → 2.8) as evicted entries return. The unattacked ledger ends
  with none, and under the heaviest attack with 1.0 — **still fewer than any
  counter with no attacker present (2.0; mean difference −1.0, p = 0.0020).**
  A mechanism retaining inert poison indefinitely has nothing left for a
  persistence adversary to take: abstention, not defence.
  The attack on the ledger is real and stands (kill 1.00 → 0.00, p = 0.0039,
  benign capability never moving so the guarantee vanishes silently). What is
  corrected is the conclusion drawn from it: **persistence narrows the ledger's
  advantage from total elimination to partial and costs it the guarantee,
  without reversing the recommendation.** Abstract, `sec:regime` Axis 2a,
  `sec:persistence` and the benchmark docs all updated.
  This is the trap `sec:swebench-attack` already records — *measure poison by
  provenance, treat elimination as a predicate rather than a count* — and it is
  the second time in this project a poison count has flattered a mechanism that
  simply never eliminated anything.

### Added

- Refundability counterfactual on the `persistence` suite: `evict_consecutive`
  (a success wipes the strike count) and `quarantine` (evicted, then restored
  after a cooldown) join `evict_on_negative`, so the arms now span whether a
  blame can be undone while holding the mechanism family fixed. This is what
  showed the flat kill rate to be a measurement artefact rather than a property
  of irreversibility, which was #63's stated-but-untested explanation. The
  three original arms reproduce #63's numbers exactly, which is the determinism
  check that adding arms does not perturb existing worlds.

### Added

- **`persistence` suite: the adversary's *objective* is a new axis, and adding
  it corrects the regime map rather than refining it.** Every adversarial arm
  in this repo spent its budget on destruction — an assumption, not a finding,
  and the MemoryOS result (#61/#62) said it was the wrong one: there the cheap
  attack was making the attacker's own memory permanent, not deleting the
  defender's. `AdversarialStorageEnv` now takes `objective="destroy"|"persist"`;
  `persist` lies **only** when the poison has just done damage, never spending
  a lie on a benign entry it does not need removed. Same channel, same worlds,
  same seeds.
  **The objectives have opposite preferred victims.** Destruction destroys
  `evict_on_negative` (benign 0.00 from budget 1) and leaves survival standing.
  Persistence leaves the counter untouched (kill 1.00 at every budget, p = 1)
  and takes survival's poison-kill guarantee away entirely — **1.00 → 0.10 at
  two lies per cycle, → 0.00 at four, paired permutation p = 0.0039** on 10
  seeds. It is also *quieter*: benign capability never leaves 1.00, so nothing
  moves in the metric an operator watches; only `cum_delta` records it
  (12.59M → −0.66M).
  **The cause is this project's own central mechanism seen from the other
  side.** Bounded credit with earn-back is what lets the ledger forgive a lie
  it did not deserve — and equally what lets a *paid* poison earn its way back
  above the floor. A counter cannot forgive (so destruction ruins it) and
  cannot be refunded (so one uncovered negative is irreversible, and its kill
  is merely *delayed*, median cycle 0 → 8). Forgiveness defends against
  accidental noise and is a liability against a patient adversary; ruthlessness
  is the reverse. Reported as a **correction to the regime map** — for a
  persistence-seeking attacker the one-line heuristic is the better choice.
  Kept in its own suite so `bench/results/adversary.json` stays byte-stable.

### Added

- **`bench.external.memoryos_promotion_e2e`: the promotion attack carried out
  end to end — adversary content reaches MemoryOS's persistent tier for the
  price of three questions.** #61 measured the precondition and said the
  extraction was a model call it had not exercised; this exercises it. A canary
  appears only in the adversary's turn, so a hit in a long-term tier cannot be
  a paraphrase of benign content. Against a `quiet` control that adds the same
  turn and never asks about it, three trials are unanimous: control never
  crosses the threshold (heat 2.0) and never promotes; **three self-queries
  cross it (heat 5.0) and promote 3/3**. The canary lands in long-term user
  knowledge 3/3 and assistant knowledge 2/3; the stored profile was never
  poisoned (that write is gated on the analysis returning ≥30 characters).
  MemoryOS's own log records the promotion.
  **Two disclosures, because the difference between compensating for a model
  quirk and lowering a bar until an attack works is the whole value of the
  result.** (1) MemoryOS parses several LLM replies with a bare `json.loads`
  and silently substitutes a generic session summary on failure; since
  retrieval gates on that summary's embedding, a model that fences its JSON
  costs MemoryOS its topic summaries *and* makes the content beneath
  semantically unfindable — a real availability bug in the target, found
  incidentally, reported, and compensated for at the client boundary because
  left in place it prevents the path under test from being reached at all.
  (2) `force_mid_term_analysis()` would bypass the heat threshold outright and
  is **not** used. No threshold lowered, no MemoryOS decision skipped.

### Added

- **`bench.external.memoryos_lfu_attack`: the threat model finally has a
  deployed target — MemoryOS (EMNLP 2025) — and the result is not the one
  predicted.** Mem0 resisted because its curator is an LLM that can decline,
  and Zep/Letta/Cognee have no automatic signal-driven deletion at all.
  MemoryOS does: `MidTermMemory.evict_lfu` is `min(access_frequency)` and
  nothing else — no model consulted, no text read — with the frequency
  incremented by `search_sessions` on every match. Needs no model and no
  network to attack, so it is deterministic.
  **The predicted attack fails, and that is the finding.** Eviction takes a
  minimum, so the obvious move is to raise the victim's peers until it is
  lowest. `add_session` registers a newcomer at frequency 0 and *then* evicts,
  so every arrival sits at the floor and evicts itself: **a memory retrieved
  even once cannot be removed by capacity pressure at all.**
  What the mechanism does instead is exact — `evicted ⟺ frequency == 0`, with
  **3/3** never-retrieved victims evicted and **0/9** ever-retrieved ones, no
  exceptions. A never-retrieved memory loses to a brand-new arrival that is
  also at 0, because `min` returns the first minimum in insertion order. So
  MemoryOS deletes the memory nobody has asked for yet in preference to the
  one that arrived a moment ago, and one retrieval confers permanent immunity.
  That is the rare-but-critical failure — an emergency contact or allergy note
  is stored once, needed rarely, never consulted between — and it is first
  out. This repo names that cost for its own mechanism and answers it with
  pinning; MemoryOS has no equivalent on this path. Written up as
  `\S sec:memoryos`.
  **And a second curation path that inflation *can* drive, running the other
  way.** When a session's heat crosses `H_PROFILE_UPDATE_THRESHOLD`, MemoryOS
  analyses it and writes what it extracts into **long-term memory** — a tier
  capacity pressure never touches. Heat is
  `N_visit + L_interaction + R_recency`, so the cost is arithmetic: at the
  shipped threshold of 5.0, a single-page session crosses on the **third
  self-query** (3.0 → 4.0 → 5.0). An adversary that gets any content into
  mid-term storage and asks about it three times has the curator launder that
  content into the persistent tier — no delete call, no judge, no further
  writes. Denial of memory is the threat model's usual direction; this is its
  mirror, and it is the cheaper of the two.
  **Not claimed**: an adversary manufacturing the neglect end to end, or the
  promotion's extraction step (a model call, not exercised — what is measured
  is the precondition). What is demonstrated is that neglect kills
  deterministically, the curator selects the neglected, and the promotion
  threshold is three questions away.

### Fixed

- **A claim about a named third-party system, shipped in #59, was wrong — and
  it came through a secondary source.** The ecosystem paragraph said Cognee's
  forget operation "leaves the memory retrievable under a forced probe". That
  came from a blog testing a *conversational* forget request. Cognee's actual
  `cognee/api/v1/forget/forget.py` is, in its own words, "a unified deletion
  command that replaces the separate prune/delete" paths, operating by item, by
  dataset, or across everything — it really deletes. This is the exact failure
  mode the repo documented once before (a detector TPR/FPR pair that reached
  three paper sections through a research note and could not be reproduced from
  the paper it cited), repeated by me a day later.
  All three claims are now read from installed sources instead:
  Graphiti's contradiction path sets `expired_at`/`invalid_at` and returns the
  edge as invalidated (`utils/maintenance/edge_operations.py`), never deleting
  automatically, though explicit `DETACH DELETE` APIs exist for a caller;
  Letta's `summarize_messages_inplace` computes a cutoff from token counts and
  summarises in-context messages, leaving the store intact; Cognee deletes but
  only when a caller invokes it. The paragraph's *conclusion* is unchanged —
  none reaches deletion automatically, by a rule, from a signal — but one of
  its three reasons was false and is now correct.

### Fixed

- **The paper shipped a dangling cross-reference.** `related.tex` referenced
  `\S\ref{sec:threat}`, a label that exists in no `.tex` file, so the built PDF
  carried a literal `??` on page 6. LaTeX reports this as a warning and still
  exits zero, which is why nothing caught it — `paper/reproduce.md` promises
  the paper builds "with no undefined references", and that was prose nobody
  checked. Repointed at `sec:adversary`, which is where the trust boundary is
  actually defined, and `tests/test_paper_builds_clean.py` now builds the paper
  and fails on any undefined `\ref`/`\cite` (and on stray `\todo` markers,
  the other half of the same promise). Mutation-tested.
  That build-based check **skips wherever tectonic is absent, which includes
  CI**, so on its own it would have protected nothing where it mattered. A
  second check recovers labels and refs from the `.tex` sources directly and
  needs no toolchain: it runs on every push in 0.02s and catches the same
  defect. Both are mutation-tested; the static one is the one that guards.

### Added

- **Where the threat model applies in today's ecosystem, checked rather than
  assumed.** After the Mem0 negative, the obvious question is which deployed
  systems have the surface at all. Zep's temporal knowledge graph does not
  delete — an outdated fact has its edge marked invalid and is retained for
  historical queries. Letta evicts from the context window and demotes to
  archival recall rather than removing anything. Cognee exposes a forget
  operation whose observed behaviour leaves the memory retrievable under a
  forced probe. Mem0 deletes, but only through the LLM judgment measured
  declining to. **None performs outcome-driven mechanical deletion**, which is
  what a curation-targeted attack needs. The threat model is therefore
  forward-looking with respect to the deployed ecosystem rather than a
  vulnerability report against shipping software — and the uncomfortable half
  is that darwin-memo is itself exactly such a design, so the paper is warning
  about the class of mechanism it belongs to. In `\S sec:mem0`.

### Changed

- **The Mem0 transfer result now runs three pre-registered phrasing families
  instead of one**, retiring the caveat #57 shipped with. All three are
  declared in `ATTACK_FAMILIES` before the runs and all three are reported —
  trying phrasings until one lands and publishing only that would be fishing.
  They span the axis that matters: polite user-voice `retraction`, claimed
  `authority` with an imperative, and `tool_output` shaped like an automated
  sync report, which is how untrusted content actually reaches an agent.
  Result across all three, three trials each: **`any_family_deleted: false`,
  retention 1.00, text unchanged**. The attack fails on the tool-output shape
  too, which is the one the threat model is really about.
  **New sub-finding, and it corroborates our own memsec result on a system we
  do not control**: the `authority` family is the *least* effective on both
  axes at once — it deletes nothing *and* persists nothing (residue 0/8, all
  trials), because the curator declines to record a bare imperative from a
  claimed authority, while the two quieter families persist in full (8/8).
  Loud beats itself; the weak-signal surface is what gets through. That is the
  split `bench/memsec.py` pre-registered and measured against a reconstructed
  write-time detector, reproduced by Mem0's curator with no detector in the
  loop at all.

### Added

- **`bench.external.mem0_curation_attack`: the curation-targeted attack run
  against Mem0, a memory system this project did not write — and it does not
  transfer.** Every other result in this repo runs on environments and
  mechanisms we built, which is the standing objection to all of them and one
  more seeds cannot answer. Mem0's curator is an LLM emitting
  ADD/UPDATE/DELETE/NONE against existing memories on every write, so the
  threat model applies by construction. Three trials with `glm-5.2` as
  curator: **zero DELETE operations, all eight seeded memories alive with text
  unmodified, identical to control on every measure of damage**
  (`benign_memory_lost_to_attack: 0.0`). What the adversary got instead is the
  inverse of denial of memory — all eight of its utterances persisted, leaving
  the store holding each fact *and* an authoritative-sounding negation of it,
  which is content poisoning and somebody else's literature.
  The boundary is worth more than the transfer would have been: this attack
  presumes a curator that acts *mechanically* on a signal (a strike counter
  cannot decline to count; an energy ledger cannot decline to debit), and an
  LLM curator can decline — it treated an unsupported retraction as a claim to
  record rather than an instruction to obey. Judgment in the curator, which
  this project criticises elsewhere as expensive and gameable, buys a defence
  mechanical curation does not have, and our own mechanism sits at the
  mechanical end. Reported in `\S sec:mem0` as a trade rather than a ranking.
  One system, one curator model, one phrasing family — a negative result from a
  single probe is evidence that *this probe* failed, not that the surface is
  safe. Opt-in, never CI; local embedder and vector index.
  **A second curator locates the boundary properly.** Repeating it with
  `llama3.2:3b` gives the same headline — zero deletions, everything retained —
  for the opposite reason: that curator never curates coherently. It stored one
  benign rule three times and another twice, merged two unrelated facts into a
  single memory, and wrote several of the adversary's imperatives in verbatim,
  ending at 22 memories from 15 inputs. Zero deletions there is *incapacity*,
  not restraint, and the store is already degraded. So the defence is not a
  property of LLM curation as such — which one model would have let us claim —
  but of a curator capable enough to understand the retraction and decline it.
  A weak curator buys neither the defence nor a clean store.

### Fixed

- **A claim I added in #53 overgeneralised, and the correction makes the paper
  stronger.** That text said the pre-registered second-half metric "has a
  shared floor" and that "the leg could not have detected an effect… even had
  one been present". True of the two short **pilot** sequences (`pytest` 19
  tasks, `astropy` 22), where every arm including `memory_off` resolves nothing
  from position 17 on. **Not true of the main matrix**, which is where the null
  actually rests: `django` and `sympy` at 50 tasks per cell, 300 evaluated
  tasks per arm, per-position resolve rates fluctuating across the full length
  with no collapse, and a first-to-second-half change of only −0.03 to −0.11
  for every arm. There the comparison is properly powered and properly
  floored — `memory_off` 0.360, `memory_on` 0.350, `random_matched` 0.350,
  curve difference +0.027 [−0.020, +0.073], p = 0.50. The null is a
  measurement on the long matrix and a non-measurement on the pilot;
  `limitations.tex` and the caveat register now say which is which.

### Changed

- **The query-only retention attack is promoted from a paragraph to a
  contribution** (`\S sec:potentiation`, its own subsection following the
  denial-of-memory result, plus a contribution entry and an abstract
  sentence). It closes a second named-but-unmeasured gap: the long-term memory
  security survey (arXiv:2604.16548) observes that "retention schemes based on
  access frequency or recency may inadvertently keep adversarial entries alive
  while discarding legitimate ones" and stops there. The measurement —
  attacker owns ~13% of store lifetime, 16/16 potentiated cells, 0/32 under
  shipped flat upkeep, with the relative-vs-usage cause isolated by
  counterfactual — was already in the repo but buried in the headline
  discussion where no reader would find it.

### Added

- `tests/test_paper_matches_evidence.py`: the paper's headline table is now
  checked against the committed runs on every push. `paper/reproduce.md`
  claims *"No number in the report was produced outside this committed
  evidence"* — the repo's strongest claim about itself, and nothing enforced
  it, in a project that has already shipped one number that did not trace to
  its source (a detector TPR/FPR pair that reached three sections through a
  research note and could not be reproduced from the paper it cited). The
  guard regenerates the aggregate with the same `bench.report` machinery the
  reproduction instructions use and checks every cum-delta, kill-rate and
  final-population cell of `tab:headline` against it, across both source files
  (`salience_matched` lives in its own suite so `headline.json` stays
  byte-stable). **All 8 rows currently agree exactly** — this codifies a
  property the repo already had rather than fixing a defect. Includes a
  guard-on-the-guard: if the table is restructured so the parser matches
  nothing, that fails loudly instead of passing vacuously. The table's
  *caption* is covered too — "wins over keep/random/recency/ttl/salience are
  all 10/0/0, Holm-adjusted p ≤ 0.014" is a claim the cell checks cannot
  reach, since every printed cell can be right while the claim about them
  goes stale. Each file is tested in the call that produced its printed
  number, because Holm adjusts across the comparisons in one call and merging
  the two grids would change every p. That claim also currently holds exactly
  (0.0137 for the four in `headline.json`, 0.0039 for `salience_matched`).

### Fixed

- **`docs/benchmarks.md` was two legs out of date, in the direction of
  understating what has been measured.** It still titled the SWE-Bench-CL
  section "no results yet" and carried a `pending` in every pre-committed
  cell, while 83 committed run files (3,115 task evaluations, all
  `eval.mode == "docker"`) and the paper reported the outcome; and its
  honest-caveats register still said LLM-mode "has no benchmark arm yet;
  its credit fidelity is covered by unit tests only", in a document that
  contains an LLM-mode results section with committed results for two
  models. A reader following the reproduction doc would have concluded two
  whole legs were unrun. Cells are now filled from the committed JSONs by
  `bench.swebench_cl.curve` — the scorer that owns those definitions — with
  the command shown, so no number was transcribed by hand.
- The four pre-registered SWE-Bench-CL gates are now scored: the three
  plumbing gates pass (upkeep deaths nonzero; injection real and
  near-saturated at 2.68–2.73 lessons/task with every second-half task in
  every memory arm receiving at least one; 3 seeds × 2 sequences) and the
  headline gate fails — `memory_off` leads on resolve rate (0.358 vs
  0.325) and `memory_on` vs `random_matched` is +0.052, p = 0.50.
- **The frozen reproduction package described less evidence than the repo
  ships, and nothing checked it.** `paper/reproduce.md` claims of its
  per-file table: *"This table is generated from `bench/results/MANIFEST.json`
  and the manifest is the authority. If the two ever disagree, the manifest
  wins and this table is stale."* Nothing enforced that, and they had
  drifted — `distill_noisy.json`, `distill_rule.json` and `neighbours.json`
  were committed evidence, validated by CI on every push and cited in
  `docs/benchmarks.md`, while the reproduction package listed neither them
  nor their commits. Anyone freezing the package would have shipped an
  incomplete one. All three are now in the frozen list and the table, and
  `tests/test_reproduce_package.py` turns the prose claim into a check:
  it fails if the manifest gains a result the table omits, if the table
  names one the manifest lacks, or if any commit differs.
- **Four `source_commit`s in the reproduction package are not in the
  repository**, so the document's own prescribed byte-exact path — "check
  out each file's manifest `source_commit`" — cannot work for them
  (`bandit.json`, `judge-llama.json`, `judge-qwen.json`, `llm-qwen.json`).
  The cause is structural: results were generated on a branch, the manifest
  recorded that branch's sha, and the squash-merge that landed them replaced
  it. Three of the four are sampled-model runs that were never byte-reproducible
  anyway; the real loss is `bandit.json`, whose suite is deterministic. Now
  named in the document with the cause and the mitigation (regenerate result
  files on `main`), and a test fails if a new unreachable commit appears so
  the list cannot grow quietly.
- The package header claimed to reproduce the evidence "for darwin-memo
  version 0.5.1". The evidence spans releases — one file was produced after
  `0.6.0` — so there is no single version to install that reproduces
  everything. The header now says so and points at the per-file
  `source_commit` as the binding that matters.

### Added

- **A second, independent bound on the real-task null, from committed data
  and no new runs.** Per sequence position every arm resolves every task in
  positions 1–4 and *nothing* from position 17 on — `memory_off` included.
  The pre-registered second-half-minus-first-half metric therefore has a
  shared floor of zero that no curation policy can improve on, and all five
  arms post a strongly negative curve (−0.535 to −0.606). That is a defect
  in the experimental design rather than a result about memory: the metric
  assumed the second half was winnable. Recorded in `limitations.tex`
  beside the retrieval ceiling, which bounds the same null for an unrelated
  reason.

- `bench.potentiation --sweep`: the query-only retention attack over a 32-cell
  grid — two independent corpora (memsec, 16 entries; TestSuiteEnv, 20 entries,
  different vocabulary and poison) × four upkeeps × both normalisations, ~25s,
  still no model and no seed. It discharges the `n=1` caveat the single-store
  run shipped with, and it corrects two things that run got wrong. **The
  default is safe in every cell**: flat upkeep favours the poison in 0 of 32.
  **The attack is a property of the mechanism, not a fixture**: the attacker
  gains in 16 of 16 potentiated cells, both corpora, all three attack classes.
  But the headline "4 cycles" was an upkeep artefact — the absolute margin runs
  8–10 cycles at upkeep 0.02 and 1 cycle at 0.2, while the *fraction* of the
  starvation horizon holds at 0.11–0.17 throughout. **The durable figure is
  that a query-only adversary owns roughly the last 13% of the store's life**,
  at whatever timescale upkeep sets. The counterfactual is also bounded more
  honestly: `saturating` normalisation does not "remove the margin" as one
  store suggested — it still shows one in 11 of 16 cells, every one of them
  exactly one cycle, tracking `1/horizon`. That is the measurement floor, so
  peak-normalisation is the dominant contributor and not provably the only one.
  Incidentally: on the TestSuiteEnv corpus, potentiation *without* an attacker
  starves the poison 18 cycles **before** the benign entries — potentiation is
  not inherently poison-friendly, and the margin is the adversary's doing.

- `bench.potentiation`: the query-only retention attack on the organic layer's
  Phase 4. `docs/threat-model.md` said a query-only adversary's poison "dies on
  the same schedule as any other unused entry, with no acceleration from its
  being adversarial" — true of the flat upkeep that ships, and false once an
  operator opts into `charge_upkeep(scale=upkeep_scale())`. Earned importance
  is recalls + credit + centrality, and an attacker who never writes and never
  settles drives two of the three: recalls directly, centrality through the
  Hebbian links each recall strengthens. Under a query-only attacker the
  poison outlives every benign entry, against no margin at all under flat
  upkeep and none under potentiation with honest traffic only. *(The
  single-store cycle counts this entry originally quoted were superseded by
  the `--sweep` entry above, which reports the scale-invariant figure; they
  are omitted here rather than left to contradict it.)* The mechanism is
  peak-normalisation — importance is a standing within the live population, so
  inflating your own recall count deflates everyone else's, and the margin is
  taken out of the benign entries' lifetime. Ceiling is exactly 2/3 importance
  (credit is the third the attacker cannot earn), and the margin is identical
  across all three attack classes because this path reads usage, never text.
  Needs no model, no environment and no seed. The mechanism is *measured*, not
  inferred: `--recall-norm saturating` swaps the recall term's denominator (the
  live population's peak for a fixed cap) and changes nothing else, and the
  margin collapses while the horizon holds — with centrality left
  attacker-drivable throughout. So the exploitable property is not that usage
  is a retention signal but that the signal is *relative*, making one entry's
  standing a function of every other entry's traffic. `SaturatingImportance` is
  a measuring instrument wired into nothing, not a proposed fix.
- `bench.swebench_cl.recall`: gold-file recall measurement for the real-task
  leg, needing no model, no docker and no evaluation harness — the question is
  whether the prompt contains the file the gold patch touches, not whether the
  task resolves. Measured over the full pinned pilot: BM25 reaches at least one
  gold file for 0.37 of pytest tasks and 0.45 of astropy tasks at the original
  60k/5 budget, and 0.74 / 0.82 at the 300k/10 budget the pilot ran; the oracle
  control reaches every gold file in every task at both. **9 of the 41 pilot
  tasks never showed the model the file it had to patch** (24 of 41 at the
  original budget) — which bounds the null rather than rescuing it, since the
  remaining 32 tasks still produced no separation. The 0.37 and 0.74 figures
  reproduce independently the recall the paper quotes.
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

- **The organic layer's neighbour ranking was not reproducible across
  processes** — the same bug as `budget_relevance` below, in a second place,
  found by `bench.potentiation` reporting a different margin run to run.
  `BruteForceBackend.search` resolved equal cosines by vector-dict insertion
  order, and `OrganicMemory.sync()` filled that dict from a *set difference*,
  so top-k moved with `PYTHONHASHSEED`; `OrganicMemory.related` then broke its
  own ties on `entry.id`, which is `uuid4().hex[:12]` and random per process.
  Ties are the common case here, not a corner one — an embedder puts unrelated
  entries at cosine 0.0 in bulk — and centrality, earned importance and upkeep
  relief all read that ranking. `sync()` now adds in store order, `search()`
  sorts on the score alone and lets Python's stable sort keep insertion order,
  and `related()` breaks ties on the new `AssociativeGraph.ordinal()` instead
  of the id. No committed bench result changes: nothing in `bench/` wires the
  organic layer into an arm.
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
