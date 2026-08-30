#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 AWAREVLN_ROOT MODEL_PATH [DEVICE] [SERVER_ARGS...]" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "${script_dir}/.." && pwd)"
if [[ ! -d "$1" ]]; then
  echo "AwareVLN source directory does not exist: $1" >&2
  exit 2
fi
if [[ ! -d "$2" ]]; then
  echo "AwareVLN checkpoint directory does not exist: $2" >&2
  exit 2
fi
awarevln_root="$(cd "$1" && pwd)"
model_path="$(cd "$2" && pwd)"
device="${3:-cuda:0}"
if [[ $# -ge 3 ]]; then
  shift 3
else
  shift 2
fi

if [[ ! -f "${awarevln_root}/llava/model/builder.py" ]]; then
  echo "Invalid AwareVLN source tree: ${awarevln_root}" >&2
  exit 2
fi
if [[ ! -f "${model_path}/config.json" ]]; then
  echo "Invalid AwareVLN checkpoint: ${model_path}" >&2
  exit 2
fi

cd "$awarevln_root"
export PYTHONPATH="${awarevln_root}:${project_root}/server${PYTHONPATH:+:${PYTHONPATH}}"
exec python -m awarevln.http_realworld_server \
  --awarevln_root "$awarevln_root" \
  --model_path "$model_path" \
  --device "$device" \
  "$@"
