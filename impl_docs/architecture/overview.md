# OmniRoboAgent Architecture

Status: `v0.1` package architecture and skill execution state graph implemented; EB-ALFRED and pre-graph RoboCasa atomic/composite evaluation verified

## 1. Objective

OmniRoboAgent 是面向长程具身任务的可扩展 Agent 框架。核心目标是提供可复用、可评测的闭环：

```text
Observe -> Plan -> Act -> Verify -> Update or Stop
```

框架需要支持不同 LLM/VLM、规则或学习型 skill、仿真 benchmark 和真实机器人，同时保持推理流程、决策逻辑和运行调度解耦。

当前已实现同步单环境闭环、组合式 `DefaultAgent`、`DirectPipeline`、显式 graph-state `SkillExecutionPipeline`、独立 `SubtaskVerifier`、`SyncRuntime`、OpenAI-compatible LLM、SkillBackend registry、EB-ALFRED，以及 RoboCasa365 Environment/Evaluator、atomic/composite Planner、GR00T remote/local 和 OpenPI remote schema adapter。迁移后 RoboCasa composite 真实 checkpoint smoke、真实 OpenPI checkpoint smoke、async runtime、ROS2 和真机 integration 尚未完成。

## 2. Design Principles

- 各领域 contract 归属对应 package，并与具体模型、ROS2、仿真器和 benchmark 解耦。
- Pipeline 描述流程，AgentCore 负责决策，Runtime 负责运行。
- 长程 skill execution 使用 Pipeline-owned explicit graph state 和确定性条件转换；参考 LangGraph 的设计方式，但不集成 LangGraph 或实现通用 Graph 框架。
- 环境反馈和 verifier 是闭环中的一等对象。
- benchmark 通过 adapter 接入，不成为 core 的特殊分支。
- 模块 payload 保持开放，只固定运行控制所需的最小字段。
- 不按 HTTP、WebSocket 等通信协议派生 Agent 类型，使用组合替换 backend。
- 第一版优先正确、可观测和可评测，再扩展 async、memory 和真机。

## 3. Logical Architecture

```text
 RunConfig --------------------+
                               v
                     +----------------------+
 Task/Integration -> |       Runtime        |
                     | lifecycle/limits/logs|
                     +----------+-----------+
                                |
                                v
                     +----------------------+
                     |       Pipeline       |
                     | call order/control   |
                     +-----+------------+---+
                           |            |
                           v            v
                +----------------+  +---------------------+
 AgentConfig -> | BaseAgent     |  | Environment Adapter |
                | Agent Core    |  | execute action      |
                +-------+-------+  +---------------------+
                        |
          +-------------+-------------+----------------+
          v             v             v                v
      Planner       Verifier       Memory       SkillBackend
          |                                        |
          v                                        v
    LLMBackend                              Policy/Rule Backend
```

## 4. Component Responsibilities

### Runtime

负责 session/episode 生命周期、资源创建与释放、step/timeout 限制、日志和异常捕获。Runtime 维护普通 `state` 字典中的 `task`、`observation`、`step` 三个基础字段，但不解释 Planner、Verifier 或 Action 内容。

Runtime 调用 Pipeline 的终止判断，不固定 Verifier 的 `decision` 取值。

### Pipeline

定义一轮推理的步骤顺序、模块输入构造和状态转换。当前 `DirectPipeline` 从 Runtime state 读取 observation，然后执行 plan、predict action、execute、verify、update。新的 observation 由 `Environment.execute()` 结果返回并写回 state。自定义 Pipeline 可以改变调用顺序、解释任意 Planner 输出，并定义自己的 Verifier decision 语义。

Pipeline 不负责启动模型服务、policy server 或仿真器进程。

### Skill Execution State Graph

`SkillExecutionPipeline` 在 Runtime state 内维护显式 graph state，并使用确定性条件转换管理长程 skill execution。该实现参考 LangGraph 的 state、node 和 conditional edge 思路，但不依赖 LangGraph，也不建立通用 `GraphBuilder`、node registry 或另一套 Runtime。

Runtime 继续负责 episode 外层循环、step/timeout/retry limits、trace、异常终止和资源释放。一次 `Pipeline.step()` 最多完成一个 Environment action/verification cycle，不能在 Pipeline 内启动不受 Runtime 约束的 episode loop。

Graph state 是 Pipeline 在普通 Runtime state 中拥有并验证的一组字段，不新增 `AgentContext`：

