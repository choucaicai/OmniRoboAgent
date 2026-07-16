# Agent Core

Agent Core 是 OmniRoboAgent 的决策组合层。它不负责 episode loop、environment execution 或 benchmark aggregation，而是组合四类能力：

```text
BaseAgent
├── Planner
├── Verifier
├── Memory
└── SkillBackend
```

其中 Agent、Planner、Verifier 和 Memory 的 contract 位于 `agent_core/`；SkillBackend 位于 `backends/skills/`，因为它负责连接 policy、rule 或 action generator。

## Components

| Component | Input and output | Current implementations |
| --- | --- | --- |
| [Agent](agent.md) | 接收 Pipeline 构造的输入并委托内部组件 | `DefaultAgent` |
| [Planner](planner.md) | `dict -> Any` | `LanguageSkillPlanner`、`TaskSkillPlanner`、`SubtaskSkillPlanner` |
| [Verifier](verifier.md) | `dict -> dict` | `EnvironmentVerifier`、`SubtaskVerifier` |
| [Memory](memory.md) | event update + explicit recall | `InMemoryMemory`、`JsonlMemory`、`TieredMemory` |
| [SkillBackend](../components/skill_backend.md) | `dict -> Any action payload` | language passthrough、remote/local policy backends |

## Composition

`AgentConfig` 显式选择每个组件：

```yaml
agent:
  class_path: omniroboagent.agent_core.DefaultAgent

planner:
  class_path: your_package.YourPlanner

verifier:
  class_path: your_package.YourVerifier

memory:
  class_path: omniroboagent.agent_core.InMemoryMemory

skill_backend:
  class_path: your_package.YourSkillBackend
```

`build_agent()` 会先构造四个组件，再注入 Agent。完整配置规则见 [Configuration](../configuration.md)。

## Boundaries

- Agent 不持有 Pipeline、Runtime 或 Environment。
- Planner 提出下一步计划，不宣告 benchmark task success。
- Verifier 产生 evidence 和 execution status；具体语义由当前 Pipeline 解释。
- Memory 只保存和返回上下文，不暗中修改 Planner 或 Pipeline decision。
- SkillBackend 只生成 action payload，不执行动作。
- 模型和 policy 通信协议放在 backend，不派生 HTTP、WebSocket 或 provider-specific Agent。

下一节从 [Agent](agent.md) 开始逐个介绍 Agent Core 元素。
