# OmniRoboAgent Architecture

Status: `v0.1` vertical slice implemented; EB-ALFRED smoke verified; package reorganization planned

## 1. Objective

OmniRoboAgent 是面向长程具身任务的可扩展 Agent 框架。核心目标是提供可复用、可评测的闭环：

```text
Observe -> Plan -> Act -> Verify -> Update or Stop
```

框架需要支持不同 LLM/VLM、规则或学习型 skill、仿真 benchmark 和真实机器人，同时保持推理流程、决策逻辑和运行调度解耦。

当前已实现同步单环境闭环、组合式 `DefaultAgent`、`DirectPipeline`、`SyncRuntime`、OpenAI-compatible LLM、OpenPI WebSocket policy client 和 EB-ALFRED adapter。RoboCasa、真实 OpenPI server、async runtime、ROS2 和真机 integration 尚未实现。

## 2. Design Principles

- 各领域 contract 归属对应 package，并与具体模型、ROS2、仿真器和 benchmark 解耦。
- Pipeline 描述流程，AgentCore 负责决策，Runtime 负责运行。
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

### AgentCore

`BaseAgent` 对应 Agent Core，组合 Planner、Verifier、Memory 和 SkillBackend。`DefaultAgent` 只委托这些组件，不固化 Pipeline，也不直接依赖 EB-ALFRED、ROS2、OpenAI SDK 或 OpenPI。

在 package ownership 上，Agent Core 及其内部决策组件统一归入 `agents/`。当前实现仍是平铺的 `agents.py`、`planners.py`、`verifiers.py` 和 `memory.py`；目标结构将在一次不改变行为的 package 重组中落地。

### LLMBackend

负责模型请求、图像编码、structured output、timeout、有限重试和 usage 统计。第一版提供支持文本与图像输入的 `OpenAICompatibleLLMBackend`，用于连接用户预先启动的 vLLM 或其他 OpenAI-compatible 服务。

Backend 只关闭客户端连接，不启动或关闭远程服务端进程。

### SkillBackend

接收 Pipeline 构造的普通字典，生成任意 Python Action payload，但不执行动作。第一版远程 policy 实现为 `OpenPIWebSocketPolicyBackend`，直接兼容 OpenPI WebSocket client/server 协议。

SkillBackend 不要求统一 Action 基类。字符串、字典、NumPy array、OpenPI action chunk 或自定义对象均可直接返回。

EB-ALFRED 使用 `LanguageSkillBackend`。Pipeline 将 Planner 选择并校验后的单个 language skill 放入 `inputs["skill"]`，backend 返回同一个对象，不解析、不复制，也不执行。

### Environment

统一 benchmark、仿真器和真实机器人交互，负责 `reset()`、执行 SkillBackend 输出和 `close()`。当前 contract 没有独立 `observe()`；初始 observation 来自 `reset()`，后续 observation 来自 `execute()` 的结果字典。Environment 自己校验是否接受当前 action payload。

对于 action chunk，`DirectPipeline` 根据自身配置向 Environment 传递 `execute_steps`。`full` 模式传入 `None`，`receding_horizon` 模式传入正整数；具体 Environment 决定如何执行该 action payload。

`environments/` 只定义框架环境 contract 和不依赖外部 SDK 的内置实现。依赖 benchmark、模拟器、ROS2 或真实机器人系统的 adapter 属于 `integrations/`，并实现 `Environment` contract。依赖方向只能是 `integrations -> environments`。

### Verifier

输入和输出均使用普通字典。输出字段由具体 Verifier 自定义，Pipeline 负责解释；框架不提供全局固定的 decision 枚举。第一版 `EnvironmentVerifier` 优先使用 benchmark 的 authoritative success signal，后续可增加 `VLMVerifier`、`HumanVerifier` 和组合实现。

### Memory

当前提供 `InMemoryMemory` 和 `JsonlMemory`。此外，`SyncRuntime` 无论使用哪种 Memory 都会写 `trace.jsonl` 和 `result.json`。Semantic、spatial 和 skill experience memory 在出现明确检索需求后增加。当前 episode 的控制状态保存在 Runtime 的 `state` 字典中，不建立 `AgentContext` 类。

## 5. Data Policy

第一版不为每个中间结果建立 class。只有输出稳定、需要跨模块校验或需要持久化时才增加明确数据类型。

| Data | Policy |
|---|---|
| Runtime state | 普通可修改 `dict`，基础字段为 `task`、`observation`、`step` |
| Planner output | `Any`，由当前 Pipeline 解释 |
| SkillBackend output | `Any`，直接交给 Environment 执行 |
| Verifier input/output | 普通 `dict`，字段由 Verifier 与 Pipeline 协商 |
| Environment result | 普通 `dict`，当前 Pipeline 读取所需字段 |
| Model raw output | 保留 provider 原始结构，需要时由 Planner 转换 |
| Memory event | 可 JSON 序列化的 `dict`，不可序列化 payload 记录摘要或引用 |

