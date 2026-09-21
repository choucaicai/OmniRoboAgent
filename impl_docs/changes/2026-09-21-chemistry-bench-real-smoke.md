# Chemistry bench real Isaac smoke

Plan: [0014](../plans/0014-chemistry_bench-titration.md).

## Result

Real Isaac Sim 4.5.0, Franka asset, 640x400 rendered camera and existing synchronous
Agent/Pipeline/Runtime loop were exercised on 2026-09-21. The worker reported seven
robot joints; initial images were non-placeholder and initial chemistry was checked
on each episode. Privileged state remained outside planner observations and memory.

- Two recorded scripted episodes: success, four steps each; reset checked again.
- Final Qwen3.5-9B episode: success in 13 steps, ending with record-finding after
  incremental pours and visible pink liquid. Termination: task_success.
- Earlier prompt iterations failed at 30, 11 and 30 steps. Failure logs were kept.
  The final prompt explains scene layout, the symbolic holding marker and neutral
  shadows versus pink liquid. The success predicate was not changed.

This is a smoke validation, not a success-rate benchmark. The chemistry is symbolic
and object handling is scripted; it does not validate fluid/contact physics or VLA.
An additional pick/pour diagnostic returned successful primitives and ten trajectory
samples, but maximum arm joint displacement was approximately 1e-13 rad. With cuRobo
disabled the arm is effectively static; the object/chemistry loop is what passed.
Do not present this result as articulated robot grasping or physically executed pouring.

## Implementation

Added `scripts/smoke_chemistry_bench.py` for scripted/model runs with robot, image
and reset assertions, result summaries and recording. Enabled video in the example
RunConfig. Worker accepts trailing `--kit-args` for deployment-specific Kit options.
No model server, system driver, IOMMU or other user's service was modified.

## Deployment notes

The shared SDK initialized slowly due to network storage and first shader compilation.
An independent Kit portable root avoided shared cache locks. GPU 7 startup spent
substantial time in cross-device P2P validation; setting `/validate/p2p/enabled=false`
alone did not prevent that check on this installation. The successful worker used
GPU 0 with `CUDA_VISIBLE_DEVICES=0`, `CHEMISTRY_BENCH_SIM_GPU=0`, multi-GPU disabled
and cuRobo disabled. Do not assume arbitrary CUDA masking preserves Kit device indices.

Use the documented worker command with an available GPU and the matching local
protocol package. The successful local worker listens on 127.0.0.1:50061; the
existing Qwen endpoint was http://127.0.0.1:28000. These are local deployment values,
not required public defaults. Scene assets used the Isaac 4.5 Franka USD asset.

## Reproduction and artifacts

See [usage](../../docs/chemistry_bench.md) for independent SDK installation and commands.
Local ignored artifacts are under `runs/chemistry_bench_smoke/`:

- `scripted-video/`: two recorded successful episodes and `smoke_summary.json`.
- `model-color/`: final successful model episode, trace, video and summary.
- `model/`, `model-grounded/`, `model-final/`: unsuccessful diagnostic iterations.
- Worker startup logs for each deployment attempt.

Regression: 143 tests passed, one optional protocol test skipped in the base
environment; Ruff, mypy and diff checks passed. The actual worker exercises the
same gRPC protocol in the recorded smoke runs. No remote commit, push or PR created.
