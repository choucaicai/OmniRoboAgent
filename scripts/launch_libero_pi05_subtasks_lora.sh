#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LEROBOT_ROOT="${LEROBOT_ROOT:?Set LEROBOT_ROOT to the LeRobot checkout}"
PYTHON="${PYTHON:-python}"
DATA_ROOT="${LIBERO_SUBTASK_DATASET:?Set LIBERO_SUBTASK_DATASET}"
BASE_POLICY="${LIBERO_PI05_BASE_CHECKPOINT:?Set LIBERO_PI05_BASE_CHECKPOINT}"
OUTPUT_DIR="${OUTPUT_DIR:-${REPO_ROOT}/runs/train/pi05_libero_subtasks_lora_3gpu_20260915}"
CUDA_DEVICES="${CUDA_DEVICES:-0,2,7}"
NUM_PROCESSES="${NUM_PROCESSES:-3}"
STEPS="${STEPS:-5000}"
MAIN_PORT="${MAIN_PORT:-29915}"

export PYTHONPATH="${LEROBOT_ROOT}/src:${REPO_ROOT}/src:${PYTHONPATH:-}"
export CUDA_VISIBLE_DEVICES="${CUDA_DEVICES}"
export HF_DATASETS_CACHE="${HF_DATASETS_CACHE:-${HOME}/.cache/huggingface/datasets}"
export TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4
export MUJOCO_GL=egl
export WANDB_PROJECT="OmniRoboAgent"
# The cluster proxy is not reachable from every host; W&B is reachable directly.
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy

mkdir -p "$(dirname "${OUTPUT_DIR}")"

LAUNCH_ARGS=(
  --num_processes "${NUM_PROCESSES}"
  --num_machines 1
  --mixed_precision bf16
  --main_process_port "${MAIN_PORT}"
)
if [[ "${NUM_PROCESSES}" -gt 1 ]]; then
  LAUNCH_ARGS+=(--multi_gpu)
fi

exec "${PYTHON}" -m accelerate.commands.launch "${LAUNCH_ARGS[@]}" \
  "${REPO_ROOT}/scripts/train_libero_pi05_subtasks.py" \
  --policy.path="${BASE_POLICY}" \
  --policy.push_to_hub=false \
  --policy.compile_model=false \
  --policy.optimizer_lr=0.0001 \
  --policy.scheduler_warmup_steps=250 \
  --policy.scheduler_decay_steps="${STEPS}" \
  --policy.scheduler_decay_lr=0.00001 \
  --dataset.repo_id=local/libero_subtasks_omni_20260915 \
  --dataset.root="${DATA_ROOT}" \
  --dataset.streaming=true \
  --batch_size=1 \
  --num_workers=2 \
  --steps="${STEPS}" \
  --eval_freq=0 \
  --log_freq=10 \
  --save_checkpoint=true \
  --save_freq=500 \
  --output_dir="${OUTPUT_DIR}" \
  --job_name=pi05_libero_subtasks_lora \
  --peft.method_type=LORA \
  --peft.r=64 \
  --wandb.enable=true \
  --wandb.project=OmniRoboAgent \
  --wandb.disable_artifact=true \
  --wandb.notes="PI0.5 LoRA on official LIBERO expert trajectories relabeled by executable subtask" \
  --seed=1000
