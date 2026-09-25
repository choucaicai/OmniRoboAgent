# Chemistry bench complete visual demo

Status: DONE

## Goal

Produce a continuous, clearly framed demo of the arm picking up a bottle, moving,
pouring, returning it and completing the simulated titration.

## Confirmed Decisions

Use scripted motion and symbolic chemistry. No fluid simulation, contact-accuracy
work, policy training or new VLA. Keep the existing Agent/Runtime contracts.

## Open Questions

None for this demo; validate camera framing and robot trajectory in Isaac.

## Scope

Wider scene camera, readable labels, deterministic arm/gripper movement with attached
bottle visualization, continuous worker-side recording with action/status overlay,
and a repeatable demo command. Update PR material after real verification.

## Out of Scope

Physical grasp attachment, collision avoidance guarantees, liquid dynamics, robot
safety certification, new agent architecture or remote PR publication.

## Tasks

- [x] Implement framing and scripted motion using the installed Isaac SDK.
- [x] Record intra-action frames with labels and execution status.
- [x] Run a complete real demo including return/reset and verify joint movement.
- [x] Update tests, documentation and PR preparation files.

## Result

Isaac Sim 4.5 scripted episode succeeded in five steps. Continuous video contains
416 frames at 20 FPS (20.8 seconds, 1280x832 including overlays). Initial, lifted,
tilted and final frames were inspected: the arm moves, the bottle follows it and
returns to the table, and the beaker is pink at success. No new VLM run was needed
for this scripted visual-demo scope.

## Acceptance Criteria

Robot and vessels remain visible. Bottle follows the hand; gripping, tilt and return
are visible. Video contains motion frames, not just episode-step screenshots.
Task success remains simulator-graded. Failures are explicit, not silent static arms.

## Risks

SDK cold startup is slow on shared storage. Scripted attachment is a presentation
approximation, not contact physics. Camera/prompt changes need a new VLM smoke.
