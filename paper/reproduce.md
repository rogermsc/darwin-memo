# Frozen reproduction package

This package reproduces the evidence behind the technical report
(`paper/darwin-memo.md`). The verification path is offline by default: it
checks the committed per-seed result JSON against the manifest, with no
model and no network.

The evidence was **not all produced by one release**. `0.5.1` is the
release the earliest committed suites were cut against, and the package
was originally written around it, but result files have been regenerated
and added since — one (`neighbours.json`) after `0.6.0`. There is
therefore no single version to install that reproduces everything, which
is why the per-file `source_commit` in the manifest is the binding that
matters and the version pin below is a convenience for the offline check
rather than a route to byte-exact numbers.

## What is frozen

Committed under `bench/results/`:

- The per-seed raw result JSON for every benchmark arm:
  `headline.json`, `noisy.json`, `ablation.json`, `testsuite.json`,
  `testsuite_noisy.json`, `bandit.json`, `memsec.json`,
  `adversary.json`, `persistence.json`, `salience.json`,
  `neighbours.json`, `distill.json`,
  `distill_merge.json`, `distill_noisy.json`, `distill_rule.json`,
  `judge-llama.json`, `judge-qwen.json`,
  `llm-llama.json`, `llm-qwen.json`, `wef-llama32.json`,
  `wef-llama32-counter.json`.
- The SWE-Bench-CL matrices, one file per (arm, sequence, seed), each
  directory with its own sibling `MANIFEST.json`: the pilot under
  `bench/results/swebench_cl/` (30 cells), the long matrix under
  `swebench_cl_long/` (30), and the curation-targeted attack under
  `swebench_cl_adversary/` (20). Those 80 entries are validated by CI on
  every push exactly as the root manifest's are, and as of 2026-08-17 by
  the same `source_commit` guards — which had been scoped to the root
  manifest alone, so all 80 went unchecked, and all 80 named a pre-squash
  branch commit absent from published history.

  **Two cells in `swebench_cl_adversary/` enter no analysis, and this is
  the only place that says so.** `memory_on-sympy_sympy_sequence-seed0-b2`
  and `-seed1-b2` are complete, fully docker-evaluated 50-task runs (13
  and 12 resolved). They are the surviving half of the abandoned attempt
  at a second sequence: the paired design needs each attacked cell's
  *unattacked twin*, and a twin here carries the seeded poison, so the
  `sympy` cells in `swebench_cl_long/` are a different configuration and
  cannot stand in for them (their `config_hash` differs, and the command
  differs by `--seed-poison`). Ten of the twelve cells a two-sequence
  result needs are missing. The two files are kept rather than deleted
  because they are real evaluated evidence and deleting them would make
  the gap invisible, but no number in the paper reads them.
- `bench/results/MANIFEST.json`, which binds each result file to its
  suite, seeds, run count, config hash, exact reproduction command,
  library version, and producing git commit (`source_commit`).
- For the two LLM-mode files, the manifest also records the Ollama model
  digest used, so the exact weights are pinned:
  - `llm-llama.json`: `llama3.2:3b` digest
    `a80c4f17acd55265feec403c7aef86be0c25983ab279d83f3bcd3abbcb5b8b72`
  - `llm-qwen.json`: `qwen3:4b` digest
    `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`

The numbers in the report are read from these files and re-derived with
`python -m bench.report`. No number in the report was produced outside this
committed evidence.

## How the manifest binds results to a config hash

