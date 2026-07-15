# Skill Execution State Graph Design

Date: 2026-07-15
Related plan: `impl_docs/plans/0007-skill-execution-state-graph.md`

## Changed

- 确认 `SkillExecutionPipeline` 下一阶段使用 Pipeline-owned explicit graph state 和确定性条件转换。
- 明确只参考 LangGraph 的 state/node/conditional-edge 设计，不集成 LangGraph，也不实现通用 Graph 引擎。
- 保持 Runtime 对 episode lifecycle、outer loop、limits、trace 和资源释放的 ownership。
- 将 `plan`、`act`、`execute`、`verify`、`transition` 和 `recover` 定义为逻辑阶段，并明确 node 不要求拆成独立 class、module 或公共接口。
- 将具身 Agent skill execution TODO 从 RoboCasa-specific 工作中抽出，建立独立计划和状态入口。

## Files

- `rules/README.md`
- `impl_docs/README.md`
- `impl_docs/TODO.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/plans/0007-skill-execution-state-graph.md`
- `impl_docs/changes/2026-07-15-skill-execution-state-graph-design.md`

## Verification

- 对照当前 `Pipeline.step()`、`SyncRuntime.run()` 和 `SkillExecutionPipeline` 实现确认 ownership；本次未修改代码行为。
- `for f in rules/README.md impl_docs/README.md impl_docs/TODO.md impl_docs/architecture/overview.md impl_docs/plans/0007-skill-execution-state-graph.md impl_docs/changes/2026-07-15-skill-execution-state-graph-design.md; do ...; done`：本地 Markdown relative-link checker exit 0，无缺失链接输出。
- `git diff --cached --check`：本次 staged 文档通过。
- Repository-wide `git diff --check` 未通过：用户已有的 `src/omniroboagent/agent_core/planners/base.py:9` 包含 trailing whitespace；该文件与本次设计无关，未修改、未暂存。
- 未运行 pytest、Ruff 或 mypy：本次仅修改规则和实现文档，没有修改 Python 代码。

## Remaining Work

- 按 `impl_docs/plans/0007-skill-execution-state-graph.md` 实现 graph state、subtask verification、transition 和 recovery。
- 实施前确认 `active_execution` 和 Subtask Verifier 的最小字段。
- 实施后补充完整 unit tests，并在 EB-ALFRED 和 RoboCasa smoke configs 上验证兼容性。