具体 benchmark 对象只在 integration 内出现。Integration 负责构造 Pipeline 能理解的 observation 和 result 字典，不把第三方 SDK 类型扩散到其他模块。

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

目标 package ownership：

| Package | Responsibility |
| --- | --- |
| `agents/` | Agent Core、Planner、Verifier 和 Memory |
| `pipelines/` | 调用顺序、模块输入、状态转换和终止语义 |
| `runtimes/` | episode 生命周期、限制、日志、异常捕获和资源释放 |
| `environments/` | 框架 `Environment` contract |
| `backends/llm/` | `LLMBackend` contract 和模型客户端实现 |
| `backends/skills/` | `SkillBackend` contract 和 policy/rule backend 实现 |
| `integrations/benchmarks/` | benchmark、模拟器和 evaluator adapter |
| `integrations/ros2/` | ROS2 连接和 message 转换，planned |
| `integrations/human_interface/` | 人类输入、确认、反馈和接管接口，planned |

Contract 不再集中在单个 `contracts.py`，而是放回所属 package 的 `base.py`。`agents` 内部当前实现较少，因此 Planner、Verifier 和 Memory 各使用一个直接模块，不再增加子 package 层级。

```text
applications / CLI
        |
        +----------> runtimes
        |               |
        |               +----------> pipelines
        |               +----------> agents
        |               +----------> environments
        |
        +----------> integrations

pipelines ----------> agents
pipelines ----------> environments
agents -------------> backends
integrations/benchmarks ----> environments
integrations/ros2 ----------> environments       # planned
integrations/human_interface -> framework contracts  # planned
```

约束：

- `agents`、`pipelines`、`runtimes` 和 `environments` 不 import `integrations`。
- `agents`、`pipelines`、`runtimes` 和 `environments` 不 import ROS2、LangGraph、OpenAI SDK 或 benchmark SDK。
- `integrations` 依赖框架 contract，负责第三方 task、observation、action 和 result 的类型转换。
- `environments` 不反向依赖任何具体 benchmark、ROS2 或 human interface。
- CLI 只组装实现，不包含核心推理逻辑。

## 8. Configuration And Composition

配置分为两层：

- `AgentConfig`：只定义 Agent Core 的 Planner、LLMBackend、Verifier、Memory 和 SkillBackend。
- `RunConfig`：定义 AgentConfig 路径、Pipeline、Runtime、Environment、任务、限制和输出目录。

所有可替换组件支持通过 `class_path` 和 `init_args` 加载：

以下配置反映当前可运行实现。package 重组完成前，不提前修改 dotted `class_path`：

```yaml
# configs/agents/eb_alfred.yaml
agent:
  class_path: omniroboagent.agents.DefaultAgent

planner:
  class_path: omniroboagent.planners.LanguageSkillPlanner
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
  class_path: omniroboagent.verifiers.EnvironmentVerifier

memory:
  class_path: omniroboagent.memory.InMemoryMemory
```

```yaml
# configs/runs/eb_alfred_smoke.yaml
agent_config: ../agents/eb_alfred.yaml

pipeline:
  class_path: omniroboagent.pipelines.DirectPipeline
  init_args:
    action_execution_mode: full

runtime:
  class_path: omniroboagent.runtime.SyncRuntime
  init_args:
    max_steps: 30
    max_invalid_actions: 10
    max_retries: 10
    timeout_seconds: 1800
    output_dir: runs/eb_alfred_smoke/traces

environment:
  class_path: omniroboagent.integrations.embodiedbench.EBAlfredEnvironment
  init_args:
    eval_set: base
    selected_indexes: [0]
    resolution: 300
    display: 1
    embodiedbench_root: benchmarks/EmbodiedBench

benchmark:
  class_path: omniroboagent.integrations.embodiedbench.EBAlfredBenchmark
  init_args:
    output_dir: runs/eb_alfred_smoke
```

自定义组件的构造函数参数由各组件自己定义。第一版只实现简单 dotted-path import，不引入 registry、plugin manager 或依赖注入框架。

package 重组完成后，目标公开路径为：

```text
omniroboagent.agents.DefaultAgent
omniroboagent.agents.LanguageSkillPlanner
omniroboagent.agents.EnvironmentVerifier
omniroboagent.agents.InMemoryMemory
omniroboagent.pipelines.DirectPipeline
omniroboagent.runtimes.SyncRuntime
omniroboagent.integrations.benchmarks.embodiedbench.EBAlfredEnvironment
omniroboagent.integrations.benchmarks.embodiedbench.EBAlfredBenchmark
```

