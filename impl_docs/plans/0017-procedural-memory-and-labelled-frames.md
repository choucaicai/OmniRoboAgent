# Procedural Memory And Labelled Working Frames

Status: DONE

## Goal

补上 memory 机制里两处结构性缺口。

**其一，成功侧是空的。** [0014](0014-reflective-memory.md) 把重复失败蒸馏成 lesson，[0016](0016-confirmed-object-state-ledger.md) 把确认结果整理成对象状态，但「这个 task 整体是怎么做成的」这条信息无处存放。当前 memory 对一次 `task_success` 的唯一反应是给相关 lesson 投一张反对票，那条成功路径本身随 episode 结束丢弃，下一个同类 episode 从零开始。AWM 从成功轨迹归纳可复用 workflow，Memp 建 procedural memory，Voyager 建 skill library，CoALA 把 procedural memory 单列为一类——这条线本项目完全没有。

pipeline 已经备好素材：`task_success` 发生时 `state["completed_executions"]` 就是一串有序执行记录，每条带 `skill`、`subtask`、`grounded_arguments` 和 `expected_outcome`。归纳成 procedure 不需要新数据源，也不需要 LLM。

**其二，[0015](0015-salient-working-memory-and-lesson-persistence.md) 只做了一半。** `frame_selection: event` 会为每帧算出 `event_type`、`status` 和 `pinned`，但三处注入点（`SubtaskSkillPlanner`、`LanguageSkillPlanner`、`SubtaskVerifier`）都只写一句 `Visual working memory, oldest to newest` 然后裸贴图片。模型看到的是若干张高度相似的画面，**无法分辨哪一张是抓取失败的那一刻**。salience gating 精心挑出的边界帧，信息在注入环节全部丢失。3D-Mem、MemER 和 KEMO 的关键帧都是带标注进入 prompt 的。

## Confirmed Decisions

- Procedure 只从 `task_success` 归纳。`subtask_completed` 已经由 lesson refutation 和对象状态账本覆盖，task 级成功才是「整条路径可复用」的证据。
- Procedure 的步骤签名复用 `_grounded_slots()`，与 attempt signature 同构（`skill|slot=value,...`），因此坐标等易变数值不进入签名，同一解法的多次成功可以对齐计数。
- Procedure signature = 归一化 task 文本 + 有序步骤签名。完全相同的解法累加 `support_count`，不同解法各存一条——同一个 task 的多条可行路径都是事实。
- 内容是**事实陈述**（「该 task 曾以这个顺序完成过 N 次」），不是祈使建议。是否照做由 Planner 决定，Memory 不改 proposal、verification 或 transition。
- `reset()` **保留** procedure，与 lesson 一致：讲的是任务解法而非当前场景，跨 episode 成立。这与 `object_state` 的清空语义相反。
- `phase == "verify"` 时分区为空，与 lesson 和 object state 一致。
- 召回按 task 词面重叠排序；query 带 task 时要求重叠非零，避免把别的 task 的解法当噪声注入。
- 默认 `track_procedures: false`，与 `frame_selection`、lesson 开关、`track_object_state` 一样可独立消融。
- 帧标注对**所有** `frame_selection` 取值生效，不绑定在 `event` 上。`recent` 下标注同样有用（模型至少知道每张图是第几步），且两者共用同一段渲染逻辑更不容易分叉。
- 三处注入点收敛到一个共享函数 `agent_core/prompting.py::working_frame_content()`，避免 planner 和 verifier 的渲染逻辑各自漂移。

## Open Questions

- 步骤签名只保留 skill 和字符串槽位，丢弃了 `expected_outcome`。若两条路径 skill 序列相同但目标不同，会被判为同一条 procedure。等观察到实际冲突再决定是否把 outcome 并入签名。
- Procedure 目前不跨进程持久化。lesson 有 `lesson_path` + `lesson_reload`，procedure 只在进程内跨 episode 累积。是否值得再加一份审计日志，取决于多轮评测的实际用法。
- 经验跟随风险：`task_success` 的样本极少（既有 audit 中 composite 40 episodes 仅 1 次成功），单次成功可能来自特定场景布局。当前靠 `support_count` 和 `session_ids` 暴露证据强度，未做场景相似度判断。
- 标注文本的粒度未经真实 rollout 检验。当前每帧一行 `step/event/status`，是否需要更短或更长未知。

