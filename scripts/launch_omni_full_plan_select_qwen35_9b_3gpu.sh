#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

DATASET="$PWD/runs/data/omni_full_plan_select_schedule_sft_2486_20260913"
RUN_DIR="$PWD/runs/sft/qwen35_9b_omni_full_plan_select_3gpu_20260913"
CONFIG="$PWD/configs/sft/omni_full_plan_select_qwen35_9b_3gpu.yaml"
PYTHON="${PYTHON:-python}"
LLAMA_FACTORY_SRC="${LLAMA_FACTORY_SRC:?Set LLAMA_FACTORY_SRC to LLaMA-Factory/src}"
GPU_IDS="${GPU_IDS:-0,1,2}"
NPROC_PER_NODE=3
MASTER_PORT="${MASTER_PORT:-29835}"
TMP_ROOT="${TMP_ROOT:-/tmp/qwen35_omni_full_plan_select_20260913}"

if [[ "$(tr ',' '\n' <<<"$GPU_IDS" | wc -l)" -ne 3 ]]; then
  echo "Exactly three GPU IDs are required: $GPU_IDS" >&2
  exit 2
fi

mkdir -p "$RUN_DIR/cache/tmp" "$TMP_ROOT"
test -x "$PYTHON"
test -d "$LLAMA_FACTORY_SRC"
test -f "$DATASET/audit.json"
test "$(jq -r .status "$DATASET/audit.json")" = PASS
test -f "$DATASET/train.jsonl"
test "$(wc -l < "$DATASET/val_10pct.jsonl")" -eq 352
test -f "$DATASET/dataset_info.json"
test -f "$CONFIG"
export PYTHONPATH="$LLAMA_FACTORY_SRC:$PWD/src:${PYTHONPATH:-}"
export CUDA_VISIBLE_DEVICES="$GPU_IDS"
export FORCE_TORCHRUN=1
export NPROC_PER_NODE MASTER_PORT
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
export TOKENIZERS_PARALLELISM=false
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export CLAWVLA_DISABLE_IMAGE_AUGMENTATION=1 DISABLE_VERSION_CHECK=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_DATASETS_OFFLINE=1
export NO_ALBUMENTATIONS_UPDATE=1
export HF_HOME="$RUN_DIR/cache/huggingface"
export HF_DATASETS_CACHE="$RUN_DIR/cache/datasets"
export TRITON_CACHE_DIR="$RUN_DIR/cache/triton"
export TMPDIR="$TMP_ROOT" RECORD_VRAM=1

cp "$CONFIG" "$RUN_DIR/training_config.yaml"
printf '%s\n' "$GPU_IDS" > "$RUN_DIR/gpu_ids"
printf '%s\n' "fresh_from_base=true" > "$RUN_DIR/initialization.txt"
printf '%s\n' "validation_rows=352" > "$RUN_DIR/validation.txt"
rm -f "$RUN_DIR/exit_code"
trap 'printf "%s\n" "$?" > "$RUN_DIR/exit_code"' EXIT
exec "$PYTHON" -m llamafactory.cli train "$CONFIG" \
  > "$RUN_DIR/train.log" 2>&1
