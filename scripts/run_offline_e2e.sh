#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLE_ROOT="${PLE_ROOT:-$HOME/repos/ple}"
OUTPUT="${1:-$HOME/ple-offline-runs/$(date +%s)}"
export PYTHONPATH="$PLE_ROOT${PYTHONPATH:+:$PYTHONPATH}"
cd "$PLE_ROOT"
uv run python "$ROOT/scripts/offline_e2e.py" --output "$OUTPUT"
