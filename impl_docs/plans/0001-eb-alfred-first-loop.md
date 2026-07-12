# EB-ALFRED First Closed Loop

Status: `IN_PROGRESS`

## Goal

建立 OmniRoboAgent 的第一个可运行纵向闭环，在 EB-ALFRED 上完成单 episode 和固定 episode 集合评测，验证框架能够根据执行反馈持续规划、验证、更新和停止。

## Confirmed Decisions

- 核心包不依赖 ROS2、O3DE、LangGraph 或具体 benchmark SDK。
- 首个 benchmark 使用 EmbodiedBench 的 EB-ALFRED。
- 第一版使用同步、单进程 runtime。
- 每次只执行一个 skill，执行后必须重新观察和验证。
- 第一版 verifier 使用环境真实信号，不使用 LLM 猜测成功状态。
- 第一版 memory 使用内存状态和 JSONL trace，不引入向量数据库。
- RAI 仅作为设计和代码参考，不直接成为公共接口。
- 使用名为 `omniagent` 的 Conda 环境，Python 版本为 3.11。
- 使用 `pip + pyproject.toml` 管理 Python package。
- `BaseAgent` 对应 Agent Core，`DefaultAgent` 通过组合使用 Planner、Verifier、Memory 和 SkillBackend。
- Pipeline 独立于 Agent Core，并由 RunConfig 选择。
- Planner 输出为 `Any`，具体 Pipeline 负责解释。
- Verifier 输入输出使用普通 `dict`，decision 语义由具体 Pipeline 定义。
- 不定义统一 Action 类，SkillBackend 输出直接交给 Environment。
- Runtime 使用普通 `state` 字典，只维护 `task`、`observation`、`step` 三个基础字段。
- 配置拆分为 `AgentConfig` 和 `RunConfig`，支持 `class_path` 加载自定义组件。
- vLLM 和 OpenPI server 由用户提前启动，框架只管理客户端连接和 healthcheck。
- `OpenAICompatibleLLMBackend` 支持文本、单图和多图输入。
- `OpenPIWebSocketPolicyBackend` 直接兼容 OpenPI WebSocket 协议。
- Action chunk 支持完整执行和可配置 `execute_steps` 的 receding-horizon 执行。
- EB-ALFRED 使用 `LanguageSkillBackend`，原样返回 Pipeline 通过 `inputs["skill"]` 提供的单个 language skill。
- 首个模型使用 `Qwen3.5-9B`，OpenAI-compatible endpoint 为 `http://127.0.0.1:8000`。
- smoke evaluation 使用 EB-ALFRED `base` subset 的 episode index `0`。
- 默认 prompt 参考 EmbodiedBench action-space 表达，但改为每轮只输出一个 skill。
- OpenPI compatibility 固定参考 commit `51fb06be280a967e59292cf63bb597aa3efdab6c`。

## Open Questions

- 正式评测使用哪些 subset 和 episode 数量尚未确认。

## Current Status

- `omniagent-eb`、EB-ALFRED Python dependencies、dataset 和 AI2-THOR binary 已安装并验证。
- `Xvfb :1` + Mesa llvmpipe 可以完成真实 `EBAlfEnv.reset()` 和 episode 执行，不需要 NVIDIA Xorg。
- `ai2thor==2.1.0` 必须固定兼容的 Flask、Werkzeug、Jinja2、MarkupSafe、itsdangerous 和 urllib3 版本，否则 Unity 会停在 `Initialize` 响应。
- `base[0]` smoke 已完成 14 个环境 step，生成完整 trace、result 和 summary；当前 Planner 策略未完成任务。
- 剩余工作是确认正式 episode 集合，并与 EmbodiedBench 原生 evaluator 对齐指标。

## Scope

- 最小 ABC interfaces、`BaseAgent` 和 `DefaultAgent`。
- 独立 `DirectPipeline` 和同步 `Runtime`。
- `AgentConfig`、`RunConfig` 和 `class_path` loader。
- 支持图像的 OpenAI-compatible backend。
- OpenPI WebSocket policy backend 和 action chunk 执行配置。
- EB-ALFRED language skill 透明传递 backend。
- EB-ALFRED environment adapter 和 rule-based verifier。
- JSONL episode trace 与基础 benchmark summary。
- unit tests、mock closed-loop test 和固定 episodes smoke run。

## Out of Scope

- ROS2 和真机部署。
- VLA 连续动作生成和训练。
- 多机器人、多 agent 和分布式调度。
- async/multi-environment runtime。
- vector、semantic 和 spatial memory。
- 通用 plugin discovery、registry 或依赖注入框架。
- 启动、关闭和监控 vLLM/OpenPI 服务端进程。

