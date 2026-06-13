# Frozen reproduction package

This package reproduces the evidence behind the technical report
(`paper/darwin-memo.md`) for darwin-memo version 0.5.1. The verification
path is offline by default: it checks the committed per-seed result JSON
against the manifest, with no model and no network.

## What is frozen

Committed under `bench/results/`:

- The per-seed raw result JSON for every benchmark arm:
  `headline.json`, `noisy.json`, `ablation.json`, `testsuite.json`,
  `testsuite_noisy.json`, `bandit.json`, `judge-llama.json`,
  `judge-qwen.json`, `llm-llama.json`, `llm-qwen.json`.
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

| file                  | suite           | seeds | runs | source_commit |
|-----------------------|-----------------|-------|------|---------------|
| headline.json         | headline        | 10    | 80   | 09ced0f7cb0cb77aa7dd266381c48e01d5642f67 |
| noisy.json            | noisy           | 30    | 2640 | 09ced0f7cb0cb77aa7dd266381c48e01d5642f67 |
| ablation.json         | ablation        | 5     | 95   | 09ced0f7cb0cb77aa7dd266381c48e01d5642f67 |
| testsuite.json        | testsuite       | 10    | 80   | 320c2a687e7f52d53201fd62b130a9657b21308b |
| testsuite_noisy.json  | testsuite_noisy | 30    | 1050 | 320c2a687e7f52d53201fd62b130a9657b21308b |
| bandit.json           | bandit          | 10    | 240  | a5fd4c3940c64a6c961fe021ece07057f6d927bb |
| judge-llama.json      | judge           | 5     | 10   | a6a60f98ed8fe45c73d8df9018dc60feec0e0a65-dirty |
| judge-qwen.json       | judge           | 5     | 10   | a6a60f98ed8fe45c73d8df9018dc60feec0e0a65-dirty |
| llm-llama.json        | llm             | 5     | 10   | 93564dae78cd5a9a9215b8667e6560bc1d535141-dirty |
| llm-qwen.json         | llm             | 2     | 2    | 93564dae78cd5a9a9215b8667e6560bc1d535141-dirty |

The `-dirty` suffix on the judge and LLM commits is recorded as-is: those
arms were assembled from a working tree that carried uncommitted local
changes, which is honest to flag. The deterministic suites carry clean
commits.

## The exact commands

The one-shot package script does steps 1 to 4 below:

```bash
bash paper/reproduce.sh
```

Run it from the repository root (the directory that contains `bench/`).

### 1. Environment and install

```bash
python3 -m venv .venv-reproduce
source .venv-reproduce/bin/activate
python -m pip install --upgrade pip
# Pinned to the release. The v0.5.1 tag is cut at release time; if it is
# not yet on PyPI, use the byte-exact alternative below.
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
for f in headline noisy ablation testsuite testsuite_noisy \
         bandit judge-llama judge-qwen llm-llama llm-qwen; do
  python -m bench.report "bench/results/$f.json" --check --require-manifest
done
```

Every file prints `PASS: N runs valid`. This is offline: no model, no
network. It confirms the committed evidence still matches the manifest.

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
