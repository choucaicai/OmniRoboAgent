# LIBERO subtask PI0.5 adaptation

## Objective

Adapt the existing LIBERO PI0.5 checkpoint to execute the same atomic subtasks
emitted by the OmniRoboAgent planner, while preserving the official observation,
state, action, and normalization contracts.

## Data

- Source: 1,693 official successful `HuggingFaceVLA/libero` demonstrations.
- Atomic tasks: retain the complete expert trajectory and relabel it with the
  executable instruction used by the planner.
- Composite LIBERO-Long tasks: split at the first sustained grasp's release,
  yielding two subtask episodes without deleting frames.
- Result: 2,031 episodes and 273,465 frames. The source normalization statistics
  remain valid because the observations and actions are unchanged.

## Training

- Base: local `pi05_libero_finetuned_v044` checkpoint.
- Method: rank-64 LoRA on PI0.5's action expert attention and projection targets.
- Schedule: 5,000 updates, effective batch size 3 on three GPUs, checkpoint every
  500 updates, W&B logging enabled.
- Dataset loading: local streaming mode to avoid duplicating the embedded images
  into a second Arrow cache.

## Validation

1. Load the derived metadata and one 50-action training window.
2. Confirm all 338 composite source episodes have a valid semantic cut.
3. Confirm the derived dataset preserves all 273,465 source frames.
4. Confirm a real optimizer step completes before leaving the job unattended.
5. Evaluate the resulting checkpoint with planner-produced subtasks in the four
   official LIBERO suites.
