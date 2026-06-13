#!/usr/bin/env bash
#
# Frozen reproduction package for the darwin-memo technical report
# (paper/darwin-memo.md), version 0.5.1.
#
# What this script does, and only this, by default:
#   1. Creates a fresh virtual environment.
#   2. Installs darwin-memo pinned to the v0.5.1 release.
#   3. Verifies every committed result file under bench/results/ against
#      bench/results/MANIFEST.json, OFFLINE. No model, no network.
#   4. Prints which arms can be regenerated deterministically offline and
#      which need a local Ollama server, with the recorded wall times so
#      the cost is known up front.
#
# The verification in step 3 is the reproduction claim for the committed
# evidence: it confirms each per-seed result file still matches the config
# hash and reproduction command the manifest binds it to. This script never
# calls a model or the network. Regenerating the sampled (LLM) arms is a
# separate, opt-in, paid-in-wall-time step and is only printed, never run.
#
# Usage:
#   bash paper/reproduce.sh
#
# Run it from the repository root (the directory that contains bench/).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VENV=".venv-reproduce"
PY="${PYTHON:-python3}"

echo "== darwin-memo report reproduction (offline manifest verification) =="
echo "repository root: $ROOT"
echo

# --- 1 + 2: environment and pinned install ------------------------------
#
# The v0.5.1 tag is cut at release time. If it is not yet on PyPI, install
# from the release commit instead (the alternative, documented below). The
# manifest's per-file source_commit is what actually reproduces the numbers
# byte for byte; see paper/reproduce.md for why the commit, not the wheel,
# is the byte-exact pin.
echo "-- creating $VENV and installing darwin-memo==0.5.1 --"
"$PY" -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --quiet --upgrade pip

if python -m pip install --quiet "darwin-memo==0.5.1"; then
  echo "installed darwin-memo==0.5.1 from PyPI"
else
  echo "darwin-memo==0.5.1 not installable from PyPI in this environment."
  echo "Alternative (byte-exact): check out the release commit and install"
  echo "the working tree:"
  echo "    git checkout v0.5.1   # or the release commit recorded in CHANGELOG"
  echo "    python -m pip install -e ."
  echo "Falling back to the current working tree so verification can proceed."
  python -m pip install --quiet -e .
fi
echo

# --- 3: offline verification of every committed result file -------------
#
# Each file is bound to MANIFEST.json by suite, seeds, config hash, exact
# reproduction command, library version, and producing git commit.
# --check --require-manifest fails if a file has no manifest entry, so a
# deleted binding fails loudly rather than passing silently.
RESULTS=(
  headline.json
  noisy.json
  ablation.json
  testsuite.json
  testsuite_noisy.json
  bandit.json
  judge-llama.json
  judge-qwen.json
  llm-llama.json
  llm-qwen.json
)

echo "-- verifying committed results against MANIFEST.json (offline) --"
fail=0
for f in "${RESULTS[@]}"; do
  path="bench/results/$f"
  if python -m bench.report "$path" --check --require-manifest; then
    :
  else
    echo "FAIL: $path did not validate against the manifest"
    fail=1
  fi
done
echo

if [ "$fail" -ne 0 ]; then
  echo "RESULT: one or more committed result files failed manifest verification."
  exit 1
fi
echo "RESULT: all committed result files match the manifest (offline)."
echo

# --- 4: what is offline-regenerable vs what needs a model ---------------
cat <<'NOTE'
== Regeneration map ==

Deterministic, stdlib-only, regenerable offline (byte-identical metrics
apart from wall times when run from the manifest source_commit):

  headline.json         python -m bench.run --suite headline        --seeds 0:10 --out bench/results/headline.json
  noisy.json            python -m bench.run --suite noisy           --seeds 0:30 --out bench/results/noisy.json
  ablation.json         python -m bench.run --suite ablation        --seeds 0:5  --out bench/results/ablation.json
  testsuite.json        python -m bench.run --suite testsuite       --seeds 0:10 --out bench/results/testsuite.json
  testsuite_noisy.json  python -m bench.run --suite testsuite_noisy --seeds 0:30 --out bench/results/testsuite_noisy.json
  bandit.json           python -m bench.run --suite bandit          --seeds 0:10 --out bench/results/bandit.json

Sampled, NOT byte-reproducible, require a running local Ollama server with
the model pulled (temperature 0 is not a determinism guarantee). Recorded
cost per run is shown so the wall-clock price is known before starting:

  judge-llama.json   suite=judge  model=llama3.2:3b  judge wall ~88 s/run     (5 seeds)
  judge-qwen.json    suite=judge  model=qwen3:4b     judge wall ~1,514 s/run  (5 seeds)
  llm-llama.json     suite=llm    model=llama3.2:3b  ~1,076 s/run, range 926 to 2,055 s   (5 seeds)
  llm-qwen.json      suite=llm    model=qwen3:4b     ~17,182 s/run, range 16,983 to 17,382 s  (2 seeds, partial)

  Recorded Ollama model digests (pin the exact weights):
    llama3.2:3b  a80c4f17acd55265feec403c7aef86be0c25983ab279d83f3bcd3abbcb5b8b72
    qwen3:4b     359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7

  For comparison, the deterministic survival arm settles in ~0.03 to 0.09 s
  per run. The LLM arms are about 12,000x (llama3.2:3b) to 540,000x
  (qwen3:4b) the ledger's per-run wall time. None of these arms ever runs
  in CI. This script does NOT run them; regenerate them yourself only with
  a local model server, knowing the cost above.
NOTE
