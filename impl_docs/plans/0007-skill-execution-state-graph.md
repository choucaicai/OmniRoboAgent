# Skill Execution State Graph

Status: TODO

## Goal

将 `SkillExecutionPipeline` 从 active skill/subtask 和 chunk counters 的隐式控制逻辑，演进为 Pipeline-owned explicit graph state 和确定性条件转换，为长程具身任务提供可验证的 subtask execution、recovery 和 termination 语义。

## Confirmed Decisions

- 不集成 LangGraph，也不增加 LangGraph dependency；只参考 state、node 和 conditional edge 的设计方式。
- `SkillExecutionPipeline` 维护显式 graph state，并对自己使用的字段负责校验和转换。
- Pipeline 使用确定性条件转换，不在 Pipeline 内进行视觉或语义完成判断。
- Planner 提出新的 plan/subtask，Verifier 判断 execution status，Pipeline 根据结构化结果路由。
- Runtime 继续负责 episode 生命周期、外层 step loop、limits、trace、异常终止和资源释放。
- 一次 `Pipeline.step()` 最多执行一个 Environment action/verification cycle。
- node 是逻辑阶段，不要求拆成独立 class、module 或公共接口；不实现通用 Graph engine、builder 或 registry。

## Open Questions

- `active_execution` 第一版必须固定哪些字段：`execution_id`、`attempt_id`、skill、subtask、expected outcome、counters 和 status 中哪些需要跨模块持久化。
- Subtask Verifier 第一版使用规则、VLM 还是组合实现，以及 evidence 的最小结构。
- Recovery 第一版只支持 retry-current/replan/abort，还是同时加入 fallback skill 和 backtrack。

## Scope

- 在现有 `SkillExecutionPipeline` 中定义并维护 explicit graph state。
- 明确 `plan`、`act`、`execute`、`verify`、`transition` 和 `recover` 六个逻辑阶段的输入、输出和副作用。
- 定义 Pipeline 使用的 structured subtask verification contract。
- 实现确定性 transition table、execution identity、attempt/chunk budgets、completed/failed ledger、no-progress 和 loop detection。
- 保持现有 Pipeline、Runtime、Agent、Environment 依赖方向和公开组合方式。
- 添加纯逻辑 unit tests，并保持现有 EB-ALFRED 和 RoboCasa configs 不回归。

## Out of Scope

- 引入 LangGraph、LangChain 或其他 Graph workflow dependency。
- 实现通用 Graph builder、dynamic node registry、plugin discovery 或独立 execution manager。
- 将 episode loop、timeout、global step limit、trace ownership 或资源管理从 Runtime 移入 Pipeline。
- 在本计划中实现 async、多环境并行、ROS2、human interface 或跨 episode semantic/spatial memory。
- 修改具体 benchmark success definition 或正式 evaluation protocol。

## Tasks

1. [ ] 定义 Pipeline-owned graph state 的最小字段、初始化、清理和 JSON trace 摘要规则。
2. [ ] 明确六个逻辑 node 的 contract；简单阶段保持内联，只为独立测试或明显降低复杂度的阶段提取 private method。
3. [ ] 调整 Planner proposal contract，使新 execution 包含可验证的 skill/subtask identity 和 completion target；Planner 不输出完成判定。
4. [ ] 增加 Subtask Verifier contract，输出 `in_progress`、`completed`、`failed`、`uncertain`、reason 和 evidence。
5. [ ] 实现 transition table：completed -> close/record/plan-next，in-progress -> continue，failed -> recover，uncertain -> reobserve/reverify，task-success -> terminate。
6. [ ] 实现 recovery policy、attempt budget、no-progress detection 和 repeated-execution loop detection。
7. [ ] 保证每次 `Pipeline.step()` 最多调用一次 `Environment.execute()`，并继续由 Runtime 累计全局 step/retry/timeout。
8. [ ] 增加 unit tests，覆盖每条 transition、state cleanup、trace event、budget 和 terminal path。
9. [ ] 更新 architecture、TODO、用户接口文档和 change record，并运行 pytest、Ruff、mypy、Markdown links 和 `git diff --check`。

## Acceptance Criteria

- `SkillExecutionPipeline` 的 active execution、verification 和 transition 均在显式 graph state 中可观察和测试。
- 相同 state 和相同 structured Planner/Verifier/Environment result 必须产生相同 transition。
- Pipeline 不通过 raw image、free-text reasoning 或 subtask wording 自行判断 completion。
- Planner 不能绕过 Verifier 宣告 subtask 或 benchmark success。
- Runtime 仍是 episode lifecycle、outer loop、limits、trace 和 resource ownership 的唯一控制层。
- node 设计没有产生六个强制公共类、通用 Graph abstraction 或 LangGraph dependency。
- 现有 `DirectPipeline` 行为和配置保持兼容。
- 现有 EB-ALFRED 与 RoboCasa unit tests 不回归。

## Risks

- node 设计可能被误解为需要大量小函数或 class；实现必须以清晰职责和可测试性为提取标准。
- Pipeline graph state 与 Runtime state 可能出现重复字段；每个字段必须指定唯一 owner。
- Verifier contract 如果仍只有 task-level success，transition table 仍无法形成真实 subtask closed loop。
- recovery 分支过早扩展会形成复杂策略框架；第一版只实现已验证需要的固定分支。
- raw observation/action 不应长期保留在 graph state 或 trace，避免 memory 随 episode 线性增长。