## Tasks

1. 使用 `pip + pyproject.toml` 初始化 Python package、测试和质量工具。
2. 定义 Planner、Verifier、Memory、SkillBackend、Environment、BaseAgent、Pipeline 和 Runtime 的最小 ABC。
3. 实现 `DefaultAgent`，通过组合委托 Planner、Verifier、Memory 和 SkillBackend。
4. 实现透明传递 `inputs["skill"]` 的 `LanguageSkillBackend`。
5. 实现 `AgentConfig`、`RunConfig` 和简单 `class_path` loader。
6. 实现 `DirectPipeline`，用普通 `state` 字典组织单步调用。
7. 使用 fake planner、verifier、skill backend 和 environment 完成无模型闭环测试。
8. 实现支持文本与图像的 `OpenAICompatibleLLMBackend`。
9. 实现 `OpenPIWebSocketPolicyBackend`，直接使用 OpenPI WebSocket client/protocol。
10. 实现完整 action chunk 和 receding-horizon 两种执行模式。
11. 实现 `EBAlfredEnvironment`，适配 reset、observation、language skill、execute 和 close。
12. 实现基于环境信号、返回普通字典的 `EnvironmentVerifier`。
13. 实现 JSONL trace、summary、healthcheck 和异常终止记录。
14. 运行固定 smoke episode。
15. 与原生 evaluator 对齐正式 episode 集合。
16. 记录结果、失败类型和下一阶段计划。

## Runtime Sequence

```text
Runtime starts episode
  -> Environment.reset()
  -> Runtime initializes state[task, observation, step]
  -> Pipeline builds Planner input dict
  -> Planner returns arbitrary output
  -> Pipeline selects one language skill and builds {"skill": skill}
  -> LanguageSkillBackend returns the same skill object
  -> Environment executes action payload
  -> Pipeline builds Verifier input dict
  -> Verifier returns a free-form dict
  -> Pipeline interprets verifier output and updates state/memory
  -> Pipeline reports whether the run is terminal
  -> Runtime writes result dict and JSONL trace
```

## Acceptance Criteria

- fake environment 可以覆盖成功、动作失败、Pipeline 自定义 decision、重试耗尽和 step limit。
- 每个实际 episode 都生成完整 JSONL trace 和结果字典。
- action failure 后不会继续执行旧的多步计划。
- Runtime 不解析 Verifier decision，只调用 Pipeline 的终止判断。
- Planner、Verifier 和 SkillBackend 的自定义 payload 可以不经过包装直接传递。
- `DefaultAgent` 可以只通过配置替换 LLMBackend 和 SkillBackend。
- `LanguageSkillBackend` 对字符串或其他 language-skill payload 保持对象和值不变，缺少 `skill` 字段时给出明确错误。
- OpenAI-compatible backend 可以发送文本、单图和多图请求。
- OpenPI backend 可以完成 healthcheck、推理、超时、重连和客户端关闭。
- action chunk 可以按配置完整执行或只执行前 `execute_steps` 步。
- benchmark summary 至少包含 success、progress、steps、invalid actions、replans、latency 和 termination reason。
- 实际评测可以通过配置指定 model、endpoint、episodes、limits 和 output directory。
- 自定义组件可以通过 dotted `class_path` 加载。
- 文档能够给出从环境安装到复现实验的完整命令。

## Risks

- EB-ALFRED、AI2-THOR 和 headless display 安装可能成为环境阻塞。
- 模型输出可能不符合当前动态 action space，需要严格结构化校验。
- OpenPI observation/action schema 与目标版本可能变化，需要固定兼容版本并做真实协议测试。
- 完全开放的 payload 无法依靠统一 class 校验，Environment 和 Pipeline 必须在使用点给出清晰错误。
- benchmark 自带 evaluator 可能把 planner 和环境耦合，需要只复用环境接口和指标定义。
- 远程模型的延迟和非确定性会影响重现，需要记录模型参数与原始响应。

## Smoke Result

2026-07-12 使用 `Xvfb :1`、Mesa llvmpipe 和 `Qwen3.5-9B` 运行 `base[0]`：

```text
episodes: 1
success_rate: 0.0
mean_progress: 0.3333333333333333
mean_steps: 14
invalid_actions: 10
replans: 10
latency_seconds: 38.64
termination_reason: environment_done
```

前四个动作执行成功，之后 Planner 重复选择 `pick up the Ladle`，最终触发环境 invalid-action limit。闭环和结果记录已验证，Planner 策略质量仍需改进。
