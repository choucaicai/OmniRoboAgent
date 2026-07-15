# Skill Execution State Graph

Status: IN_PROGRESS

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

## Resolved Contract

Pipeline-owned state 继续使用 Runtime 的普通 `state` 字典，不新增 graph class：

```text
active_execution
verification
transition
completed_executions
failed_executions
execution_history
```

`active_execution` 第一版固定以下字段：

```text
execution_id / attempt_id / attempt_count
skill / skill_id / subtask
grounded_arguments / expected_outcome
status
chunk_count / attempt_chunk_count / failure_count
uncertain_count / no_progress_count / last_progress_marker
planner_output
```

- `execution_id` 在一次 episode 内稳定；retry 只增加 `attempt_id`，replan/fallback 创建新的 `execution_id`。
- Planner proposal 只包含 `skill`、可选可信 `skill_id`、`subtask`、`grounded_arguments` 和 `expected_outcome`；不再输出 completion status。
- Subtask Verifier 输出 `execution_status`、`reason`、`confidence`、`evidence`，并透传 benchmark authoritative `task_success`。
- Pipeline 只解释 structured result，不读取 raw image 或 free-text reasoning 判断完成。
- Recovery 第一版支持固定的 `retry_current -> replan -> fallback -> abort` 路径；fallback 只有在配置了明确 proposal 时可用。

Transition table：

| Condition | State action | Next logical node |
| --- | --- | --- |
| `task_success` | close active execution, record completion | terminal |
| `completed` | close active execution, append completed ledger | plan on next Runtime step |
| `in_progress` | keep active execution | act on next Runtime step |
| `failed` | apply recovery policy | act, plan, fallback, or terminal |
| `uncertain` within budget | keep active execution | verify again without Environment action |
| `uncertain` exhausted | apply recovery policy | plan, fallback, or terminal |
| chunk/attempt budget exhausted | record classified failure | plan, fallback, or terminal |
| no-progress/repeated/A-B-A loop | record classified failure | fallback or terminal |

`planner_check_interval_chunks` 仅作为旧配置兼容参数保留，不再允许 Planner 在 `in_progress` execution 中判断 continue。后续视觉检查频率属于 Subtask Verifier 配置。

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

1. [x] 定义 Pipeline-owned graph state、transition table、recovery 顺序和 trace 摘要边界。
2. [ ] 调整 Planner proposal contract；增加独立 Subtask Verifier 和 focused contract tests。
3. [ ] 实现 graph state 初始化、`plan/act/execute/verify/transition` 路由和 ledger。
4. [ ] 实现 retry/replan/fallback/abort、attempt/chunk budget、no-progress 和 loop detection。
5. [ ] 保证每次 `Pipeline.step()` 最多调用一次 `Environment.execute()`，uncertain reverify 调用零次。
6. [ ] 增加 transition unit tests，覆盖 first plan、continue、completed、failed、uncertain、budget、no-progress、loop、task success 和 cleanup。
7. [ ] 迁移 RoboCasa configs，保持 `DirectPipeline`、EB-ALFRED 和 atomic/composite config loading 兼容。
8. [ ] 更新 architecture、TODO、用户文档和 change record，并运行 pytest、Ruff、mypy、Markdown links 和 `git diff --check`。

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