```text
active_execution
planner_output
action
environment_result
verification
transition
completed_executions
failed_executions
execution_history
```

`active_execution` 固定保存 `execution_id`、`attempt_id`、attempt/chunk/failure counters、skill/subtask、grounded arguments、expected outcome 和 status。retry 保留 `execution_id` 并增加 `attempt_id`；replan/fallback 创建新的 `execution_id`。详细字段和 transition table 见 [0007 plan](../plans/0007-skill-execution-state-graph.md)。

Node 表示一个有明确输入、输出和副作用边界的逻辑阶段，不要求每个 node 对应独立 class、module 或公共接口。第一版可以保留在 `SkillExecutionPipeline.step()` 及少量必要的 private methods 中；只有能够独立测试或明显降低复杂度时才提取函数。

| Logical node | Responsibility |
| --- | --- |
| `plan` | 仅在没有 active execution 或明确要求 replan 时调用 Planner，校验 proposal，并创建新的 active execution |
| `act` | 使用 active execution 和当前 observation 调用 SkillBackend 生成 action payload |
| `execute` | 调用 Environment 一次，接收新的 observation 和执行结果，不解释 subtask 是否完成 |
| `verify` | 调用 Verifier，根据执行目标和执行前后 evidence 判断 execution 状态 |
| `transition` | 根据 verification、budget 和 task success 执行确定性状态转换，并生成 trace event |
| `recover` | 仅在 failed、stalled 或 retry budget 到达时应用已配置的 retry current、replan、fallback 或 abort 规则 |

Planner 不负责宣告 subtask 完成。Verifier 提供结构化 execution status 和 evidence，Pipeline 将其映射为下一状态。例如：

```text
completed    -> close execution -> record completed -> plan next
in_progress  -> keep execution -> act again
failed       -> recover
uncertain    -> reobserve or reverify
task_success -> terminate
```

当前实现每个 Runtime step 最多调用一次 `Environment.execute()`；uncertain reverify step 调用零次。`completed` 关闭 execution 并在下一 Runtime step 规划，`in_progress` 保持 execution，`failed` 进入 retry/replan/fallback/abort，`task_success` 使用 benchmark authoritative signal 终止。attempt/chunk/uncertain/no-progress budgets 和 repeated/A-B-A loop detection 都由 Pipeline 的 structured state 决定。

### AgentCore

`BaseAgent` 对应 Agent Core，组合 Planner、Verifier、Memory 和 SkillBackend。`DefaultAgent` 只委托这些组件，不固化 Pipeline，也不直接依赖 EB-ALFRED、ROS2、OpenAI SDK 或 OpenPI。

在 package ownership 上，Agent Core 及其内部决策组件统一归入 `agent_core/`。`agents/`、`planners/`、`verifiers/` 和 `memories/` 分别保存对应 contract 与具体实现；每个子 package 使用 `base.py` 定义 contract，并按实现职责增加独立模块。`agent_core/__init__.py` 提供当前组件的统一公开入口。

`BaseAgent` 统一持有 Planner、Verifier、Memory 和 SkillBackend，提供 memory update、healthcheck 和幂等 close lifecycle；继承类只实现 `plan()`、`predict_action()` 和 `verify()`。`DefaultAgent` 保持纯组件委托，公开 class path 和 AgentConfig 不变。Agent 不持有 Pipeline、Runtime 或 Environment。见 [0008 plan](../plans/0008-composable-agent-base.md)。

### Planner

`LanguageSkillPlanner` 从 Environment 提供的语言 skill 列表中选择一个动作。`TaskSkillPlanner` 将 concrete benchmark task name 直接作为 policy skill，用于 RoboCasa atomic task。

`SubtaskSkillPlanner` 用于 composite task。Environment 通过 observation 的 `available_skills` 暴露 atomic macro catalog；Planner 使用 OpenAI-compatible multimodal structured output 生成 `skill`、具体 `subtask`、`grounded_arguments` 和 `expected_outcome`，再通过 AgentConfig 中的可信映射补充 `skill_id`。模型不能直接提供或覆盖 skill ID，也不输出 execution completion status。

### LLMBackend

负责模型请求、图像编码、structured output、timeout、有限重试和 usage 统计。第一版提供支持文本与图像输入的 `OpenAICompatibleLLMBackend`，用于连接用户预先启动的 vLLM 或其他 OpenAI-compatible 服务。

