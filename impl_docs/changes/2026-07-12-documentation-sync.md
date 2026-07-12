# Implementation Documentation Sync

Date: 2026-07-12
Related plan: `impl_docs/plans/0002-documentation-sync.md`

## Changed

- 将架构状态、组件职责、数据边界和演进阶段与当前 `v0.1` 实现对齐。
- 用实际 `LanguageSkillPlanner`、OpenPI `host/port` 和 `DirectPipeline.init_args` 替换过期配置示例。
- 补充 AgentConfig、RunConfig、CLI 分支、action chunk 参数传递和输出可复现性说明。
- 补充 LLM、Planner、OpenPI、Memory、Environment、Pipeline 和 Runtime 的实际输入输出及错误语义。
- 补充自定义组件加载条件和资源生命周期。
- 补充 EB-ALFRED 的 Xvfb 检查、依赖故障定位、Planner 空输出处理和原生 evaluator 未对齐边界。
- 修正 TODO：resolved config/framework version 尚未自动写入结果，真实连续 action chunk 执行仍需首个连续控制 Environment 验证。

## Files

- `impl_docs/architecture/overview.md`
- `impl_docs/TODO.md`
- `impl_docs/README.md`
- `impl_docs/plans/0002-documentation-sync.md`
- `docs/README.md`
- `docs/quickstart.md`
- `docs/configuration.md`
- `docs/interfaces.md`
- `docs/custom_components.md`
- `docs/eb_alfred.md`

## Verification

- 实际加载 `configs/agents/eb_alfred.yaml`，并从 RunConfig 实例化 `DirectPipeline` 和 `SyncRuntime`：通过。
- `conda run -n omniagent python -m pytest`：24 个 tests 全部通过。
- `conda run -n omniagent ruff check src tests`：通过。
- `conda run -n omniagent ruff format --check src tests`：27 个文件格式正确。
- `conda run -n omniagent mypy`：22 个 source files 无类型错误。
- 检查 `impl_docs/`、`docs/` 和根 README 的本地 Markdown links：全部有效。
- 检查 `impl_docs/` 和 `docs/` trailing whitespace：未发现。

## Remaining Work

- 确认正式 EB-ALFRED subset 和 episode 数量，并与原生 evaluator 对齐。
- 将 resolved config 和框架版本写入 benchmark output。
- 使用真实 OpenPI server 和连续控制 Environment 验证 action chunk 执行。
