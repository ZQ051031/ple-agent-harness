#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLE_ROOT="${PLE_ROOT:-$HOME/repos/ple}"
cd "$PLE_ROOT"
exec uv run python "$ROOT/scripts/local_model.py" "$@" --ple-root "$PLE_ROOT"
