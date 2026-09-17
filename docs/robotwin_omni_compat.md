# RoboTwin Omni-style compatibility

`configs/agents/robotwin_omni.yaml` and
`configs/runs/robotwin_omni.yaml` provide the Omni-style surface for RoboTwin
without changing the benchmark success definition.

The planner and verifier expose the same structured fields used by the rest of
the framework:

```text
task -> skill -> subtask -> grounded_arguments -> expected_outcome
```

RoboTwin subtasks are assigned one of the eleven protocol skill labels:

```text
gripper control, handover, hang, open, pick and place, pour,
press, rotate, scan, shake, tool use
```

These labels are an interface envelope. The pi0.5 backend still executes the
concrete subtask prompt. The worker receives the task/skill/subtask metadata in
`omni_context`, while scheduler-only fields such as the chunk budget, seed and
episode index are removed from that worker payload.

The Qwen planner receives the complete task, initial three-camera observation,
and available skill labels. It generates the complete ordered plan once,
including a positive chunk budget for every subtask. At each subtask boundary it
receives the cached plan, current images, recent history, and explicit progress,
then copies the current item. The verifier receives the same plan and progress
after each action chunk and advances only when that item's budget is consumed.

The run keeps a 50-chunk safety guard, but neither that guard nor local budget
completion is a benchmark-success label. `RoboTwinEnvironment` reports
`task_success` from `RoboTwin.task_env.check_success()`, and the verifier preserves
that authoritative result before applying any local scheduling decision.

Run the compatibility smoke entry point with:

```bash
cp configs/examples/robotwin_omni_pi05.example.json \
  configs/examples/robotwin_omni_pi05.local.json
# Edit the local copy with the RoboTwin/OpenPI/checkpoint paths.
export ROBOTWIN_CONFIG="$PWD/configs/examples/robotwin_omni_pi05.local.json"
PYTHONPATH=src python -m omniroboagent.cli run \
  --config configs/runs/robotwin_omni.yaml
```

The Qwen endpoint and resident pi0.5 worker must already be running. The training
data and final model entry points are documented in
[`fixed_schedule_sft.md`](fixed_schedule_sft.md). The 50-task held-out result is
reported in [`results.md`](results.md).
