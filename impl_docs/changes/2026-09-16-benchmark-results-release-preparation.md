# Benchmark results and release preparation

## Changes

- Added `scripts/summarize_benchmarks.py` to aggregate raw LIBERO and RoboTwin
  episode outputs without copying logs, traces, images, or datasets into Git.
- Added a local-only `results/benchmarks/` generation path and a results
  document. The generated tables remain ignored rather than being uploaded.
- Added `checkpoints/manifest.json` with final planner/VLA artifact paths and
  adapter checksums. Large policy weights remain external; the requested
  inference-only LIBERO Qwen planner LoRA is packaged through Git LFS.
- Added a 50-task RoboTwin manifest for reproducible aggregation.
- Recorded the release scope and acceptance checks in plan `0021`.

## Verified snapshot

- LIBERO: 40 tasks, 2,000 unique episodes, 1,904 successes (95.20%).
- RoboTwin 2.0: 50 tasks, 1,500 episodes, 922 successes (61.47%).
- Both benchmark summaries use the native environment success signal.

## Hygiene

The ignored `runs/` and generated `results/benchmarks/` trees remain available
locally for audit. No raw log, observation, trace, dataset, cache, secret,
optimizer state, or large policy checkpoint is staged by this change. Existing
tracked RobotWorkspace assets and unrelated user edits were not removed or
rewritten.
