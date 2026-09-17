# Benchmark results and branch preparation

## Goal

Prepare the RoboTwin and LIBERO integration branch for review without adding
runtime logs, datasets, caches, or model weights.

## Scope

- Aggregate completed LIBERO and RoboTwin evaluations from authoritative
  per-episode result files.
- Generate compact machine-readable tables and a human-readable summary under
  the ignored local `results/benchmarks/` directory.
- Record the exact checkpoints used by the reported evaluations. Keep large
  policy checkpoints external, while packaging the requested inference-only
  LIBERO Qwen planner LoRA through Git LFS.
- Keep only the final data-building, training, inference, benchmark adapter,
  configuration, documentation, and test paths in the proposed commit.
- Run unit tests, Ruff, and repository hygiene checks before handoff.

## Acceptance criteria

- LIBERO aggregation contains 40 tasks and 2,000 unique episodes.
- RoboTwin aggregation distinguishes complete, running, and pending tasks; only
  complete 30-episode tasks contribute to the aggregate accuracy.
- Every reported success is taken from the benchmark-native success field.
- No `runs/`, generated result table, log, cache, dataset, secret, optimizer
  state, or large policy checkpoint is staged.
- The final checkpoint manifest names the planner, RoboTwin VLA, and LIBERO VLA
  artifacts used by the evaluations and records whether each artifact exists.
- Relevant unit tests and static checks pass, or remaining failures are reported.
