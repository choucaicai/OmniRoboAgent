# LIBERO Qwen3.5-9B planner LoRA

This is the inference-only LoRA adapter from training step 500. It is applied
to `Qwen/Qwen3.5-9B` and generates the ordered LIBERO subtask plan from the
official task instruction and initial camera observations.

- LoRA rank: 64
- LoRA alpha: 128
- Training rows: 160
- Validation rows: 40
- Training step: 500
- Adapter SHA-256:
  `5e49c9eefd40406752e71a1c5474f7c933da0009ebc7ca441b9666fb6f034213`

The adapter was initialized from the RoboTwin full-plan planner LoRA and then
continued on LIBERO planner examples. Tokenizer and processor files are not
duplicated here because the adapter does not add tokens and uses the base
model's processor.

The reported 95.20% direct LIBERO VLA result does not use this planner. This
adapter is packaged for the integrated Qwen-planner execution path. The
training validation accuracy is a plan-label metric, not environment task
success.