Backend 只关闭客户端连接，不启动或关闭远程服务端进程。

### SkillBackend

接收 Pipeline 构造的普通字典，生成任意 Python Action payload，但不执行动作。当前实现包括 language passthrough、GR00T ZeroMQ remote、OpenPI WebSocket remote 和 in-process local policy。

SkillBackend 不要求统一 Action 基类。字符串、字典、NumPy array、OpenPI action chunk 或自定义对象均可直接返回。

EB-ALFRED 使用 `LanguageSkillBackend`。Pipeline 将 Planner 选择并校验后的单个 language skill 放入 `inputs["skill"]`，backend 返回同一个对象，不解析、不复制，也不执行。

`SkillBackendRegistry` 只将 `groot_remote`、`openpi_remote`、`local` 等稳定配置名映射到具体 backend；模型协议和 schema 仍由 backend 自己处理。自定义实现使用 `class_path` fallback，不做自动 discovery。

GR00T remote 和 local 复用同一个 request builder。Atomic 路径没有显式 `skill_id`，因此严格要求 `skill == task_name`。Composite 路径携带可信非负 `skill_id` 时，request 保留 composite `task`，同时发送 atomic macro `skill`、`skill_id` 和 concrete subtask；Environment 和 Evaluator 不感知 GR00T schema。

### Environment

统一 benchmark、仿真器和真实机器人交互，负责 `reset()`、执行 SkillBackend 输出和 `close()`。当前 contract 没有独立 `observe()`；初始 observation 来自 `reset()`，后续 observation 来自 `execute()` 的结果字典。Environment 自己校验是否接受当前 action payload。

对于 action chunk，`DirectPipeline` 根据自身配置向 Environment 传递 `execute_steps`。`full` 模式传入 `None`，`receding_horizon` 模式传入正整数；具体 Environment 决定如何执行该 action payload。

`RoboCasaEnvironment` 默认将当前 concrete task name 暴露为唯一 `available_skills`，保持 atomic 行为。Composite RunConfig 可以显式提供非空、唯一的 macro skill catalog；Environment 只负责把 catalog 放入 observation，不负责 Planner 选择或 GR00T skill ID 映射。

`environments/base.py` 定义框架环境 contract。依赖 benchmark 或模拟器的 adapter 放在 `environments/benchmarks/<framework>/`，并实现 `Environment` contract；核心执行模块只依赖 `base.py`，不 import 具体 adapter 或可选 SDK。ROS2 与 human text I/O 不属于 benchmark environment ownership，统一归入 `integrations/`。

### Verifier

输入和输出均使用普通字典。输出字段由具体 Verifier 自定义，Pipeline 负责解释；框架不提供全局固定的 Runtime decision 枚举。`EnvironmentVerifier` 为 `DirectPipeline` 透传 benchmark authoritative fields。`SubtaskVerifier` 输出 `in_progress`、`completed`、`failed`、`uncertain`、reason、confidence 和 evidence；它始终优先保留 benchmark `task_success`、environment done 和 action failure，并可选使用 OpenAI-compatible VLM 比较 action 前后 observation。RoboCasa composite 配置每 8 个 action chunks 执行一次视觉语义检查。

### Memory

当前提供 `InMemoryMemory` 和 `JsonlMemory`。此外，`SyncRuntime` 无论使用哪种 Memory 都会写 `trace.jsonl` 和 `result.json`。Semantic、spatial 和 skill experience memory 在出现明确检索需求后增加。当前 episode 的控制状态保存在 Runtime 的 `state` 字典中，不建立 `AgentContext` 类。

计划中的集中 Memory 采用一个组合式 `TieredMemory`，内部区分 bounded visual working memory、append-only event memory 和 bounded text summary。raw frames 只保存在长度为 `K` 的 working set 或独立 artifact 中；长期 record 只保存结构化摘要和引用。Planner/Verifier 必须通过显式 recall 输入读取这些内容，Memory 不得直接修改 proposal、verification 或 transition。该能力尚未实现，见 [0009 plan](../plans/0009-tiered-agent-memory.md)。

## 5. Data Policy

第一版不为每个中间结果建立 class。只有输出稳定、需要跨模块校验或需要持久化时才增加明确数据类型。

