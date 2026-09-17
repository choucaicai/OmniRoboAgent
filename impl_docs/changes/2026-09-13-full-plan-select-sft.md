# Full-plan generation and Omni-style subtask selection SFT

Added an opt-in scheduled mode in which Qwen first generates the complete ordered
plan, including the selected skill, VLA instruction, visible completion condition
and chunk budget for every subtask. Runtime caches that model output. To preserve
the normal Omni planning boundary, a fresh multimodal Planner call is still made
before every subtask; it sees the cached plan, explicit progress, recent history
and current three-camera observation, and must select the current plan item exactly.
The Verifier receives the same plan after every action chunk and predicts
`in_progress` or `completed` from the explicit current chunk and budget.

Replayed all 2486 RoboTwin expert episodes through `SyncRuntime`,
`SkillExecutionPipeline`, `DefaultAgent` and `TieredMemory`. The resulting dataset
contains 2486 full-plan examples, 7645 per-subtask Planner selections and 24897
Verifier examples, for 35028 rows total. It preserves the existing 2236/250
episode-level train/validation split, 54 task/skill-sequence schedule variants,
11 skills and 69939 audited image references. The independent audit verifies plan
identity, one selection per subtask, selection/plan equality, progress continuity,
completion boundaries, split isolation and every image reference; status is PASS.

Added a fresh Qwen3-VL-8B LoRA training config and guarded tmux launcher. The run
uses physical GPUs 4, 6 and 7, FlashAttention 2, DeepSpeed ZeRO-3, rank-64 LoRA,
trainable language/vision/projector targets, and validation every 2000 optimization
steps. It initializes from the original base model and does not load the old
3500-step adapter. Training entered real optimization steps and saved checkpoint
1000 without OOM.

Validation: 21 focused unit tests passed; Ruff and launcher/config syntax checks
passed; full-data audit PASS.
