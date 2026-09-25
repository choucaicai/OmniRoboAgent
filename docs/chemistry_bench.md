# Chemistry bench

Chemistry bench is an independent Isaac Sim 4.5 environment for a fixed titration
task, connected to the existing DirectPipeline and LanguageSkillBackend.

## Install

Run from the repository root with Python 3.11:

```bash
UV_PROJECT_ENVIRONMENT=.venv-chemistry_bench uv sync --extra chemistry_bench --group dev
```

Install the standalone worker with Isaac Sim's Python, in a separate environment:

```bash
/absolute/path/to/isaac-sim-4.5.0/python.sh -m pip install \
  ./benchmarks/chemistry-bench-proto ./benchmarks/chemistry-bench-sim
```

Isaac Sim and NVIDIA assets remain subject to their own terms. grpcio, protobuf,
NumPy, Pillow and PyYAML retain their respective licenses.
Isaac Sim is not installed into the agent environment.

## Start and run

Choose an available GPU and a valid Franka USD asset:

```bash
CHEMISTRY_BENCH_SIM_GPU=0 CHEMISTRY_BENCH_FRANKA_USD=/absolute/path/to/franka.usd \
  /absolute/path/to/isaac-sim-4.5.0/python.sh \
  -m chemistry_bench_sim.worker --port 50051 --record-dir runs/chemistry_bench_demo
```

The worker binds loopback only, disables multi-GPU rendering and does not enable
WebRTC by default. It has no authentication: keep it dedicated to one episode owner.
For a remote worker use an authenticated tunnel, not a public unauthenticated port.
The adapter does not manage service startup/shutdown. Use the matching worker and
protocol from this repository; differently named gRPC services are not compatible.

Set the multimodal model endpoint/model in
`configs/agents/chemistry_bench_titration.yaml`, then run:

```bash
.venv-chemistry_bench/bin/omniroboagent run \
  --config configs/runs/chemistry_bench_titration.yaml
```

The task is to pick the NaOH bottle, pour incrementally until the beaker becomes
pink, return the bottle, and record the finding. The fixed action catalog supports pick, pour 5/15/30 ml,
place, observe and record. Only full primitive execution is supported.

## Semantics and limits

- Success requires a pink beaker AND at least one recorded finding; a planner claim
  alone cannot establish success.
- Privileged pH, volumes and vessel states remain private to grading. Only the RGB
  image, action catalog and timestamp are exposed as observations.
- Each completed action receives a fresh observation and verification.
- Reset reloads the same scene to restore initial chemistry. An empty Reset payload
  is not sufficient.
- RPC failures invalidate the client without replay: an expired pour may still
  execute. Reconcile/restart the dedicated worker before another run.
- Worker connections bypass inherited HTTP proxies without changing global settings.
- Chemistry is symbolic. Arm waypoints use Isaac's Lula inverse kinematics with
  scripted joint interpolation and visual bottle attachment, not fluid dynamics,
  collision planning, contact-accurate grasping or a trained policy. A Franka asset
  is required for the motion demo; unreachable waypoints fail explicitly.
- `--record-dir` enables continuous 20 FPS simulation-time recording (requires
  FFmpeg on PATH), including frames inside actions, object labels and action/status
  overlays. Model inference pauses are omitted. Each recording has JSON metadata;
  successful completion finalizes the MP4. The camera is 1280x720, with an added
  header/footer in the video. Runtime's separate `episode.mp4` remains step-based.

## Verification

For shared SDK installations, append `--kit-args --portable-root /absolute/writable/cache`
to the worker command to isolate Kit cache/config/log files. The directory must be
dedicated to this worker, not another running instance.

Validate a dedicated running worker using two scripted episodes, including robot
state, image and initial chemistry reset assertions:

```bash
.venv-chemistry_bench/bin/python scripts/smoke_chemistry_bench.py \
  --address 127.0.0.1:50051 --output runs/chemistry_bench_scripted
```

Then validate the model-driven loop:

```bash
.venv-chemistry_bench/bin/python scripts/smoke_chemistry_bench.py \
  --address 127.0.0.1:50051 --output runs/chemistry_bench_model --episodes 1 \
  --agent-config configs/agents/chemistry_bench_titration.yaml \
  --base-url http://127.0.0.1:8000
```

The script exits nonzero if any episode fails. Initial images, Runtime traces/video,
and `smoke_summary.json` are saved under the output directory.
The demo allows 600 seconds per RPC for shared-GPU continuous rendering; the smoke
runner exposes this as `--rpc-timeout`. A timeout still requires reconciliation,
not automatic action replay.

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests
.venv/bin/mypy src/omniroboagent
.venv-chemistry_bench/bin/pytest tests/integration/test_chemistry_bench_rpc.py -q
```

Unit tests cover action mapping, grading, failures, lifecycle and observation
validation. The optional loopback test checks actual protobuf/gRPC serialization
against a fake service, not Isaac Sim.

Real smoke verified on 2026-09-21 with Isaac Sim 4.5.0 and a Franka asset:
two recorded scripted episodes succeeded in four steps each; Qwen3.5-9B succeeded
in 13 steps with 14 recorded frames and no artifact errors. Robot joint state,
non-placeholder images and initial chemistry reset were checked. Earlier prompt
iterations failed; the current prompt describes scene layout, holding visualization
and color/shadow interpretation. This is one fixed-task smoke, not a performance
benchmark. See the [validation record](../impl_docs/changes/2026-09-21-chemistry-bench-real-smoke.md).

That historical model verification used a static arm. The new articulated scripted
demo succeeded in five steps: pick, pour twice, return the bottle, record the pink
endpoint. Its continuous video contains 416 frames at 20 FPS (20.8 seconds,
1280x832 including overlays). Initial, lifted, tilted and final frames were visually
checked. The model-driven loop has not been revalidated after these camera/motion
changes. See the [visual-demo record](../impl_docs/changes/2026-09-21-chemistry-bench-visual-demo.md).

On the tested shared host, a GPU 0 process with `CUDA_VISIBLE_DEVICES=0` and
`CHEMISTRY_BENCH_SIM_GPU=0` avoided lengthy cross-device startup tests. Kit and CUDA
indices must agree; do not generalize this masking recipe to other device indices
without checking. First shader compilation and network-mounted SDK loading can be
slow. The worker can remain running between episodes; each episode restores state.

Protocol bindings are generated with `grpcio-tools==1.83.0` from
`benchmarks/chemistry-bench-proto/protos/embodiment.proto`; after generation, keep
the sibling `embodiment_pb2` import relative in `embodiment_pb2_grpc.py`.
