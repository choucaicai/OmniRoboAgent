# Agent Core Subpackages

Status: `DONE`

## Goal

将 Agent Core 从单层 `agents/` 重组为独立的 `agent_core/` package，并按组件类型拆分 `agents/`、`planners/`、`verifiers/` 和 `memories/` 子 package，方便后续增加不同实现。

## Confirmed Decisions

- 使用 `agent_core/` 表达完整的 Agent Core ownership 边界。
- `agents/` 保存 `BaseAgent` contract 和不同 Agent 实现。
- `planners/`、`verifiers/`、`memories/` 分别保存对应 contract 和具体实现。
- 子 package 使用复数命名，并通过各自 `__init__.py` 提供最小公开 API。
- `agent_core/__init__.py` 统一导出当前公共组件。
- 直接迁移到 `omniroboagent.agent_core.*`，不保留旧 `omniroboagent.agents` 兼容路径。
- 只调整 package ownership、imports 和公开路径，不改变闭环运行语义。

## Scope

- 重组 `src/omniroboagent/agents/` 为 `src/omniroboagent/agent_core/` 下的四类子 package。
- 更新源码 imports、公开导出、配置 `class_path` 和测试。
- 更新架构文档和受影响的用户文档。
- 删除迁移后不再使用的旧 `agents/` package。

## Out of Scope

- 新增 Agent、Planner、Verifier 或 Memory 能力。
- 修改 Pipeline、Runtime、Environment 或 backend 的运行语义。
- 为旧 `omniroboagent.agents` 路径增加兼容层。

## Tasks

1. 创建 `agent_core/{agents,planners,verifiers,memories}` packages。
2. 将 contract 和当前实现迁移到对应子 package。
3. 更新内部 imports、公开 API、YAML `class_path` 和 tests。
4. 同步架构文档、用户文档和 TODO 状态。
5. 运行 unit tests、Ruff、mypy、公开导入和 stale-path 检查。

## Acceptance Criteria

- `agent_core/` 的实际目录结构与架构文档一致。
- 每类组件的 contract 与实现归属自己的子 package。
- 配置使用 `omniroboagent.agent_core.*` 并可正常实例化。
- 旧 `src/omniroboagent/agents/` 和有效文档中的旧公开路径已移除。
- 现有 unit tests、Ruff 和 mypy 全部通过。

## Risks

- dotted `class_path` 变化会破坏仍使用旧路径的外部配置。
- 跨 package type hints 可能产生循环 import。
- 拆分文件时可能意外改变实现逻辑，因此迁移应保持类内容不变。

## Change Record

- `impl_docs/changes/2026-07-13-agent-core-subpackages.md`
