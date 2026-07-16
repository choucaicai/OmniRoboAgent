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
- [x] `DONE` RoboCasa OpenPI client 固定到兼容 NumPy 2 的 fork commit `5a6beda9ff99da30b4e1b59320f6a32971d7c397`。
- [ ] `TODO` 确认首轮 EB-ALFRED episode 列表和正式评测数量。

## 1. Project Foundation

- [x] `DONE` 创建项目级 `AGENTS.md`。
- [x] `DONE` 创建并维护面向通用框架用户的 `docs/` / `impl_docs/` 文档 skill 与项目规则。
- [x] `DONE` 编写整体架构设计文档。
- [x] `DONE` 创建 Python package 和 `pyproject.toml`。
- [x] `DONE` 创建最小命令行入口。
- [x] `DONE` 配置 Ruff、mypy 和 pytest。
- [x] `DONE` 忽略 Python 工具缓存和本地 `reference_repo/` 参考仓库。
- [x] `DONE` 配置 benchmark submodule，并在根 README 记录 clone、安装和启动流程。
- [x] `DONE` 使用 Docsify 将 `docs/` 作为 GitHub Pages Markdown 文档站。
- [x] `DONE` 将 `impl_docs/` 和 `docs/` 与当前实现、配置及 smoke 结果同步（[计划](plans/0002-documentation-sync.md)）。
- [x] `DONE` 按通用框架使用路径重组用户文档，并拆分 Agent Core 与其他 framework components（[计划](plans/0011-user-doc-information-architecture.md)）。
- [x] `DONE` 按已确认的 package architecture 重组 core 与 integrations，保持现有行为不变（[计划](plans/0003-package-architecture.md)）。
- [x] `DONE` 将 Agent Core 重组为按组件类型划分的子 packages（[计划](plans/0004-agent-core-subpackages.md)）。
- [x] `DONE` 拆分 benchmark evaluation、environment 和 external integration ownership（[计划](plans/0005-eval-environment-ownership.md)）。
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
- [x] `DONE` 实现独立 observability package，生成 Agent trace、episode video 和 artifact manifest（[计划](plans/0012-episode-observability-artifacts.md)）。

## 5. Embodied Agent Skill Execution

- [x] `DONE` 将 `SkillExecutionPipeline` 演进为显式 graph state 和确定性条件转换（[计划](plans/0007-skill-execution-state-graph.md)）。
- [x] `DONE` 定义 Pipeline-owned `active_execution`、稳定 execution identity、attempt/chunk counters 和 completed/failed ledger，同时保持 Runtime 只负责 episode 生命周期。
- [x] `DONE` 将 Planner proposal、SkillBackend action、Environment result、Verifier result 和 transition event 的边界写成可验证 contract；node 只是逻辑阶段，不要求拆成独立 class 或 module。
- [x] `DONE` 实现独立 subtask verifier，输出 `in_progress`、`completed`、`failed`、`uncertain` 和 evidence；Planner 不再负责宣告完成。
- [x] `DONE` 实现确定性 transition/recovery：continue、close-and-plan-next、retry-current、replan、fallback、abort，以及 no-progress/loop detection。
- [x] `DONE` 增加 graph-state 和 transition unit tests，覆盖正常完成、继续、失败、uncertain、budget exhausted、recovery 和 terminal task success。

## 5.1 Agent Core And Memory Evolution

- [x] `DONE` 将 `BaseAgent` 演进为统一组件 ownership 和 lifecycle 的组合式抽象基类，同时保持 `DefaultAgent` 配置兼容（[计划](plans/0008-composable-agent-base.md)）。
- [x] `DONE` 实现 bounded visual working memory、长期 event memory 和 bounded text summary 的集中分层 Memory（[计划](plans/0009-tiered-agent-memory.md)）。
- [x] `DONE` 为 Planner/Verifier 提供显式 memory recall 输入，不允许 Memory 隐式修改 decision 或 Pipeline transition。
- [x] `DONE` 为 `TieredMemory` 增加关键事件记忆和视觉 artifacts，记录 subtask completion/failure、recovery 和 task terminal，并显式提供给 Planner/Verifier（[计划](plans/0010-key-event-memory.md)）。

## 6. Backend Support

- [x] `DONE` 实现透明传递 `inputs["skill"]` 的 `LanguageSkillBackend`。
- [x] `DONE` 实现支持文本、单图和多图的 `OpenAICompatibleLLMBackend`。
- [x] `DONE` 实现 OpenAI-compatible healthcheck、timeout、有限重试和客户端关闭。
- [x] `DONE` 记录 LLM latency、token usage 和模型错误。
- [x] `DONE` 实现直接兼容 OpenPI 协议的 `OpenPIWebSocketPolicyBackend`。
- [x] `DONE` 实现 OpenPI healthcheck、timeout、断线重连和客户端关闭。
- [x] `DONE` 实现 action chunk full 模式的 `execute_steps=None` 传递语义。
- [x] `DONE` 实现 action chunk receding-horizon 模式和正整数 `execute_steps` 传递语义。
- [x] `DONE` 在 RoboCasa GR00T real rollouts 中验证 full action chunk 的连续控制执行。
- [ ] `TODO` 使用真实 OpenPI checkpoint 在 RoboCasa 中验证 receding-horizon action chunk；当前只有 fake/schema test 和可运行配置。
- [x] `DONE` 实现最小 `SkillBackendRegistry`，内置 GR00T remote、OpenPI remote 和 local，并保留 `class_path` fallback。