## Scope

- `ReflectiveMemory` 增加 `track_procedures`、`procedure_limit`、`procedure_recall_limit` 和 `procedure_min_support` 并校验。
- 新增 `_record_procedure()`、`_procedure_steps()`、`_recall_procedures()`、`_procedure_text()` 和 `_task_text()`。
- `recall()` 增加恒定存在的 `procedures` 分区；超过 `procedure_limit` 时淘汰证据最弱、最久未出现的一条。
- `LanguageSkillPlanner._memory_prompt` 在分区非空时附加 `procedures`，每条只注入单行文本。
- 新增 `agent_core/prompting.py::working_frame_content()`，按帧插入一行标注后再贴该帧图片；`LanguageSkillPlanner`、`SubtaskSkillPlanner` 和 `SubtaskVerifier` 三处改用它。
- 补充 unit tests、用户文档、架构文档和 change record。

## Out Of Scope

- 不引入新依赖，不做语义解析、轨迹聚类或场景相似度计算。
- 不修改 `TieredMemory`、`InMemoryMemory`、`JsonlMemory`。
- 不修改 `SkillExecutionPipeline` 的 transition、recovery 或 loop abort 逻辑。
- 不修改 Verifier 的判定逻辑，不向 Verifier 注入 procedure。
- 不改变 `lessons` 和 `object_state` 分区的任何行为。
- 不改动现有 benchmark 配置，不做在线评测。

## Tasks

1. [x] `DONE` 实现 procedure 的归纳、计数、上限淘汰和 phase 门控。
2. [x] `DONE` `reset()` 保留 procedure，并与 `object_state` 的清空语义区分开。
3. [x] `DONE` 在 `_memory_prompt` 附加 `procedures`。
4. [x] `DONE` 新增 `working_frame_content()` 并收敛三处注入点。
5. [x] `DONE` 补充 unit tests。
6. [x] `DONE` 更新用户文档、架构文档、`TODO.md` 和 change record。

Implementation record: [2026-09-20 procedural memory and labelled frames](../changes/2026-09-20-procedural-memory-and-labelled-frames.md)。

## Acceptance Criteria

- 一次 `task_success` 由 `state["completed_executions"]` 归纳出一条 procedure，步骤顺序与执行顺序一致，数值槽位不进签名。
- 同一 task 的相同解法再次成功时 `support_count` 递增且仍只有一条；不同解法各存一条。
- `reset()` 之后 procedure 仍在，而 `object_state` 已清空。
- `recall({"phase": "verify"})` 的 `procedures` 为空列表。
- `track_procedures` 默认 `false` 时不产生任何条目，`recall()` 仍返回 `procedures` 键。
- query 带 task 时，词面无重叠的 procedure 不被召回。
- 超过 `procedure_limit` 时淘汰证据最弱的一条。
- `working_frame_content()` 为每帧输出一行标注再输出该帧图片，图片数量与顺序不变。
- 无 working frames 时不输出任何 header，不产生空的标注项。
- `pytest`、`ruff check`、`ruff format --check`、`mypy` 全部通过。

## Risks

- Procedure 注入使 plan phase prompt 变长。缓解手段是每条只注入单行文本、`procedure_recall_limit` 默认 1、verify phase 不注入、默认关闭。
- 经验跟随风险：Planner 可能盲目复刻一条在当前场景不成立的路径。缓解手段是每条带 `support_count` 和 `session_ids`，且陈述为事实而非指令；已在 Open Questions 记录样本稀疏问题。
- 帧标注改变了三处 prompt 的实际内容，属于行为变更而非纯重构。缓解手段是图片数量和顺序保持不变，只增加文本项，且由单测锁定顺序。
- 标注每帧增加少量 text token。相对既有 audit 中单帧数千 image token 的量级可以忽略，但仍记录在案。
