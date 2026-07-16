# Key Event Memory And Visual Artifacts

Date: 2026-07-16
Related plan: `impl_docs/plans/0010-key-event-memory.md`

## Changed

- `Memory.recall()` 增加兼容的 `key_events` 分区。
- `DirectPipeline` 和 `SkillExecutionPipeline` 为 transition 输出确定性 `event_type`。
- `TieredMemory` 使用 bounded recent transitions 和长期 key events；session reset 保留 key events。
- 关键事件保存结构化文本、Verifier evidence、expected outcome、task progress、recovery action 和 artifact references。
- `SyncRuntime` 提供 session-scoped `artifact_dir`；启用后 Memory 保存当前 camera PNG 和 append-only key-event JSONL。
- Planner/Verifier 显式消费 bounded key-event 文本，不自动加载全部历史关键帧。
- RoboCasa composite remote/local 配置启用 key-event artifacts，resolved config 记录相关 Memory 参数。
- 同步 `docs/`、architecture、TODO 和 memory plans。

## Files

- `src/omniroboagent/agent_core/memories/`
- `src/omniroboagent/agent_core/planners/language_skill.py`
- `src/omniroboagent/agent_core/verifiers/subtask.py`
- `src/omniroboagent/pipelines/`
- `src/omniroboagent/runtimes/sync.py`
- `src/omniroboagent/evals/benchmarks/robocasa/evaluator.py`
- `configs/agents/robocasa365_groot_composite_*.yaml`
- `tests/unit/`
- `README.md`
- `docs/`
- `impl_docs/`

## Verification

- `conda run -n omniagent pytest -q`：114 passed。
- `conda run -n omniagent ruff check src tests`：通过。
- `conda run -n omniagent mypy`：58 个 source files 无问题。
- 全部 12 个 checked-in YAML 解析通过。
- 本地 Markdown link checker：检查 11 个变更文档中的 34 个相对链接，全部存在。
- 本次 owned files `git diff --check`：通过；repository-wide check 仍只命中用户已有 `src/omniroboagent/agent_core/planners/base.py` trailing whitespace。
- unit tests 验证 ordinary transition 不写 artifact、`event_path` 兼容、Runtime artifact directory、关键事件 PNG/JSONL、session reset、recall limit、Pipeline event type 和 Planner/Verifier context。

## Remaining Work

- 尚未重跑真实 RoboCasa Qwen+GR00T smoke；当前只验证了配置实例化和 unit-level artifact persistence。
- peak RSS、artifact 数量/磁盘占用和 Verifier backend usage/latency 继续在 RoboCasa audit 中跟踪。
- semantic-equivalent repeated execution detection 和正式多 episode matrix 不属于本计划。
