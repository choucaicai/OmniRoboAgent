# Composable Agent Base

Status: DONE

## Goal

在不改变 Pipeline、Runtime 和 benchmark ownership 的前提下，将 `BaseAgent` 演进为类似 Transformers model base 的组合式基类：基类统一持有组件和生命周期，继承类实现明确的决策抽象方法。

## Confirmed Decisions

- 保留 `BaseAgent` + `DefaultAgent`，不引入新的 Agent manager、factory hierarchy 或模型框架依赖。
- `BaseAgent` 组合 `Planner`、`Verifier`、`Memory` 和 `SkillBackend`，但不持有 Pipeline、Runtime 或 Environment。
- `plan()`、`predict_action()` 和 `verify()` 保持抽象，由具体 Agent 实现；memory update、healthcheck 和 close 由基类提供一致默认行为。
- `DefaultAgent` 继续作为纯委托实现，现有 class path 和 AgentConfig 保持兼容。
- 自定义 Agent 可以复用部分组件并覆盖决策方法，但不能绕过 Pipeline 的执行和 transition ownership。

## Resolved Decisions

- 第一阶段继续要求 Planner、Verifier、Memory 和 SkillBackend 四个组件全部存在。
- 不增加 component registry 或通用 `components` mapping。
- Memory recall 由后续 TieredMemory TODO 通过显式 Agent/Pipeline input 接入，不在本计划中隐式注入。

## Open Questions

- None for this implementation stage.

## Scope

- 将共享组件持有、healthcheck、memory update 和 close 逻辑上移到 `BaseAgent`。
- 保留三个核心抽象决策方法，并为继承式 Agent 增加 contract tests。
- 保持 `build_agent()` 的现有顶层 component config 兼容。
- 更新 Agent extension 文档和 architecture。

## Out of Scope

- 引入 `torch.nn.Module`、Transformers、checkpoint save/load 或训练 API。
- 让 Agent 管理 Pipeline、Runtime、Environment 或 benchmark lifecycle。
- 建立 plugin discovery、component registry 或自动 dependency injection。

## Tasks

1. [x] 固定 BaseAgent constructor、component ownership 和 lifecycle contract。
2. [x] 将 DefaultAgent 的共享 update/healthcheck/close 逻辑移动到 BaseAgent。
3. [x] 增加 composed default Agent 和 inherited custom Agent tests。
4. [x] 验证现有 AgentConfig、EB-ALFRED 和 RoboCasa class path 不变。
5. [x] 更新 architecture、custom component 文档、TODO 和 change record。

Implementation record: [2026-07-15 composable agent base](../changes/2026-07-15-composable-agent-base.md).

## Acceptance Criteria

- `BaseAgent` 统一持有并关闭组件，重复 close 不泄漏资源。
- 子类只需实现明确的决策抽象方法，不复制生命周期样板代码。
- `DefaultAgent` 行为和公开 class path 不变。
- Agent 不获得 Pipeline 或 Environment ownership。

## Risks

- 将可选组件加入第一版会让类型和 config contract 变复杂；默认继续要求完整组合。
- 基类自动注入 memory context 可能形成隐式决策影响；recall 必须是显式输入字段。
