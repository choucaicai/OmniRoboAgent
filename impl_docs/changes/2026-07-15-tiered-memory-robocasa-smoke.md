# Tiered Memory RoboCasa Fixed Smoke

Date: 2026-07-15
Related plan: `impl_docs/plans/0009-tiered-agent-memory.md`

## Changed

- 完成 `composite_seen / pretrain / DeliverStraw / episode_index=0 / seed=0` 的迁移后真实 Qwen+GR00T fixed smoke。
- 对比迁移前同 episode trace，记录 success、progress、steps、Planner calls、replans、token 和 latency。
- 核对 visual verifier evidence、completed/failed execution ledger、chunk-budget recovery 和每 step Environment action 边界。
- 更新 architecture、RoboCasa user docs、memory plan 和 TODO，明确控制逻辑改善、端到端 success 未改善及后续 recovery/RSS gap。

## Files

- `docs/robocasa365.md`
- `impl_docs/README.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/plans/0009-tiered-agent-memory.md`
- `impl_docs/TODO.md`
- `impl_docs/changes/2026-07-15-tiered-memory-robocasa-smoke.md`

## Verification

- `omniroboagent run --config configs/runs/robocasa365_groot_composite_remote_smoke.yaml`：1 episode 完整运行，0 success、0 exception、107 action chunks、1700 environment steps、termination 为 `environment_done`。
- `jq` 审计 `episodes.jsonl`、`resolved_config.json` 和 `trace.jsonl`：5 次 Planner calls、3 次 replans、12 次 visual semantic checks、1 个 completed execution、4 个 failed executions、107 个 step events 均各有 1 次 Environment result。
- 与 `runs/robocasa365_groot_composite_remote_seen_pretrain_5tasks/` 中同 seed baseline 对比：Planner calls 16 -> 5，Planner backend latency 32.43 s -> 19.31 s，episode latency 134.17 s -> 149.49 s，success/progress 均保持 0。
- 运行时确认 K=4、三路 `256x256x3` camera，working set 最多 12 张 frame；输出目录没有独立 visual artifact。
- 未重新运行 pytest、Ruff 或 mypy；本次提交只更新真实 smoke 结果文档，前一代码提交已通过 108 tests、Ruff 和 mypy。

## Remaining Work

- 使用 peak-RSS sampler 重复 fixed smoke；当前运行未保存精确 process peak RSS。
- 在 verifier trace 中增加 backend token usage 和 latency，区分 memory context 与 verification 成本。
- 调整 semantic-equivalent repeated execution detection，配置 `max_no_progress_steps` / `max_replans`，再运行相同 manifest 的多 episode matrix。
