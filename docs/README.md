# OmniRoboAgent Documentation

OmniRoboAgent 是用于组合、运行和评测具身 Agent 的模块化框架。核心执行闭环是：

```text
Observe -> Plan -> Act -> Verify -> Update or Stop
```

框架通过配置组合 Agent Core、model/policy backends、Pipeline、Runtime、Environment 和 benchmark evaluator。模型 provider、policy implementation 和 benchmark SDK 都不固化在 Agent 类型中。

## Start Here

| Document | Content |
| --- | --- |
| [Quickstart](quickstart.md) | 安装、选择 backend、healthcheck、测试和首次运行 |
| [Configuration](configuration.md) | `AgentConfig`、`RunConfig`、`class_path` 和 registry |
| [Agent Core](agent_core/README.md) | Agent、Planner、Verifier 和 Memory 的组合关系 |
| [Framework Components](interfaces.md) | Backend、Pipeline、Runtime、Environment 和 Evaluation |
| [Custom Components](custom_components.md) | 实现并通过配置加载自定义组件 |

## Agent Core

| Component | Responsibility |
| --- | --- |
| [Agent](agent_core/agent.md) | 组合 Planner、Verifier、Memory 和 SkillBackend，并管理组件 lifecycle |
| [Planner](agent_core/planner.md) | 根据 task、observation 和 memory 提出下一步计划或 subtask |
| [Verifier](agent_core/verifier.md) | 根据 environment feedback 和 evidence 判断执行状态 |
| [Memory](agent_core/memory.md) | 保存事件和视觉上下文，并通过显式 recall 返回上下文 |

## Framework Components

| Component | Responsibility |
| --- | --- |
| [Model Backend](components/model_backend.md) | 隔离 LLM/VLM provider 或推理协议 |
| [Skill Backend](components/skill_backend.md) | 将计划转换为 environment 可执行的 action payload |
| [Pipeline](components/pipeline.md) | 定义调用顺序、输入构造和状态转换 |
| [Runtime](components/runtime.md) | 管理 episode lifecycle、limits、trace 和资源释放 |
| [Observability](components/observability.md) | 保存 Agent trace、episode video 和 artifact manifest |
| [Environment](components/environment.md) | 连接 benchmark、simulator 或 robot 并执行 action |
| [Evaluation](components/evaluation.md) | 遍历任务、聚合指标并保存可复现输出 |

## Benchmarks

- [EB-ALFRED](eb_alfred.md)：EmbodiedBench/AI2-THOR 安装、运行和输出。
- [RoboTwin 2.0](robotwin_omni_compat.md)：Qwen 调度、共享 pi0.5 backend 和评测协议。
- [LIBERO](libero.md)：官方 task suites、固定初始状态、本地 pi0.5 和评测输出。
- [RoboCasa365](robocasa365.md)：assets、atomic/composite Agent、VLA backends 和 evaluation。
- [评测结果](results.md)：LIBERO/RoboTwin 汇总表和本地 checkpoint 身份。

架构约束、实现计划和历史变更位于 GitHub 仓库的 [`impl_docs/`](https://github.com/choucaicai/OmniRoboAgent/tree/master/impl_docs)，不属于用户教程。
