# Chemistry bench continuous visual demo

Status: DONE; real Isaac scripted visual demo verified.

## Changes

- Wider 1280x720 camera, neutral table lighting and projected object labels.
- Scripted Franka arm/gripper motion using Isaac Lula IK; the bottle follows the
  gripper transform during lift, transport and tilt, then returns to the table.
- Continuous worker-side recording at 20 FPS simulation time with action/status
  overlays and JSON metadata; model inference pauses are omitted.
- Scripted smoke now includes bottle placement before recording the finding.
- Removed the unused optional cuRobo path. Core Agent/Runtime remain unchanged.

## Validation

- Base suite: 144 passed, 1 optional test skipped.
- Ruff checks for worker, recorder, scene, smoke runner and worker tests passed.
- Recorder test produces an actual FFmpeg MP4 and verifies frame/action metadata.
- Chemistry unit/loopback tests: 21 passed; mypy passed for 62 source files.
- First real attempt exposed a narrow default lens and the 120-second RPC limit
  during continuous rendering. Set an explicit 18 mm USD lens, render at 20 Hz
  while keeping 60 Hz physics, and allow 600-second RPCs in the demo configuration.
- New articulated Isaac episode succeeded in five steps, with initial reset checks.
  Video: 416 frames, 20 FPS, 20.8 seconds, 1280x832 including overlays.
  Initial/lifted/tilted/final frames were inspected; arm movement, bottle attachment,
  bottle return and pink endpoint are visible, with a final TASK SUCCESS overlay.
- Local artifacts (ignored):
  `runs/chemistry_bench_demo/continuous/demo-670d82f5b668.mp4`, matching JSON metadata,
  and `runs/chemistry_bench_demo/wide/smoke_summary.json`.
- No new VLM episode was run after the camera/motion changes; the new video uses
  the deterministic scripted planner through the existing runtime/pipeline.

## Limits

Scripted interpolation and visual attachment are not contact simulation or
collision avoidance. Chemistry remains symbolic; no fluid solver or policy
training is introduced. Prior static-arm smoke results do not validate this demo.
