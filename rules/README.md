# OmniRoboAgent Project Rules

本文件是整个项目的工程规则。根目录和所有子目录的新代码都必须遵守；第三方 clone 仓库保持上游风格，不做无关修改。

## 1. Requirements

- 需求、输入输出、验收条件或兼容范围不明确时，先向用户确认。
- 不把推测写成实现，不自行扩大任务范围。
- 涉及 benchmark、模型、数据集或脚本时，严格使用用户确认的入口和评测口径。
- 开始较大修改前，在 `docs/plans/` 记录目标、范围、任务和验收条件。

## 2. Implementation

- 优先完成满足当前目标的最小实现。
- 避免过度抽象、过度包装和预先设计未使用的扩展能力。
- 一次性逻辑保持内联；只有复用、独立职责或测试需求明确时才提取 helper。
- 不为形式统一新增无必要的 manager、factory、registry、wrapper 或 base class。
- Registry 仅在同一接口至少存在两个实现且确有动态选择需求时引入。
- 修改应聚焦当前任务，不顺带重构无关模块。

## 3. Architecture

- `core` 只能依赖 Python 标准库和轻量 contract 依赖。
- `core` 不得依赖 ROS2、LangChain、LangGraph、benchmark SDK、模型 SDK 或仿真器。
- 第三方系统通过 `integrations` adapter 接入，core 不得 import 第三方 integration 类型。
- `Pipeline` 独立于 Agent Core，定义调用顺序、模块输入、Verifier decision 语义和状态转换。
- `Runtime` 负责 episode 生命周期、调度、限制、日志和异常终止，不包含 planner 策略。
- `BaseAgent` 对应 Agent Core，组合 Planner、Verifier、Memory 和 SkillBackend，不内置固定 Pipeline。
- `Environment` 负责执行任意 action payload，并在使用点校验是否支持该 payload。
- `SkillBackend` 只生成 action payload，不执行动作，也不负责全局任务规划。
- `Memory` 保存事实和事件，不应暗中改变 planner 决策。
- 不按 HTTP、WebSocket、OpenAI-compatible 等通信协议创建 Agent 子类，通信差异放在 backend 实现中。
- 依赖方向必须从具体实现指向抽象接口，不能反向依赖 integration。

## 4. Data Boundaries

- 只有输出确定、需要跨模块校验或需要稳定持久化时才建立 dataclass、Pydantic model 或固定结果类。
- Planner 输出和 SkillBackend action payload 默认保持开放，可以是 `dict`、字符串、array、tensor 或自定义对象。
- Verifier 和 Environment 结果默认使用普通 `dict`，具体 Pipeline 负责解释所需字段。
- Runtime state 使用普通可修改 `dict`，只保证 `task`、`observation`、`step` 三个基础字段。
- 开放 payload 不等于静默容错；Pipeline 和 Environment 必须在实际使用点验证需要的 key、shape、dtype、单位或协议。
- JSONL 只直接保存可序列化字段；array、tensor、图像和自定义对象保存摘要、独立 artifact 或引用。
- 失败必须显式返回或抛出分类异常，不能用空值静默表示。

## 5. Closed Loop

- 每次动作执行后必须接收环境反馈并进入 verifier。
- Pipeline 解释 Verifier 输出并决定继续、重试或终止；Runtime 不固定全局 decision 枚举。
- planner 不能绕过 verifier 自行宣告 benchmark 成功。
- benchmark 提供真实 success signal 时，第一优先使用该信号作为 ground truth。
- 重试、重新规划、step limit、timeout 和 invalid-action limit 必须可配置并写入 trace。
- episode 的每种退出路径都必须产生明确 termination reason。

## 6. Sync And Async

- 第一版先保证同步单环境闭环正确。
- 不为了未来 async 提前复制整套接口。
- 引入 async runtime 前，必须有真实并发或吞吐需求和对应测试。
- sync 和 async 实现必须产生相同语义的事件和结果。

## 7. Testing

- contract 和纯逻辑必须有 unit tests。
- Pipeline 至少覆盖成功、执行失败、重试、超限和异常终止。
- integration 使用最小 smoke tests，耗时或需要外部服务的测试必须单独标记。
- 修复 bug 时应补充能够复现该 bug 的测试。
- 不把需要付费 API 或完整模拟器的测试放入默认快速测试集。

## 8. Observability

- 每个 episode 使用稳定的 `session_id` 和 `step_id`。
- 记录输入任务、模型配置、Planner 输出摘要、action 摘要、执行结果、verification 和 termination reason。
- 密钥和完整敏感配置不得进入日志。
- benchmark 输出必须包含可复现配置和框架版本信息。
- 日志用于诊断，指标用于比较，两者不能混为一份自由文本。

## 9. Dependencies

- 优先使用标准库和已有依赖。
- 新依赖必须对应明确功能，并说明为什么现有工具无法满足。
- 大型 SDK、ROS2、仿真器和模型运行时必须放在 optional dependency group。
- 不允许 core import optional integration dependency。
- 版本范围应可重现，不能无理由依赖浮动开发分支。
- 第一版使用 `pip + pyproject.toml`，运行环境使用 Conda Python 3.11。
- 远程 vLLM 和 OpenPI server 由用户管理；框架只负责 healthcheck、客户端请求、重连和关闭客户端连接。

## 10. Configuration

- Agent 配置和运行配置分离，AgentConfig 不包含具体 benchmark。
- RunConfig 负责选择 AgentConfig、Pipeline、Runtime、Environment、任务和执行限制。
- 自定义组件通过 dotted `class_path` 和 `init_args` 加载。
- 第一版不引入 registry、plugin manager、factory hierarchy 或依赖注入框架。
- 密钥通过环境变量读取，不直接写入 YAML。

## 11. Documentation

- `docs/TODO.md` 维护项目总状态。
- 开始非简单任务前更新 `docs/plans/`。
- 完成任务后更新状态并在 `docs/changes/` 记录实际修改和验证。
- 公共 contract、运行命令或配置发生变化时，同步更新架构或使用文档。
- 文档描述当前真实行为；未来能力必须明确标记为计划。

## 12. Safety And Repository Hygiene

- 不覆盖或回退用户已有修改。
- 不修改 clone 的参考框架，除非计划明确要求。
- 不提交模型权重、数据集、密钥、运行缓存或大体积生成文件。
- 不执行删除数据、破坏接口或生产环境操作，除非得到明确授权。
- 修改前后检查 `git status`，区分本次变更与用户已有内容。