Each entry in `MANIFEST.json` carries a `config_hash` (a sha256 over the
suite's full configuration) and the exact command that produced the file.
`python -m bench.report <file> --check` recomputes the file's binding and
fails on any mismatch; `--require-manifest` additionally fails if the file
has no manifest entry at all, so committed evidence cannot drift out of
binding silently. CI runs this check on every committed file on every push.

One subtlety, important for byte-exact reproduction. The environments'
per-cycle seed scheme changed after the 0.4.0 release while the package
`__version__` still read 0.4.0. Reproducing the committed numbers byte for
byte therefore means checking out each file's manifest `source_commit`, not
installing a released wheel. The per-file commits, as recorded in the
manifest at the time this package was frozen:

| file                       | suite           | seeds | runs | source_commit |
|----------------------------|-----------------|-------|------|---------------|
| ablation.json              | ablation        | 5     | 95   | 948870223a2ad897401e28e30550bfa1cfe5971d |
| adversary.json             | adversary       | 30    | 1050 | 948870223a2ad897401e28e30550bfa1cfe5971d |
| bandit.json                | bandit          | 10    | 240  | 948870223a2ad897401e28e30550bfa1cfe5971d |
| distill.json               | distill         | 5     | 30   | a68d2cc2aa2a5ce2a721b1fef27c8ccdc1896b2a |
| distill_merge.json         | distill_merge   | 5     | 35   | a68d2cc2aa2a5ce2a721b1fef27c8ccdc1896b2a |
| distill_noisy.json         | distill_noisy   | 5     | 45   | 112d02595f17b57639620ff45b52e8abb6538d5d |
| distill_rule.json          | distill_rule    | 5     | 30   | 112d02595f17b57639620ff45b52e8abb6538d5d |
| headline.json              | headline        | 10    | 80   | 948870223a2ad897401e28e30550bfa1cfe5971d |
| judge-llama.json           | judge           | 5     | 10   | 519118ea714e9df9ac71843f79e7b12d43538079 |
| judge-qwen.json            | judge           | 5     | 10   | 519118ea714e9df9ac71843f79e7b12d43538079 |
| llm-llama.json             | llm             | 5     | 20   | 9eef3df8758a467cef3a5617634de7969bfbbb3d |
| llm-qwen.json              | llm             | 2     | 2    | 9eef3df8758a467cef3a5617634de7969bfbbb3d |
| memsec.json                | memsec          | 10    | 120  | 948870223a2ad897401e28e30550bfa1cfe5971d |
| neighbours.json            | neighbours      | 10    | 30   | 92433ffb5a7996ed74cbe4aecb404a3ccaf5cd9f |
| noisy.json                 | noisy           | 30    | 2640 | 948870223a2ad897401e28e30550bfa1cfe5971d |
| persistence.json           | persistence     | 10    | 400  | 04959d904667d60ce33ee6dd4a1f2a33d3b561ad |
| salience.json              | salience        | 10    | 30   | 948870223a2ad897401e28e30550bfa1cfe5971d |
| testsuite.json             | testsuite       | 10    | 80   | 948870223a2ad897401e28e30550bfa1cfe5971d |
| testsuite_noisy.json       | testsuite_noisy | 30    | 1050 | 948870223a2ad897401e28e30550bfa1cfe5971d |
| wef-llama32-counter.json   | wef             | 3     | 9    | a1583d78dc90c2abc3e1b11a0a41a620fc60bad8 |
| wef-llama32.json           | wef             | 3     | 18   | a1583d78dc90c2abc3e1b11a0a41a620fc60bad8 |

Every commit in that column is in this repository's published history, so
`git checkout <sha>` works for all of them — as it now does for the 80
entries in the three SWE-Bench-CL sub-manifests, which are not tabulated
here only because 80 rows of one repeated commit would be noise. That was
not true of any of them until 2026-08-17 and the next section is the
accounting.

This table is generated from `bench/results/MANIFEST.json` and the
manifest is the authority. If the two ever disagree, the manifest wins
and this table is stale. That correspondence is now enforced rather than
asserted: `tests/test_reproduce_package.py` fails if the manifest gains a
result this table omits, if this table names one the manifest does not
have, or if any commit here differs from the manifest's. It was not
enforced before, and the two had drifted — `distill_noisy`,
`distill_rule` and `neighbours` were committed evidence, validated by CI
on every push and cited in `docs/benchmarks.md`, while this package
described neither them nor their commits.

### The code pointer was wrong in two ways, and both are now checked

`config_hash` binds a file to its run grid, and that has always been
enforced. `source_commit` binds it to the *code that walked the grid*, and
until now nothing checked it at all. Two failures had accumulated.

**Commits a reader cannot check out — 98 of 101 entries.** Eighteen of the
root manifest's twenty-one, and *all eighty* in the three SWE-Bench-CL
sub-manifests, which the guard was not looking at. A
squash-merge replaces a branch's commits with one new commit and deletes the
branch, so a sha recorded during development ceases to exist in the
published history once the work lands, and the manifest cannot know in
advance what sha will carry it onto `main`. Almost every entry here was
recorded that way.

The reason the damage was understated for so long is the check itself. The
guard asked `git cat-file -e`, which passes for any object in the **local**
object store — and a pre-squash branch commit survives indefinitely in the
clone of whoever generated the file. On that check exactly four entries
looked broken (`bandit.json`, `judge-*.json`, `llm-qwen.json`) and this
document declared them as a known limit. Asked as *ancestry of published
history*, the true count was **eighteen**. The lesson is not about git: a
validation that can pass for a reason unavailable to the reader is not
validating the thing it names.

Every entry in all four manifests now records a commit in published
history — the commit that landed the file, or for the files regenerated in
the provenance-metric audit the tree they were run from — with a
`source_commit_note` wherever that differs from the sha the generator
originally wrote.
`test_manifest_source_commit_is_in_published_history` asks ancestry, carries
no allow-list, walks **every** manifest under `bench/results/` rather than
the root one, and runs in CI (which needed `fetch-depth: 0`, without which
it silently skipped on every push — the reason it never caught any of this).
Three defects had to line up for 98 entries to go unnoticed: the guard asked
a question that passed locally, it never executed in CI, and it was pointed
at 21 of the 101 entries.

**Commits that resolve but could not have produced the file.** Worse than
the above, because it reads as verified provenance. Three entries recorded
the commit immediately *before* the one that added their suite —
`adversary.json` named a tree from six weeks earlier in which `--suite
adversary` is not a choice in `bench/run.py`, and `memsec.json` and
`wef-llama32.json` did the same for their own suites. The cause is
`_git_commit()` reading `HEAD` while the suite's code was still uncommitted
in the working tree; the `-dirty` suffix flags exactly this and says the
commit "brackets the producing code rather than pinning it exactly", with
the instruction to update it at commit time. That follow-up was skipped
three times, and once the sha was recorded clean with no `-dirty` at all.
`test_manifest_source_commit_could_have_produced_the_file` now checks the
recorded tree exposes the suite named in the entry.

To avoid adding to either list: when results land, update the entry to a
commit in `main` — the landing commit if the file is not being regenerated,
or the tree it was run from if it is — and say which in
`source_commit_note`. `_git_commit()` records the generating machine's
`HEAD`, which is a starting point and not the answer.

## The exact commands

The one-shot package script does steps 1 to 4 below:

```bash
bash paper/reproduce.sh
```

Run it from the repository root (the directory that contains `bench/`).

### 1. Environment and install

darwin-memo requires Python 3.10 or newer. `python3` is 3.9 on a stock
macOS and on several LTS distributions; point the script at a newer
interpreter rather than the default:

```bash
PYTHON=python3.12 bash paper/reproduce.sh
```

The script checks this first and says so plainly. Skipping the check
produces a pip resolution error that reads like a broken package instead
of an old interpreter.

```bash
python3 -m venv .venv-reproduce
source .venv-reproduce/bin/activate
python -m pip install --upgrade pip
# Enough to run the offline --check over every committed file. It is NOT
# the tree that produced them all (see the version note at the top), so
# use the per-file source_commit below for byte-exact numbers.
python -m pip install "darwin-memo==0.5.1"
```

Byte-exact alternative (and the only way to reproduce the numbers exactly,
per the seed-scheme note above): check out the relevant `source_commit`
from the table and install the working tree.

```bash
git checkout v0.5.1          # or the source_commit for the file in question
python -m pip install -e .
```

### 2. Offline verification (the reproduction claim)

```bash
for f in bench/results/*.json; do
  [ "$(basename "$f")" = MANIFEST.json ] && continue
  python -m bench.report "$f" --check --require-manifest
done
```

Every file prints `PASS: N runs valid`. This is offline: no model, no
network. It confirms the committed evidence still matches the manifest.

The loop globs rather than naming files on purpose. An earlier version
listed ten of them, and the omitted set turned out to be exactly the two
that could not pass, so the check reported success over evidence it was
not reading. Globbing means a newly committed result file is verified by
default and a broken one fails loudly instead of being left out.

The SWE-Bench-CL cells carry their own manifest in their own directory:

```bash
for f in bench/results/swebench_cl/*.json; do
  [ "$(basename "$f")" = MANIFEST.json ] && continue
  python -m bench.report "$f" --check --require-manifest
done
```

### 3. Re-derive any table

The report's numbers come from these commands (a representative subset; the
full list is in `docs/benchmarks.md` under Reproduce):

