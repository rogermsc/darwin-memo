#!/usr/bin/env bash
# Offline central-table reconstruction. No installation or model calls.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
"${PYTHON:-python3}" tools/reconstruct_paper.py
