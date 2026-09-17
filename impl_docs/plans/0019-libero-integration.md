# LIBERO integration

Status: completed (2026-09-15).

Add a minimal LIBERO vertical slice without changing OmniRoboAgent's core
Runtime, Pipeline, Planner, or Verifier contracts.

- Add a benchmark environment adapter under `environments/benchmarks/libero/`.
  Reuse ClawVLA's existing LIBERO simulator adapter for official task suites,
  fixed initial states, two-camera observations, 8-D robot state, 7-D actions,
  and authoritative `env.check_success()` evaluation.
- Add a local LIBERO pi0.5 SkillBackend. It lazily reuses ClawVLA's validated
  LeRobot pi0.5 adapter, keeps the policy resident, sends the active Omni
  subtask as the policy prompt, and returns a source-observation-bound action
  chunk.
- Add a LIBERO evaluator that enumerates official tasks and initial states,
  writes atomic episode JSONL plus a suite summary, and preserves official
  per-task and macro success metrics.
- Add an atomic smoke AgentConfig/RunConfig. The first smoke uses the official
  task instruction as one subtask; LIBERO-Long can later replace the Planner
  with the existing `SubtaskPlanPlanner` without changing environment or policy
  interfaces.
- Add unit tests for observation mapping, action validation/execution, policy
  prompt wiring, official task enumeration, and evaluator aggregation.

The integration must not expose BDDL predicates or `check_success()` to the
Planner or policy. Benchmark success remains an Environment result used by the
Verifier/Pipeline only. No model training or full 2,000-episode evaluation is
part of this change.

Acceptance:

- Existing unit tests continue to pass.
- New LIBERO unit tests pass without importing the real simulator or loading a
  model.
- The installed LIBERO SDK resolves the four evaluation suites and their fixed
  initial states.
- A real environment reset/action smoke and real pi0.5 inference are attempted
  only when they do not interfere with the running RoboTwin evaluation; any
  unrun heavy validation is reported explicitly.
