#!/usr/bin/env bash
# Credentials are inherited only; the kit owns runtime credential transport.
set -euo pipefail
set +x
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLE_ROOT="${PLE_ROOT:-$HOME/repos/ple}"
if [[ $# -ne 1 ]]; then
  printf 'Usage: %s NEW_OR_EMPTY_RUN_DIRECTORY\n' "$0" >&2
  exit 2
fi
: "${HF_TOKEN:?Export HF_TOKEN with gated dataset read access}"
: "${MODEL_PROXY_URL:?Export MODEL_PROXY_URL for the declared google-cloud model}"
: "${MODEL_PROXY_KEY:?Export MODEL_PROXY_KEY for the declared google-cloud model}"
if [[ -n "${JUDGE_BASE_URL:-}" && -z "${JUDGE_API_KEY:-}" ]] ||
   [[ -z "${JUDGE_BASE_URL:-}" && -n "${JUDGE_API_KEY:-}" ]]; then
  printf 'Set both JUDGE_BASE_URL and JUDGE_API_KEY, or neither (use model proxy).\n' >&2
  exit 2
fi
TRIALS="${DEV_TRIALS:-1}"
if [[ ! "$TRIALS" =~ ^[1-9][0-9]*$ ]]; then
  printf 'DEV_TRIALS must be a positive integer.\n' >&2
  exit 2
fi
OUT="$(realpath -m "$1")"
ARGS=("$ROOT" --trials "$TRIALS" --out "$OUT")
if [[ -n "${DEV_TASKS:-}" ]]; then
  ARGS+=(--tasks "$DEV_TASKS")
fi
cd "$PLE_ROOT"
uv run python eval/run.py "${ARGS[@]}"
# Default eval export writes ROOT/artifacts; validate without altering it.
uv run python -m kit artifacts "$ROOT"