| Data | Policy |
|---|---|
| Runtime state | 普通可修改 `dict`，基础字段为 `task`、`observation`、`step` |
| Pipeline graph state | Runtime state 中由当前 Pipeline 拥有并验证的普通字段；不包含 Agent、Environment、model client 或通用 Graph 对象 |
| Planner output | `Any`，由当前 Pipeline 解释 |
| SkillBackend output | `Any`，直接交给 Environment 执行 |
| Verifier input/output | 普通 `dict`，字段由 Verifier 与 Pipeline 协商 |
| Environment result | 普通 `dict`，当前 Pipeline 读取所需字段 |
| Model raw output | 保留 provider 原始结构，需要时由 Planner 转换 |
| Memory event | 可 JSON 序列化的 `dict`，不可序列化 payload 记录摘要或引用 |

具体 benchmark environment 对象只在 `environments/benchmarks/` 和对应 `evals/benchmarks/` 内出现。Environment adapter 负责构造 Pipeline 能理解的 observation 和 result 字典，evaluation runner 负责任务遍历与指标聚合；两者都不能把第三方 SDK 类型扩散到 core。

## 6. Interface Shape

基类只规定调用入口，不限制模块 payload：

```python
class Planner:
    def plan(self, inputs: dict[str, Any]) -> Any: ...

class Verifier:
    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]: ...

class SkillBackend:
    def predict(self, inputs: dict[str, Any]) -> Any: ...

class BaseAgent:
    def plan(self, inputs: dict[str, Any]) -> Any: ...
    def predict_action(self, inputs: dict[str, Any]) -> Any: ...
    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]: ...
    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None: ...

class Environment:
    def reset(self, task: Any) -> Any: ...
    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]: ...
    def close(self) -> None: ...

class Pipeline:
    def step(self, agent: BaseAgent, environment: Environment, state: dict[str, Any]) -> dict[str, Any]: ...
    def is_terminal(self, output: dict[str, Any], state: dict[str, Any]) -> bool: ...

class Runtime:
    def run(self, agent: BaseAgent, pipeline: Pipeline, environment: Environment, task: Any) -> dict[str, Any]: ...
```

默认 Pipeline 可以内部使用 `continue`、`retry`、`success`、`failure`，但这些不是全局 Verifier 协议。自定义 Pipeline 通过 `is_terminal()` 解释自己的输出，Runtime 不读取 Verifier decision。

实现时选择最少的抽象。上述接口先使用简单 ABC；配置、内部工具和一次性逻辑不额外建立继承体系。

## 7. Package Ownership And Dependency Direction

当前 package ownership：

| Package | Responsibility |
| --- | --- |
| `agent_core/agents/` | `BaseAgent` contract 和 Agent 组合实现 |
| `agent_core/planners/` | `Planner` contract 和任务规划实现 |
| `agent_core/verifiers/` | `Verifier` contract 和验证实现 |
| `agent_core/memories/` | `Memory` contract 和记忆实现 |
| `pipelines/` | 调用顺序、模块输入、状态转换和终止语义 |
| `runtimes/` | episode 生命周期、限制、日志、异常捕获和资源释放 |
| `environments/` | 框架 `Environment` contract |
| `environments/benchmarks/` | benchmark 和 simulator environment adapter |
| `evals/benchmarks/` | benchmark task loop、结果保存和指标聚合 |
| `backends/llm/` | `LLMBackend` contract 和模型客户端实现 |
| `backends/skills/` | `SkillBackend` contract 和 policy/rule backend 实现 |
| `integrations/ros2/` | ROS2 连接和 message 转换，planned |
| `integrations/human_interface/` | 人类文本输入输出、确认、反馈和接管接口，planned |

Contract 不集中在单个 `contracts.py`，而是放在所属 package 的 `base.py`。Agent、Planner、Verifier 和 Memory 的 contract 分别归入 `agent_core/` 下对应的子 package，具体实现不能反向定义或持有其他层的 contract。

```text
applications / CLI
        |
        +----------> runtimes
        |               |
        |               +----------> pipelines
        |               +----------> agent_core
        |               +----------> environments
        |
        +----------> evals
        +----------> integrations

pipelines ----------> agent_core
pipelines ----------> environments
agent_core ----------> backends
evals/benchmarks ----> agent_core / pipelines / runtimes
evals/benchmarks ----> environments/benchmarks
environments/benchmarks ----> environments
integrations/ros2 ----------> framework contracts       # planned
integrations/human_interface -> framework contracts  # planned
```

约束：

