# Framework Components

Agent Core 负责组合决策组件，其他 framework components 负责模型连接、action generation、执行顺序、episode lifecycle、外部环境和评测聚合。

```text
CLI / Application
       |
       v
    Runtime -------- lifecycle, limits, recorder hooks
       |
       +-------> Observability -> Agent trace / video / manifest
       v
    Pipeline ------- call order, inputs, transitions
       |       \
       v        v
  Agent Core   Environment
    |    |
    v    v
 Model  Skill Backend
 Backend     |
             v
        action payload

Evaluation -> runs Agent + Pipeline + Runtime + Environment over task sets
```

## Components

| Component | Contract | Current implementations |
| --- | --- | --- |
| [Model Backend](components/model_backend.md) | `complete()`、`healthcheck()`、`close()` | `OpenAICompatibleLLMBackend` |
| [Skill Backend](components/skill_backend.md) | `predict(inputs) -> Any` | language、GR00T remote/local、OpenPI remote、local policy |
| [Pipeline](components/pipeline.md) | `step()`、`is_terminal()` | `DirectPipeline`、`SkillExecutionPipeline` |
| [Runtime](components/runtime.md) | `run(agent, pipeline, environment, task)` | `SyncRuntime` |
| [Observability](components/observability.md) | episode recorder lifecycle | `LocalEpisodeRecorder` |
| [Environment](components/environment.md) | `reset()`、`execute()`、`close()` | EB-ALFRED、RoboCasa adapters |
| [Evaluation](components/evaluation.md) | benchmark-specific `run()` | `EBAlfredBenchmark`、`RoboCasa365Evaluator` |

## Open Payloads

OmniRoboAgent 只固定运行控制需要的最小 contract：

| Data | Policy |
| --- | --- |
| Planner output | `Any`，由当前 Pipeline 解释和校验 |
| SkillBackend output | `Any`，由 Environment 在使用点校验 |
| Verifier output | 普通 `dict`，语义由 Pipeline 定义 |
| Environment result | 普通 `dict`，字段由 adapter 与 Pipeline 协商 |
| Runtime state | 普通可修改 `dict`，基础字段为 `task`、`observation`、`step` |

开放 payload 不是静默容错。需要的 key、shape、dtype、单位和协议必须在实际使用边界显式校验。

## Dependency Direction

- Pipeline 依赖 Agent Core 和 Environment contract。
- Runtime 依赖 Pipeline、Agent Core 和 Environment contract，但不解释 Planner 或 Verifier 语义。
- Runtime 只调用 Observability contract；recorder 不依赖具体 benchmark SDK。
- Agent Core 可以依赖 backend contract，不依赖具体 benchmark SDK。
- benchmark adapters 和 evaluators 可以依赖对应 SDK，不得把 SDK 类型扩散进 core。
- integrations 用于 ROS2 和 human I/O；当前仍是 planned surface，不属于已实现 benchmark path。

实现替换方式见 [Custom Components](custom_components.md)。