```bash
python -m bench.report bench/results/headline.json --tests --fmt md
python -m bench.report bench/results/headline.json --paired survival evict_on_negative --metric cum_delta
python -m bench.report bench/results/noisy.json --paired survival evict_consecutive
python -m bench.report bench/results/testsuite_noisy.json --tests
python -m bench.report bench/results/bandit.json --paired policy_bandit survival
python -m bench.report bench/results/judge-llama.json --paired survival judge_settled
python -m bench.report bench/results/judge-qwen.json  --paired survival judge_settled
python -m bench.report bench/results/llm-llama.json --paired \
  survival_llm:model=llama3.2:3b,refuse=off \
  survival_llm:model=llama3.2:3b,refuse=on --metric cum_delta
```

The seeded bootstrap and permutation tests reproduce byte-identically, so a
rerun of any of these gives the same intervals and p-values.

### 4. Regeneration map

Deterministic, stdlib-only arms regenerate offline and byte-identically
when run from the manifest `source_commit` (`headline`, `noisy`,
`ablation`, `testsuite`, `testsuite_noisy`, `bandit`). The sampled arms
(`judge`, `llm`) require a running local Ollama server with the named model
pulled to the recorded digest, are not byte-reproducible (temperature 0 is
not a determinism guarantee), and never run in CI. Their recorded per-run
wall times, for cost before you start:

