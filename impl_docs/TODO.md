# OmniRoboAgent Task List

本文档是项目工作的唯一总清单。详细方案放在 `impl_docs/plans/`，完成记录放在 `impl_docs/changes/`。

## 0. Project Decisions

- [x] `DONE` 使用 Python 3.11，Conda 环境名为 `omniagent`。
- [x] `DONE` 使用 `uv + pyproject.toml + uv.lock` 管理 Python package 和依赖。
- [x] `DONE` 第一版允许连接用户预先启动的远程模型和 policy 服务，但不管理服务端进程。
- [x] `DONE` 首个 LLM/VLM backend 使用支持图像的 OpenAI-compatible 接口。
- [x] `DONE` 首个远程 policy backend 直接兼容 OpenPI WebSocket 协议。
- [ ] `TODO` 确认项目许可证。
- [x] `DONE` 首个模型使用 `Qwen3.5-9B`，OpenAI-compatible endpoint 为 `http://127.0.0.1:8000`。
- [x] `DONE` OpenPI client protocol 固定参考 commit `51fb06be280a967e59292cf63bb597aa3efdab6c`。
- [ ] `TODO` 确认首轮 EB-ALFRED episode 列表和正式评测数量。

## 1. Project Foundation

- [x] `DONE` 创建项目级 `AGENTS.md`。
- [x] `DONE` 创建文档维护结构和项目规则。
- [x] `DONE` 编写整体架构设计文档。
- [x] `DONE` 创建 Python package 和 `pyproject.toml`。
- [x] `DONE` 创建最小命令行入口。
- [x] `DONE` 配置 Ruff、mypy 和 pytest。
- [x] `DONE` 忽略 Python 工具缓存和本地 `reference_repo/` 参考仓库。
- [x] `DONE` 配置 benchmark submodule，并在根 README 记录 clone、安装和启动流程。
- [x] `DONE` 使用 Docsify 和 GitHub Pages Actions 发布 `tutorial_docs/` Markdown 文档站。
- [x] `DONE` 将 `impl_docs/` 和 `tutorial_docs/` 与当前实现、配置及 smoke 结果同步（[计划](plans/0002-documentation-sync.md)）。
- [ ] `TODO` 按已确认的 package architecture 重组 core 与 integrations，保持现有行为不变（[计划](plans/0003-package-architecture.md)）。
- [ ] `TODO` 配置基础 CI，执行 lint、type check 和 unit tests。

## 2. Data And Configuration Policy

- [x] `DONE` 实现 Runtime 普通 `state` 字典，基础字段为 `task`、`observation`、`step`。
- [x] `DONE` 允许 Planner 输出和 SkillBackend action payload 使用任意 Python 类型。
- [x] `DONE` 使用普通 `dict` 作为 Verifier 和 Environment 结果，不建立固定结果类。
- [x] `DONE` 定义 JSONL event 中不可序列化 payload 的摘要或引用规则。
- [x] `DONE` 定义独立 `AgentConfig` 和 `RunConfig`。
- [x] `DONE` 实现 dotted `class_path + init_args` 配置加载。
- [x] `DONE` 验证错误配置和不兼容 action 时能够产生清晰错误。

## 3. Core Interfaces

- [x] `DONE` 定义与具体 SDK 无关的 `LLMBackend` interface。
- [x] `DONE` 定义 `Planner` interface。
- [x] `DONE` 定义 `Verifier` interface。
- [x] `DONE` 定义 `Memory` interface。
- [x] `DONE` 定义 `SkillBackend` interface。
- [x] `DONE` 定义 `Environment` interface。
- [x] `DONE` 定义对应 Agent Core 的 `BaseAgent`，并实现组合式 `DefaultAgent`。
- [x] `DONE` 定义 `Pipeline` 单步状态转换接口。
- [x] `DONE` 由 Pipeline 定义 Verifier decision 语义和终止判断。
- [x] `DONE` 定义 `Runtime` episode 生命周期接口。
- [x] `DONE` 使用 fake implementations 验证各接口可以独立替换。

## 4. First Closed-Loop Implementation

