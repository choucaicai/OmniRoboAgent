# LIBERO

OmniRoboAgent can run the official LIBERO suites through the existing ClawVLA
environment and LeRobot pi0.5 implementation. The integration keeps simulator and
policy details behind the standard `Environment` and `SkillBackend` contracts.

## Current execution path

The atomic configuration uses the full LIBERO language instruction as the active
subtask. `TaskSkillPlanner` proposes it, `LiberoPi05PolicyBackend` predicts a 50-step
action chunk from the agent-view image, wrist image, and 8D robot state, and the
pipeline executes five actions before observing again. Only LIBERO's
`env.check_success()` is treated as benchmark success.

The reported four-suite evaluation applies this direct official-prompt path to all
40 tasks. `SubtaskPlanPlanner` remains available for a separate decomposed
LIBERO-Long experiment, but reliable boundaries for such plans must come from the
official demonstrations or another reviewed trajectory source; the environment
adapter does not invent frame boundaries.

## Run one smoke episode

Use the environment that contains LIBERO, ClawVLA, and LeRobot, then run:

```bash
export CLAWVLA_ROOT=/path/to/clawvla
export LEROBOT_ROOT=/path/to/lerobot
export CLAWVLA_LIBERO_CONFIG="$CLAWVLA_ROOT/configs/libero_pi05_enabled_probe.json"
export LIBERO_PI05_CHECKPOINT=/path/to/libero_pi05_checkpoint
export PALIGEMMA_TOKENIZER=/path/to/paligemma_hf_tokenizer
export PYTHONPATH="$PWD/src:$CLAWVLA_ROOT/src:$LEROBOT_ROOT/src"
export MUJOCO_GL=egl
export PYOPENGL_PLATFORM=egl
export TORCHINDUCTOR_COMPILE_THREADS=1
export TORCHINDUCTOR_CACHE_DIR=/tmp/omni_libero_inductor
python -m omniroboagent.cli run \
  --config configs/runs/libero_spatial_pi05_smoke.yaml
```

The run writes `resolved_config.json`, one row per episode in `episodes.jsonl`, the
aggregate `summary.json`, runtime traces, and observation artifacts below
`runs/libero_spatial_pi05_smoke/`.

`PALIGEMMA_TOKENIZER` must point to a Transformers-readable tokenizer directory
with the same 257,152-token SentencePiece vocabulary as OpenPI. A raw
`paligemma_tokenizer.model` file cannot be passed directly to
`AutoTokenizer.from_pretrained`; it must be converted or replaced with an approved
local Hugging Face tokenizer snapshot.

For a full suite, remove `task_ids`, set `episodes_per_task: 50`, and give the
runtime enough steps for the suite horizon. The evaluator indexes the official fixed
initial-state files; it does not replay training demonstrations.

The completed four-suite result and per-task CSV are available in
[`results.md`](results.md).

## Optional Qwen planner adapter

The inference-only LIBERO planner adapter is packaged at
`checkpoints/libero_qwen35_plan_lora_step500/` using Git LFS. Apply it to
`Qwen/Qwen3.5-9B` for the integrated initial-image-to-subtask-plan path. It is
separate from the reported direct-VLA evaluation: the 95.20% result sends the
official task prompt directly to the LIBERO pi0.5 backend.