- `agent_core`、`pipelines`、`runtimes` 和 `environments/base.py` 不 import `evals` 或 `integrations`。
- `agent_core`、`pipelines`、`runtimes` 和 `environments/base.py` 不 import ROS2、LangGraph、OpenAI SDK 或 benchmark SDK。
- `environments/benchmarks` 可以依赖对应 benchmark SDK，并负责 observation、action 和 result 的类型转换。
- `evals/benchmarks` 可以依赖具体 benchmark environment，但 environment 不反向依赖 evaluator。
- `integrations` 只负责 ROS2 和 human text I/O 等外部交互，不保存 benchmark runner 或 environment adapter。
- CLI 只组装实现，不包含核心推理逻辑。

## 8. Configuration And Composition

配置分为两层：

- `AgentConfig`：只定义 Agent Core 的 Planner、LLMBackend、Verifier、Memory 和 SkillBackend。
- `RunConfig`：定义 AgentConfig 路径、Pipeline、Runtime、Environment、任务、限制和输出目录。

所有可替换组件支持通过 `class_path` 和 `init_args` 加载；SkillBackend 还支持最小 `name + init_args` registry：

以下配置反映当前可运行实现：

```yaml
# configs/agents/eb_alfred.yaml
agent:
  class_path: omniroboagent.agent_core.DefaultAgent

planner:
  class_path: omniroboagent.agent_core.LanguageSkillPlanner
  init_args:
    backend:
      class_path: omniroboagent.backends.llm.OpenAICompatibleLLMBackend
      init_args:
        base_url: http://127.0.0.1:8000
        model: Qwen3.5-9B
        timeout_seconds: 120
        max_retries: 2
    max_tokens: 1024
    temperature: 0
    extra_body:
      chat_template_kwargs:
        enable_thinking: false

skill_backend:
  class_path: omniroboagent.backends.skills.LanguageSkillBackend

verifier:
  class_path: omniroboagent.agent_core.EnvironmentVerifier

memory:
  class_path: omniroboagent.agent_core.InMemoryMemory
```

```yaml
# configs/runs/eb_alfred_smoke.yaml
agent_config: ../agents/eb_alfred.yaml

pipeline:
  class_path: omniroboagent.pipelines.DirectPipeline
  init_args:
    action_execution_mode: full

runtime:
  class_path: omniroboagent.runtimes.SyncRuntime
  init_args:
    max_steps: 30
    max_invalid_actions: 10
    max_retries: 10
    timeout_seconds: 1800
    output_dir: runs/eb_alfred_smoke/traces

environment:
  class_path: omniroboagent.environments.benchmarks.embodiedbench.EBAlfredEnvironment
  init_args:
    eval_set: base
    selected_indexes: [0]
    resolution: 300
    display: 1
    embodiedbench_root: benchmarks/EmbodiedBench

benchmark:
  class_path: omniroboagent.evals.benchmarks.embodiedbench.EBAlfredBenchmark
  init_args:
    output_dir: runs/eb_alfred_smoke
```

自定义组件的构造函数参数由各组件自己定义。除显式 `SkillBackendRegistry` 外，不引入自动 discovery、plugin manager 或依赖注入框架。

当前公开路径为：

```text
omniroboagent.agent_core.DefaultAgent
omniroboagent.agent_core.LanguageSkillPlanner
omniroboagent.agent_core.SubtaskSkillPlanner
omniroboagent.agent_core.SubtaskVerifier
omniroboagent.agent_core.EnvironmentVerifier
omniroboagent.agent_core.InMemoryMemory
omniroboagent.pipelines.DirectPipeline
omniroboagent.pipelines.SkillExecutionPipeline
omniroboagent.runtimes.SyncRuntime
omniroboagent.environments.benchmarks.embodiedbench.EBAlfredEnvironment
omniroboagent.evals.benchmarks.embodiedbench.EBAlfredBenchmark
omniroboagent.environments.benchmarks.robocasa.RoboCasaEnvironment
omniroboagent.evals.benchmarks.robocasa.RoboCasa365Evaluator
```

## 9. Remote Service Lifecycle

- vLLM/OpenAI-compatible、GR00T 和 OpenPI policy server 由用户提前启动。
- OmniRoboAgent 启动 episode 前执行客户端 healthcheck。
- HTTP backend 负责 timeout、有限重试、usage 和关闭 HTTP client。
- GR00T backend 使用 ZeroMQ + `torch.save` 协议；OpenPI backend 使用 WebSocket + msgpack 协议。二者负责 healthcheck、timeout、一次重连和关闭客户端连接。
- OmniRoboAgent 不启动、停止或监控远程服务端进程。
- `OpenAICompatibleLLMBackend` 第一版支持文本、单图和多图输入。