## 7. EB-ALFRED Environment And Evaluation

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

## 8. First Benchmark Acceptance

- [x] `DONE` 完成固定 `base[0]` episode 的真实 smoke run。
- [x] `DONE` smoke episode 产生明确 `environment_done` 终止原因和完整 trace。
- [x] `DONE` 失败动作进入 verify 和 replan，不继续执行旧计划。
- [x] `DONE` 输出 success rate、progress、steps、invalid actions、replans 和 latency。
- [x] `DONE` 配置和文档记录 model、prompt、依赖版本、episode 和运行命令。
- [x] `DONE` 记录首份 smoke 指标和重复无效动作失败类型。

## 9. RoboCasa365 Evaluation

- [ ] `IN_PROGRESS` 实现 RoboCasa365 evaluation-first Agent + VLA case（[计划](plans/0006-robocasa365-evaluation.md)）。
- [x] `DONE` 添加固定 commit 的 `benchmarks/RoboCasa` submodule，并提供不覆盖已有数据的本地 assets 软链流程。
- [x] `DONE` 实现 `RoboCasaEnvironment` 和 `RoboCasa365Evaluator`，支持官方 `task_set`、`pretrain` / `target` split 和可复现 smoke overrides。
- [x] `DONE` 实现 graph-state `SkillExecutionPipeline`，在每个 action chunk 后验证，并按 structured status continue、close、recover 或 terminate。
- [x] `DONE` 实现 GR00T remote server/backend、OpenPI remote server/backend 和 local in-process backend 三种 policy mode。
- [x] `DONE` 完成 GR00T remote/local 单任务 smoke，并在 `atomic_seen` 的同一组 5 个 task 上验证 `pretrain` / `target` split；保存 resolved config、episode trace 和 summary。
- [x] `DONE` 接通 LLM Agent 的 composite-to-atomic skill contract，并完成 `composite_seen` / `composite_unseen` 的 GR00T remote/local split matrix；40 episodes 为 1 success、0 exception，用户文档记录真实 subtask sequence 和失败模式。
- [x] `DONE` RoboCasa composite Agent 配置已接入独立 visual `SubtaskVerifier`、`TieredMemory(K=4)` 和 structured execution evidence；固定 `DeliverStraw` real smoke 完成 12 次 visual checks，正确关闭 `Open_Door`，但最终 success 仍为 0。
- [ ] `TODO` 拆分 Planner/policy/Environment/benchmark 错误指标，并验证 macro skill catalog、skill 和 trusted skill ID 一致性。
- [ ] `TODO` 重跑 RoboCasa real smoke 审计 key-event artifact 数量/内容、peak RSS 和 Verifier backend usage/latency；调整 semantic-equivalent repeated execution detection，并配置 `max_no_progress_steps` / `max_replans` 后复跑 fixed matrix。
- [ ] `TODO` Evaluator resume、completed-episode skip 和 atomic result write 继续在 RoboCasa plan 中跟踪。
- [ ] `TODO` 使用真实 OpenPI checkpoint 完成相同 task/scenario smoke；当前只有 server/client/schema 和 fake protocol test。
- [ ] `TODO` 将已验证的 custom GR00T policy source 固定到其他用户可获取的 commit/package，并记录 checkpoint digest、policy RNG、Conda/CUDA/GPU 和 dependency lock。
- [ ] `TODO` 将正式 split matrix 的 experiment manifest/RunConfig 纳入版本控制，并在结果中保存完整 resolved AgentConfig/RunConfig、Planner prompt/schema、skill map 和 camera 参数。
- [x] `DONE` 补充 RoboCasa 官方 assets 安装、可选本地软链、server、本地运行、evaluation 配置和 troubleshooting 用户文档。
- [ ] `TODO` 先确认正式 RoboCasa task-set scope，再与官方 evaluator 对齐随机 50-scenario manifest、reset identity、low-level horizon 和 aggregation；从 environment horizon 派生或校验 Runtime action-chunk budget，随后增加可控 worker/GPU 并行。

## 10. Later Extensions

- [ ] `TODO` 评估 RoboNeuron action contract 与开放 action payload 的兼容方式。
- [ ] `TODO` 接入本地 LLM/VLM planner backend（不含 RoboCasa365 计划中的 local VLA policy）。
- [ ] `TODO` 在同步闭环稳定后实现 async runtime。
- [ ] `TODO` 在真实检索需求出现后实现 semantic/spatial memory。
- [x] `DONE` 第二个 benchmark 接入后继续复用统一 CLI/RunConfig 入口，同时保留各 benchmark 的具体 runner，不引入无需求的 Evaluator hierarchy。
- [ ] `TODO` 评估 BEHAVIOR-1K adapter。
- [ ] `TODO` 设计 ROS2 和 human text I/O integrations，保持 core 不依赖外部通信实现。