| arm        | model        | recorded wall (per run)              |
|------------|--------------|--------------------------------------|
| judge      | llama3.2:3b  | judge step ~88 s                     |
| judge      | qwen3:4b     | judge step ~1,514 s                  |
| llm        | llama3.2:3b  | ~1,076 s (range 926 to 2,055 s)      |
| llm        | qwen3:4b     | ~17,182 s (range 16,983 to 17,382 s) |

For comparison, the deterministic survival arm settles in about 0.03 to
0.09 s per run. `paper/reproduce.sh` prints this map and does NOT run the
sampled arms; regenerate them yourself only with a local model server.

### 5. The SWE-Bench-CL leg (the expensive one)

Unlike everything above, this needs Docker, a frontier-model API key, and
about half a day. It is deliberately not part of `reproduce.sh`, which
stays offline and free. Verifying the committed cells (step 2) is the
reproduction claim; regenerating them is optional.

Prerequisites: a running Docker daemon (the official SWE-bench harness
builds and runs real repository test suites, under `linux/amd64`
emulation on Apple Silicon), `pip install swebench`, and the pinned
dataset:

```bash
python -m bench.swebench_cl.run pin \
  --dataset /path/to/SWE-Bench-CL-Curriculum.json
```

The loader refuses any dataset file whose sha256 differs from the pin in
`bench/swebench_cl/manifests/pilot.json`, so a drifted download fails
rather than quietly producing different numbers.

Then the full matrix, five arms by two sequences by three seeds:

```bash
export SWEBENCH_API_KEY=...
python -m bench.swebench_cl.matrix \
  --manifest bench/swebench_cl/manifests/pilot.json \
  --dataset /path/to/SWE-Bench-CL-Curriculum.json \
  --out-dir bench/results/swebench_cl \
  --executor docker --model gpt-4.1 \
  --base-url https://api.openai.com/v1 \
  --api-key-env SWEBENCH_API_KEY \
  --code-context-chars 300000 --code-max-files 10 --max-tokens 4096
```

Add `--dry-run` first to see the thirty cells and what a resume would
skip. The driver runs each cell as its own subprocess and skips any whose
output file already exists, so an interrupted matrix continues where it
stopped; a failed cell is reported at the end rather than aborting the
rest. Recorded cost at this configuration: roughly 55 s per task, about
20 minutes per pytest cell, on the order of 10 hours and $100 of API for
the whole matrix.

`--code-context-chars` matters more than it looks. At 0 the model never
sees the repository and resolves approximately nothing on every arm; the
committed matrix uses 300000 over 10 files, where BM25 puts the file the
gold patch edits in front of the model on 74% of the pytest sequence
(37% at 60000 over 5). A file the model never sees is a task no arm can
solve, so this figure bounds every arm. The driver refuses 0 outright.

Score the matrix with:

```bash
python -m bench.swebench_cl.curve bench/results/swebench_cl
```

This is sampled, not byte-reproducible: a frontier endpoint at
temperature 0 is not a determinism guarantee, and the resolve rate moves
between identical runs.