Action chunk 执行由 RunConfig 中的 `DirectPipeline.init_args` 控制：

```yaml
pipeline:
  class_path: omniroboagent.pipelines.DirectPipeline
  init_args:
    action_execution_mode: full
```

或：

```yaml
pipeline:
  class_path: omniroboagent.pipelines.DirectPipeline
  init_args:
    action_execution_mode: receding_horizon
    execute_steps: 4
```

`full` 执行完整 chunk；`receding_horizon` 只执行前 `execute_steps` 步，然后重新观察并再次请求 policy。

## 10. Evaluation, Environments And Integrations

### Benchmark Environments

`environments/benchmarks/` 保存具体 benchmark 或 simulator 的执行 adapter。每个 adapter 负责加载任务和 observation、校验并执行 action、整理环境反馈，以及关闭 simulator。当前实现 `EBAlfredEnvironment` 和 `RoboCasaEnvironment`；后者逐步执行连续 action chunk，支持默认 concrete task skill 或显式 macro skill catalog，并使用官方 wrapper 的 `_check_success()` 结果作为 ground truth。

### Benchmark Evaluation

`evals/benchmarks/` 保存 evaluation runner 和指标聚合。runner 组合 Agent、Pipeline、Runtime 和具体 Environment，负责遍历任务、保存逐 episode 结果并生成 summary。当前实现 `EBAlfredBenchmark` 和具体的 `RoboCasa365Evaluator`；尚未抽象通用 Evaluator hierarchy。

Benchmark SDK 作为对应 environment 的独立 Conda 依赖安装。AgentConfig 不包含 benchmark 信息，同一个 Evaluator/Environment 通过替换 AgentConfig 在 GR00T remote、OpenPI remote 和 local policy 之间切换。BEHAVIOR support 在实际接入时再增加，不预先创建空目录。

### External Integrations

`integrations/` 只用于不属于 benchmark environment/evaluation 的外部交互接口：

- `ros2/`：连接 ROS2 node、topic、service、action 和 message；后续实现。
- `human_interface/`：接入人类文本任务输入、输出、确认、纠错、反馈和接管；后续实现。

`ros2` 主要承担机器人系统连接，不包含 Planner 策略。`human_interface` 不被强制建模为 Environment，因为人类可以作为任务来源、Verifier、审批者或 Runtime 控制者。二者当前只定义架构边界，不创建空目录、占位 class 或配置项。

## 11. Repository Structure

当前 `v0.1` package layout：

```text
OmniRoboAgent/
├── impl_docs/
├── rules/
├── src/
│   └── omniroboagent/
│       ├── agent_core/
│       │   ├── __init__.py
│       │   ├── agents/
│       │   │   ├── __init__.py
│       │   │   ├── base.py
│       │   │   └── default.py
│       │   ├── planners/
│       │   │   ├── __init__.py
│       │   │   ├── base.py
│       │   │   ├── language_skill.py
│       │   │   ├── subtask_skill.py
│       │   │   └── task_skill.py
│       │   ├── verifiers/
│       │   │   ├── __init__.py
│       │   │   ├── base.py
│       │   │   └── environment.py
│       │   └── memories/
│       │       ├── __init__.py
│       │       ├── base.py
│       │       ├── in_memory.py
│       │       └── jsonl.py
│       ├── pipelines/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── direct.py
│       │   └── skill_execution.py
│       ├── runtimes/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── sync.py
│       ├── environments/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── benchmarks/
│       │       ├── embodiedbench/
│       │       │   └── eb_alfred.py
│       │       └── robocasa/
│       │           └── environment.py
│       ├── evals/
│       │   └── benchmarks/
│       │       ├── embodiedbench/
│       │       │   └── eb_alfred.py
│       │       └── robocasa/
│       │           └── evaluator.py
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── exceptions.py
│       ├── serialization.py
│       ├── backends/
│       │   ├── llm/
│       │   │   ├── __init__.py
│       │   │   ├── base.py
│       │   │   └── openai_compatible.py
│       │   └── skills/
│       │       ├── __init__.py
│       │       ├── base.py
│       │       ├── groot.py
│       │       ├── language.py
│       │       ├── local.py
│       │       ├── openpi.py
│       │       └── registry.py
│       └── integrations/
│           ├── __init__.py
│           ├── ros2/                # planned, create when implemented
│           └── human_interface/     # planned, create when implemented
├── tests/
│   └── unit/
├── configs/
│   ├── agents/
│   └── runs/
├── scripts/
│   ├── link_robocasa_assets.sh
│   ├── run_eb_alfred_xvfb.sh
│   ├── serve_robocasa_groot.py
│   └── serve_robocasa_openpi.py
├── benchmarks/
│   ├── EmbodiedBench/             # submodule
│   └── RoboCasa/                  # submodule
├── docs/
└── pyproject.toml
```

