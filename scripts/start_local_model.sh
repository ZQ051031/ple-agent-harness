#!/usr/bin/env bash
set -euo pipefail

IMAGE="ghcr.io/ggml-org/llama.cpp@sha256:ae28f5c2046de51dfd00c9116a36fe44b5e8703ef730d0aea69082781eecb1f7"
MODEL_DIR="${MODEL_DIR:-$HOME/models}"
MODEL="Qwen3-8B-Q4_K_M.gguf"
SHA256="d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785"
NAME="${LOCAL_MODEL_CONTAINER:-llama}"
PORT="${LOCAL_MODEL_PORT:-8091}"
mkdir -p "$MODEL_DIR"
if [[ ! -f "$MODEL_DIR/$MODEL" ]]; then
  curl --fail --location --retry 3 \
    "https://huggingface.co/Qwen/Qwen3-8B-GGUF/resolve/main/$MODEL" \
    --output "$MODEL_DIR/$MODEL.part"
  printf '%s  %s\n' "$SHA256" "$MODEL_DIR/$MODEL.part" | sha256sum --check -
  mv "$MODEL_DIR/$MODEL.part" "$MODEL_DIR/$MODEL"
else
  printf '%s  %s\n' "$SHA256" "$MODEL_DIR/$MODEL" | sha256sum --check -
fi
if docker container inspect "$NAME" >/dev/null 2>&1; then
  if [[ "$(docker inspect --format '{{.State.Running}}' "$NAME")" == true ]]; then
    echo "Leaving running container $NAME unchanged."
  else
    echo "Container $NAME exists but is stopped; inspect/remove it before recreating."
    exit 1
  fi
else
  docker run -d --name "$NAME" -p "0.0.0.0:$PORT:8080" \
    -v "$MODEL_DIR:/models:ro" "$IMAGE" \
    -m "/models/$MODEL" --host 0.0.0.0 --port 8080 \
    -c 32768 --jinja -t 8 --parallel 1 --alias qwen3-8b
fi
echo "Local-only endpoint: http://localhost:$PORT/v1 (model qwen3-8b)."
echo "No authentication: use only on a trusted host/network. Startup may take a minute."