## 9. Remote Service Lifecycle

- vLLM/OpenAI-compatible server 和 OpenPI policy server 由用户提前启动。
- OmniRoboAgent 启动 episode 前执行客户端 healthcheck。
- HTTP backend 负责 timeout、有限重试、usage 和关闭 HTTP client。
- OpenPI backend 直接使用 OpenPI WebSocket 协议，负责连接、timeout、断线重连和关闭客户端连接。
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

## 10. Integrations

`integrations/` 是第三方系统接入层，不定义框架核心 contract。它按接入类型分组：

- `benchmarks/`：接入 benchmark、模拟器、dataset task loader 和 evaluator。
- `ros2/`：连接 ROS2 node、topic、service、action 和 message；后续实现。
- `human_interface/`：接入人类任务输入、确认、纠错、反馈和接管；后续实现。

`ros2` 主要承担机器人系统连接，不包含 Planner 策略。`human_interface` 不被强制建模为 Environment，因为人类可以作为任务来源、Verifier、审批者或 Runtime 控制者。二者当前只定义架构边界，不创建空目录、占位 class 或配置项。

### Benchmark Integrations

具体 benchmark 不进入 core。每个 integration 负责：

- 枚举或加载任务。
- 创建并关闭具体 environment。
- 将 benchmark observation 交给 Pipeline。
- 接收任意 action payload，并转换为 benchmark 可执行动作。
- 将执行反馈整理为普通字典。
- 聚合 benchmark 指标和保存原始结果。

当前只实现 `integrations/embodiedbench/eb_alfred.py`，其中包含 `EBAlfredEnvironment` 和 `EBAlfredBenchmark`。目标位置是 `integrations/benchmarks/embodiedbench/eb_alfred.py`，将在 package 重组时迁移。RoboCasa 和 BEHAVIOR adapters 在实际接入时再创建，不预先生成空目录。

Benchmark SDK 作为对应 integration 的 optional dependency 安装。AgentConfig 不包含 benchmark 信息，同一个 AgentConfig 可以被多个 RunConfig 复用。

## 11. Repository Structure

当前 `v0.1` 使用平铺的 `agents.py`、`planners.py`、`verifiers.py`、`memory.py`、`pipelines.py`、`runtime.py` 和 `contracts.py`。以下是已确认但尚未实施的目标 package layout：

```text
OmniRoboAgent/
├── impl_docs/
├── rules/
├── src/
│   └── omniroboagent/
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   ├── default.py
│       │   ├── planners.py
│       │   ├── verifiers.py
│       │   └── memory.py
│       ├── pipelines/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── direct.py
│       ├── runtimes/
│       │   ├── __init__.py
│       │   ├── base.py
│       │   └── sync.py
│       ├── environments/
│       │   ├── __init__.py
│       │   └── base.py
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
│       │       ├── language.py
│       │       └── openpi.py
│       └── integrations/
│           ├── benchmarks/
│           │   └── embodiedbench/
│           │       ├── __init__.py
│           │       └── eb_alfred.py
│           ├── ros2/                # planned, create when implemented
│           └── human_interface/     # planned, create when implemented
├── tests/
│   └── unit/
├── configs/
│   ├── agents/
│   └── runs/
├── scripts/
│   └── run_eb_alfred_xvfb.sh
├── docs/
└── pyproject.toml
```

`ros2/` 和 `human_interface/` 在树中表达目标 ownership，但实际目录只在出现首个实现时创建，避免预先生成空模块。package 重组必须独立进行，不与 Pipeline、Runtime 或 payload 行为修改混合。

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
| Target package architecture | Documented; source migration pending |
| Resolved config/framework version copied into results | Not implemented |
| Native EmbodiedBench evaluator alignment | Pending |
| RoboCasa, async runtime, ROS2, human interface and real robot | Not implemented |

## 14. Evolution Path

1. 已使用 fake environment 验证 core loop。
2. 已完成 EB-ALFRED 单 episode 同步闭环；正式 episode 集合和原生 evaluator 对齐待完成。
3. 在不改变行为的前提下完成 core 和 integrations package 重组。
4. 接入 RoboCasa 与 VLA/policy skill backend。
5. 根据真实需求加入 async runtime 和多环境调度。
6. 加入 semantic/spatial memory 和 learned verifier。
7. 通过 RoboNeuron/ROS2 integration 接入真机，并按真实需求实现 human interface。

每一阶段都必须保持上一阶段 benchmark 可运行，不能以未来扩展为由破坏已验证接口。