- [x] `DONE` 实现 `DefaultAgent`，组合 planner、verifier、memory 和 skill backend。
- [x] `DONE` 实现独立 `DirectPipeline`：plan、predict、execute、verify、update observation/state。
- [x] `DONE` 实现单进程同步 `Runtime`。
- [x] `DONE` Runtime 只维护基础 state、循环和限制，不解释 Verifier 或 Action。
- [x] `DONE` 实现内存态 working memory。
- [x] `DONE` 实现 append-only JSONL episodic memory。
- [x] `DONE` 实现结构化 event、日志和错误记录。
- [x] `DONE` 实现 step、invalid action、retry 和 wall-time 限制。
- [x] `DONE` 实现 mock environment 闭环集成测试。

## 5. Backend Support

- [x] `DONE` 实现透明传递 `inputs["skill"]` 的 `LanguageSkillBackend`。
- [x] `DONE` 实现支持文本、单图和多图的 `OpenAICompatibleLLMBackend`。
- [x] `DONE` 实现 OpenAI-compatible healthcheck、timeout、有限重试和客户端关闭。
- [x] `DONE` 记录 LLM latency、token usage 和模型错误。
- [x] `DONE` 实现直接兼容 OpenPI 协议的 `OpenPIWebSocketPolicyBackend`。
- [x] `DONE` 实现 OpenPI healthcheck、timeout、断线重连和客户端关闭。
- [x] `DONE` 实现 action chunk full 模式的 `execute_steps=None` 传递语义。
- [x] `DONE` 实现 action chunk receding-horizon 模式和正整数 `execute_steps` 传递语义。
- [ ] `TODO` 在首个连续控制 Environment 中验证 full/receding-horizon action chunk 的实际执行。
- [ ] `TODO` 在出现第二个 backend 后再实现 backend registry。

## 6. EB-ALFRED Integration

- [x] `DONE` 安装并验证 EmbodiedBench、EB-ALFRED dataset、AI2-THOR binary、兼容依赖和 Xvfb 软件渲染环境。
- [x] `DONE` 实现 `EBAlfredEnvironment` adapter。
- [x] `DONE` 将 `language_skill_set` 提供给 DirectPipeline 和默认 Planner。
- [x] `DONE` 将 SkillBackend 的字符串 action 交给 `env.step()` 执行。
- [x] `DONE` 将 `env.step()` 输出整理为普通结果字典。
- [x] `DONE` 实现基于 `task_success`、`task_progress` 和 `last_action_success` 的 verifier。
- [x] `DONE` 每轮只执行一个 skill，执行后强制重新观察和验证。
- [x] `DONE` 保存 episode trace 和最终指标。
- [ ] `TODO` 将 resolved AgentConfig、RunConfig 和框架版本写入 benchmark 输出目录。
- [ ] `TODO` 与 EmbodiedBench 原生 evaluator 在相同 episodes 上对齐结果。

详细方案：[0001-eb-alfred-first-loop.md](plans/0001-eb-alfred-first-loop.md)

## 7. First Benchmark Acceptance

- [x] `DONE` 完成固定 `base[0]` episode 的真实 smoke run。
- [x] `DONE` smoke episode 产生明确 `environment_done` 终止原因和完整 trace。
- [x] `DONE` 失败动作进入 verify 和 replan，不继续执行旧计划。
- [x] `DONE` 输出 success rate、progress、steps、invalid actions、replans 和 latency。
- [x] `DONE` 配置和文档记录 model、prompt、依赖版本、episode 和运行命令。
- [x] `DONE` 记录首份 smoke 指标和重复无效动作失败类型。

## 8. Later Integrations

- [ ] `TODO` 接入 RoboCasa，验证连续控制或 VLA skill backend。
- [ ] `TODO` 评估 RoboNeuron action contract 与开放 action payload 的兼容方式。
- [ ] `TODO` 接入本地模型 backend。
- [ ] `TODO` 在同步闭环稳定后实现 async runtime。
- [ ] `TODO` 在真实检索需求出现后实现 semantic/spatial memory。
- [ ] `TODO` 在第二个 benchmark 接入后抽象统一 benchmark runner。
- [ ] `TODO` 评估 BEHAVIOR-1K adapter。
- [ ] `TODO` 设计 ROS2 和真机 integration，保持 core 不依赖 ROS2。
