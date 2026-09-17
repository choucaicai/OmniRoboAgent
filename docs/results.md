# Reproducible evaluation results

The compact tables are generated locally under the ignored
`results/benchmarks/` directory from the raw per-episode outputs under the
ignored `runs/` directory:

```bash
python scripts/summarize_benchmarks.py
```

The script rejects duplicate LIBERO episodes, reports all four official suites,
and counts a RoboTwin result only when all 30 held-out episodes for that task are
present. Both benchmarks use their native environment success signal:
`LIBERO env.check_success()` and `RoboTwin task_env.check_success()`.

## Reported snapshot

| Benchmark | Tasks | Episodes | Successes | Accuracy |
| --- | ---: | ---: | ---: | ---: |
| LIBERO (four suites) | 40 | 2,000 | 1,904 | 95.20% |
| RoboTwin 2.0 (demo_clean) | 50 | 1,500 | 922 | 61.47% |

The local output contains `libero_per_task.csv`, `robotwin_per_task.csv`,
`summary.json`, and a readable `README.md`. These generated result files are not
uploaded to the repository.

## Checkpoint identities

The final local adapters and the shared RoboTwin pi0.5 checkpoint are listed in
[`checkpoints/manifest.json`](../checkpoints/manifest.json). We deliberately do
not commit raw episodes, images, traces, logs, optimizer states, or the large
pi0.5 checkpoints. The inference-only LIBERO Qwen planner LoRA is the single
packaged weight artifact and is stored through Git LFS. The manifest records
paths and adapter SHA-256 values so another checkout can verify the artifacts.

The RoboTwin snapshot uses the Qwen3.5-9B planner LoRA at step 3500 together with
the shared subtask pi0.5 checkpoint at step 20000. The LIBERO snapshot uses the
subtask pi0.5 adapter at step 5000 and sends the official task prompt directly to
the VLA. The separately packaged LIBERO Qwen planner LoRA at step 500 supports
the integrated planner path but was not used to calculate that direct-VLA score.
