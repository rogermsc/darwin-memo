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
  `adversary.json`, `salience.json`, `neighbours.json`, `distill.json`,
  `distill_merge.json`, `distill_noisy.json`, `distill_rule.json`,
  `judge-llama.json`, `judge-qwen.json`,
  `llm-llama.json`, `llm-qwen.json`, `wef-llama32.json`,
  `wef-llama32-counter.json`.
- The SWE-Bench-CL matrix under `bench/results/swebench_cl/`, one file
  per (arm, sequence, seed) with its own sibling `MANIFEST.json`.
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
| ablation.json              | ablation        | 5     | 95   | 09ced0f7cb0cb77aa7dd266381c48e01d5642f67 |
| adversary.json             | adversary       | 30    | 1050 | 41a1399d9726d3d6f15b78949880a5a4cf5e36b4-dirty |
| bandit.json                | bandit          | 10    | 240  | a5fd4c3940c64a6c961fe021ece07057f6d927bb |
| distill.json               | distill         | 5     | 30   | 8ddc6e22ffb1aaf14e2fe92371548e9af8496014-dirty |
| distill_merge.json         | distill_merge   | 5     | 35   | 118327e1cb1b213664b43c20c33a4fe78c4b0048-dirty |
| distill_noisy.json         | distill_noisy   | 5     | 45   | 0a16f8a041006ed6cfe132dbc1bdba4c5e978b92-dirty |
| distill_rule.json          | distill_rule    | 5     | 30   | 9064ce9b250831241d5279e4898eb280b454133b-dirty |
| headline.json              | headline        | 10    | 80   | 09ced0f7cb0cb77aa7dd266381c48e01d5642f67 |
| judge-llama.json           | judge           | 5     | 10   | a6a60f98ed8fe45c73d8df9018dc60feec0e0a65-dirty |
| judge-qwen.json            | judge           | 5     | 10   | a6a60f98ed8fe45c73d8df9018dc60feec0e0a65-dirty |
| llm-llama.json             | llm             | 5     | 20   | 7a1de5347e8314e3e80a436c26d9de175cae57a5-dirty |
| llm-qwen.json              | llm             | 2     | 2    | 93564dae78cd5a9a9215b8667e6560bc1d535141-dirty |
| memsec.json                | memsec          | 10    | 120  | 22048c9eb433a4c5a2036f2dea46f03d33cf9ae7-dirty |
| neighbours.json            | neighbours      | 10    | 30   | b57fef6a87b1e82371ee86343c56395281c86b4f-dirty |
| noisy.json                 | noisy           | 30    | 2640 | 09ced0f7cb0cb77aa7dd266381c48e01d5642f67 |
| salience.json              | salience        | 10    | 30   | e1407e7d30bdd781a9d72e33c107925327df7eae-dirty |
| testsuite.json             | testsuite       | 10    | 80   | 320c2a687e7f52d53201fd62b130a9657b21308b |
| testsuite_noisy.json       | testsuite_noisy | 30    | 1050 | 320c2a687e7f52d53201fd62b130a9657b21308b |
| wef-llama32.json           | wef             | 3     | 18   | 711bd4ff79c72588bf2ed914285a6ec2bb075481-dirty |
| wef-llama32-counter.json   | wef             | 3     | 9    | 47ea87b80dbc74c3cb50d7cf3a54d8bcc373cc93-dirty |

The `-dirty` suffix is recorded as-is and means the producing tree
carried uncommitted content when the manifest was written, most often
the freshly regenerated results themselves. The named commit brackets
the producing code rather than pinning it exactly; the deterministic
suites carry clean commits.

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

**Four commits in the table above are not in the repository**, so for
these files the "check out the `source_commit`" path does not work:

| file | recorded commit | why |
|---|---|---|
| `bandit.json` | `a5fd4c39…` | generated on a branch that was squash-merged |
| `judge-llama.json` | `a6a60f98…` | same branch |
| `judge-qwen.json` | `a6a60f98…` | same branch |
| `llm-qwen.json` | `93564dae…` | generated on a branch that was squash-merged |

A squash-merge replaces a branch's commits with one new commit and the
branch is then deleted, so a sha recorded during development ceases to
exist once the work lands. Nothing detected this because the manifest
records the sha of the tree that *produced* the file, which cannot know
what sha will later carry it onto `main`. For these four, the `config_hash`
binding and the recorded command still hold and `--check` still verifies
them; what is lost is the exact producing tree. The three sampled-model
files among them (`judge-*`, `llm-qwen`) were never byte-reproducible
anyway — model sampling is not deterministic — so the practical loss is
`bandit.json`, whose suite is deterministic.

The test above fails if a *new* unreachable commit appears, so this list
cannot grow quietly. To avoid adding to it, regenerate result files on
`main` rather than on a branch that will be squashed.

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
