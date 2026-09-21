# Chemistry bench titration environment

Status: DONE

## Goal

Integrate an independent chemistry bench environment and fixed titration task.

## Confirmed Decisions

Preserve Isaac Sim in a separate worker process. Reuse existing DirectPipeline,
LanguageSkillBackend and EnvironmentVerifier. Keep simulator truth private to grading.

## Open Questions

None for this fixed smoke. Formal multi-episode quality evaluation is out of scope.

## Scope

Environment adapter, local protocol and simulator packages, fixed scene/task
configuration, CPU and loopback tests, optional dependencies and setup documentation.

## Out of Scope

Fluid dynamics, learned VLA control, new planners/runtime, multi-worker evaluation
and remote PR publication.

## Tasks

- [x] Implement adapter lifecycle, actions, observations and authoritative grading.
- [x] Add scene, task, protocol and independent worker packages.
- [x] Test success, action failure, invalid observations and RPC uncertainty.
- [x] Verify CPU regression, lint and typing.
- [x] Validate real rendering, robot loading and model-driven scripted task execution.
  - Use a dedicated loopback worker and isolated Kit portable root.
  - Run two scripted episodes with robot/image/reset assertions, then a VLM episode.
  - Retain trace, video and summary; do not equate a fake service test with Isaac.

## Acceptance Criteria

No heavy SDK in core. Fresh feedback after actions. Success requires pink beaker
and recorded finding. No timed-out action replay. Document validation boundaries.

## Risks

Symbolic chemistry and scripted pouring are not fluid/contact simulation.
The cuRobo-disabled smoke does not validate arm motion: the pour trajectory showed
no meaningful joint displacement. Articulated grasp/pour control remains out of scope.
Use a dedicated worker. Reset must restore the initial snapshot.
Worker uses loopback-only unauthenticated gRPC.

Completion: [real smoke record](../changes/2026-09-21-chemistry-bench-real-smoke.md).
