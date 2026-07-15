# Skill, Agent And Memory Implementation Plan

Date: 2026-07-15
Related plan: `impl_docs/plans/0007-skill-execution-state-graph.md`, `impl_docs/plans/0008-composable-agent-base.md`, `impl_docs/plans/0009-tiered-agent-memory.md`

## Changed

- 将 skill execution graph 的开放问题固定为可实施的 state、proposal、verification、transition 和 recovery contract。
- 将后续实现拆成 Planner/Verifier、graph state、recovery/trace 和最终兼容性收口四个原子阶段。
- 新增组合式 `BaseAgent` 后续重构计划，明确基类与 Pipeline/Runtime/Environment 的 ownership 边界。
- 新增集中分层 Memory 计划，明确 bounded visual working memory、长期 event memory、text summary 和显式 recall 语义。

## Files

- `impl_docs/README.md`
- `impl_docs/TODO.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/plans/0007-skill-execution-state-graph.md`
- `impl_docs/plans/0008-composable-agent-base.md`
- `impl_docs/plans/0009-tiered-agent-memory.md`
- `impl_docs/changes/2026-07-15-skill-agent-memory-implementation-plan.md`

## Verification

- 对照当前 `SkillExecutionPipeline`、`SubtaskSkillPlanner`、`BaseAgent`、`DefaultAgent` 和 Memory 实现核对设计边界。
- 本地 Markdown link checker：检查 7 个本次文档文件，所有相对链接存在。
- `git diff --check -- impl_docs`：通过。
- 本阶段只修改实现文档；未运行 pytest、Ruff 或 mypy。

## Remaining Work

- 按 0007 plan 依次实现 Planner/Verifier contract、graph state、recovery 和测试。
- 0008 和 0009 保持 TODO，待 skill execution graph 稳定后分别实施。
