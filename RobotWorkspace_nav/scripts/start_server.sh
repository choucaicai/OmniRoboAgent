#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 /path/to/latentpilot-checkpoint [cuda_device]" >&2
  exit 2
fi

project_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
checkpoint=$1
device=${2:-cuda:0}

cd "$project_root/server"
exec python -m streamvln.http_realworld_server \
  --model_path "$checkpoint" \
  --device "$device" \
  --num_future_steps 4 \
  --num_frames 32 \
  --num_history 8
