# RoboTwin subtask integration

Status: in progress (2026-09-11). Upstream: `c97c3d5`.

Implement a minimal extension in OmniRoboAgent. Reuse DefaultAgent,
SkillExecutionPipeline, SubtaskVerifier, TieredMemory and SyncRuntime.

- Add a RoboTwin environment using the existing external ClawVLA simulator
  adapter, without invoking ClawVLA AgentLoop or changing its source.
- Add a client for the resident pi0.5 worker; send the subtask verbatim for
  subtask-trained checkpoints, optionally Task + Skill + Subtask for the
  separately trained Omni-style checkpoint.
- Accept ordered instruction/success_condition plans from JSON or a model.
  Advance only after verification, preserve current subtask on continue/retry,
  and regenerate the remaining plan on recovery when a model is configured.
- Add opt-in fresh observation on uncertain verification and explicit plan
  exhaustion handling. Environment success remains authoritative.
- Provide one-episode config and commands, with CPU limits and tmux. No new
  training or full benchmark run is part of this change.

Acceptance: existing unit tests still pass; new tests cover plan alignment,
target-free subtasks, continue/advance/retry/replan, fresh observation, invalid
actions and plan exhaustion. Check a real RoboTwin/pi0.5 episode if dependencies
and resources permit; report it separately from simulated contract tests.