`ros2/` 和 `human_interface/` 在树中表达 planned ownership，但实际目录只在出现首个实现时创建，避免预先生成空模块。

## 12. First Vertical Slice: EB-ALFRED

EB-ALFRED 提供 RGB observation、离散语言 skill、动作反馈、task progress 和 task success，能够在不训练 VLA 的情况下验证闭环。

首次闭环的数据映射：

```text
EBAlfEnv.reset()              -> state["observation"]
env.language_skill_set       -> available skills
LLM Planner output           -> DirectPipeline interprets one language skill
LanguageSkillBackend         -> returns inputs["skill"] unchanged
EBAlfEnv.step(action)        -> result dict
last_action_success          -> execution verification
task_progress / task_success -> task verification
episode limit                -> Runtime termination
```

第一版不执行模型生成的多步 action list。每执行一个 skill 都重新获取 observation、更新 memory 并触发 verifier，失败时重新规划。

已验证的 `base[0]` smoke 完成 14 个环境 step，生成完整 trace 和 summary。闭环运行成功，但 Planner 重复选择无效动作，任务成功率为 `0.0`、progress 为 `0.3333`。这验证了框架执行路径，不代表 Planner 策略已经达到 benchmark 目标。

## 13. Implementation Boundary

| Capability | Status |
| --- | --- |
| Sync single-environment runtime | Implemented and unit tested |
| OpenAI-compatible text/image backend | Implemented; live vLLM verified |
| Language skill backend | Implemented |
| OpenPI WebSocket client | Implemented with fake client tests; real server smoke pending |
| EB-ALFRED adapter and `base[0]` smoke | Implemented and verified |
| Package architecture | Implemented and unit tested |
| SkillBackend registry | Implemented with explicit names and `class_path` fallback |
| RoboCasa365 Environment/Evaluator | Implemented; atomic and composite GR00T remote/local split matrices verified |
| RoboCasa composite Agent contract | Implemented with `SubtaskSkillPlanner`, visual `SubtaskVerifier` config, macro catalog, trusted skill ID mapping, and shared local/remote request schema; migrated smoke pending |
| Explicit skill-execution graph state and deterministic transitions | Implemented and unit tested; migrated RoboCasa real checkpoint smoke pending |
| RoboCasa OpenPI real checkpoint | Server/client/schema implemented; real smoke pending |
| Resolved config/framework version copied into results | Partial for RoboCasa365: task/component/version metadata implemented, full resolved AgentConfig/RunConfig pending; EB-ALFRED pending |
| Native EmbodiedBench evaluator alignment | Pending |
| Async runtime, ROS2, human interface and real robot | Not implemented |

## 14. Evolution Path

1. 已使用 fake environment 验证 core loop。
2. 已完成 EB-ALFRED 单 episode 同步闭环；正式 episode 集合和原生 evaluator 对齐待完成。
3. 已在不改变行为的前提下完成 Agent Core、Environment、Evaluation 和 Integration ownership 重组。
4. 已接入 RoboCasa 与 GR00T/OpenPI/local VLA backend，并验证 atomic 与 composite Agent split matrix；OpenPI 真实 smoke 和原生 evaluator 对齐待完成。
5. 已为 `SkillExecutionPipeline` 增加显式 graph state、独立 subtask verification、确定性转换和 recovery；下一步验证迁移后的 RoboCasa composite real smoke。
6. 根据真实需求加入 async runtime 和多环境调度。
7. 加入 semantic/spatial memory 和 learned verifier。
8. 通过 RoboNeuron/ROS2 integration 接入真机，并按真实需求实现 human interface。

每一阶段都必须保持上一阶段 benchmark 可运行，不能以未来扩展为由破坏已验证接口。
