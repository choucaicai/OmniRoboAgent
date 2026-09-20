# Confirmed Object State Ledger

Status: DONE

## Goal

给 `ReflectiveMemory` 增加第二个语义分区：按对象索引的、由 Verifier 确认的世界状态账本。

现有分区里，「世界现在是什么样」这个信息只以**叙事**形式存在。`summary` 是全部 key event 文本按时间顺序拼接，超过 `summary_max_chars` 时**从头丢弃**；`key_events` 是按时间排序的列表，recall 只取最后 `key_event_limit` 条。两者都有同一个缺陷：最早确认的事实最先消失，而它往往恰恰是最需要保留的那一条（「第 3 步已经把柜门打开了」）。而且同一个对象被多次操作时，两条陈述都留在叙事里，Planner 必须自己推断哪条还成立。

RoboCasa 厨房是部分可观测的，相机只覆盖一个视角。Planner 因此会重复提出效果已经达成的 subtask。既有 audit 中 composite 40 episodes 只有 1 次成功，且记录了「语义相同的重复 Pick_Place proposal」问题。[0014](0014-reflective-memory.md) 用 attempt signature 解决了失败侧的重复识别，本计划解决成功侧：把已确认的效果整理成按对象去重、带 supersede 的状态视图。

## Confirmed Decisions

- 账本的 key 是 `grounded_arguments` 里字符串槽位的**值**（对象名），不是自由文本。复用 [0014](0014-reflective-memory.md) 的槽位提取逻辑，因此不需要任何 NLP、正则实体抽取或 LLM 调用。
- 一次 `subtask_completed` 涉及的每个字符串槽位值都建一条目。`object=mug, target=tray` 会同时在 `mug` 和 `tray` 下记录同一条已确认陈述，因为「杯子在托盘上」对两个对象都是事实。
- 事实内容取 `expected_outcome`，缺失时退化为 `subtask`；两者都没有时**不记录**，不编造陈述。
- 只有**后续同对象的确认**才会 supersede 先前的事实。保留 `revision` 和 `superseded_step`，与 lesson 一样不做无版本的原地覆盖。
- 失败**不确认任何事实**，因此不 supersede。但失败可能物理扰动了它触碰的对象，所以给这些对象的现有条目打 `disturbed_step`。这是事实陈述（第 N 步有一次涉及该对象的尝试失败了），不是建议。
- `reset()` **清空**账本。环境每个 episode 重新随机化，上一个 episode 确认的事实对本 episode 不是证据。这与 lesson 的处理**相反**：lesson 讲的是 agent 自身的能力，跨 episode 成立；世界状态讲的是这一个场景，不跨 episode。
- `phase == "verify"` 时账本为空，与 lesson 一致。Verifier 必须从当前画面判断，先验的「这里本来应该是什么样」会诱导它盖章放行。
- 默认 `track_object_state: false`。与 `frame_selection`、`lesson_reload` 一样是可独立开关的机制，便于分别消融。
- 不新增审计日志文件。每条事实都带 `source_event_id`，对应的 key event 已经由 `event_path` 或 key-event JSONL 记录，provenance 可回溯，不必再加一份配置项。

## Open Questions

- 按槽位值建索引假设 `grounded_arguments` 的字符串值是对象引用。若某个 skill 用字符串槽位传非对象参数（例如 `direction=left`），会产生一条无意义条目。等真实 skill catalog 的参数分布统计出来后再决定是否需要槽位白名单。
- 同一个对象在不同 receptacle 间移动时，旧 receptacle 下的条目仍指向旧陈述。例如 mug 从 tray 移到 sink 后，`tray` 条目仍写着「mug 在 tray 上」。当前只靠 `confirmed_step` 让 Planner 自行比较新旧，未做跨条目的一致性传播。是否需要，等观察到实际误导后再定。
- `disturbed_step` 目前只标记不降级。是否应该在若干步后自动失效，需要真实 rollout 数据支撑。

## Scope

- `ReflectiveMemory` 增加 `track_object_state` 和 `object_state_limit` 参数并校验。
- 从 `_attempt_signature` 抽出 `_grounded_slots()`，供 signature 和账本共用，signature 的输出保持不变。
- 新增 `_update_object_state()`、`_confirm_object_state()`、`_recall_object_state()` 和 `_object_state_text()`。
- `recall()` 增加恒定存在的 `object_state` 分区，按确认时间从旧到新排序，上限 `object_state_limit`，超出时淘汰最久未确认的对象。
- 覆写 `reset()` 清空账本，同时保留 lesson 和 key events。
- `LanguageSkillPlanner._memory_prompt` 在账本非空时附加 `object_state` 分区，每条只注入单行文本。
- 补充 unit tests、用户文档、架构文档和 change record。

## Out of Scope

- 不引入新依赖，不做实体识别、共指消解或语义解析。
- 不修改 `TieredMemory`、`InMemoryMemory`、`JsonlMemory`。
- 不修改 `SkillExecutionPipeline` 的 transition、loop abort 或 recovery 逻辑。账本只陈述已确认的事实，是否据此跳过 subtask 由 Planner 决定。
- 不修改 Verifier，不向 Verifier 注入账本。
- 不改变 `lessons` 分区的任何行为。
- 不改动现有 benchmark 配置。
- 不做在线评测，验收只到 unit test 级别。

## Tasks

1. [x] `DONE` 抽出 `_grounded_slots()` 并保持 signature 输出不变。
2. [x] `DONE` 实现账本的确认、supersede、disturb、上限淘汰和 phase 门控。
3. [x] `DONE` 覆写 `reset()` 清空账本并保留 lesson。
4. [x] `DONE` 在 `LanguageSkillPlanner._memory_prompt` 附加 `object_state`。
5. [x] `DONE` 补充 unit tests，覆盖确认、supersede、disturb、reset 语义差异、phase 门控、上限和缺失 outcome。
6. [x] `DONE` 更新 `docs/agent_core/memory.md`、`docs/configuration.md`、`impl_docs/architecture/overview.md`、`impl_docs/TODO.md` 和 change record。

Implementation record: [2026-09-20 confirmed object state ledger](../changes/2026-09-20-object-state-ledger.md)。

## Acceptance Criteria

- 一次 `subtask_completed` 为其 `grounded_arguments` 的每个字符串槽位值建一条目，数值槽位不建。
- 后续同对象的确认使 `revision` 递增、`superseded_step` 记录前一次的 `confirmed_step`，且该对象只有一条条目。
- 后续涉及同对象的失败设置 `disturbed_step`，但不改变 `state` 和 `confirmed_step`，未涉及的对象不受影响。
- `reset()` 之后账本为空，而 lesson 和 key events 仍然保留。
- `recall({"phase": "verify"})` 的 `object_state` 为空列表。
- `track_object_state` 默认为 `false` 时不产生任何条目，`recall()` 仍返回 `object_state` 键。
- 超过 `object_state_limit` 时淘汰最久未确认的对象。
- `expected_outcome` 和 `subtask` 都为空时不建条目。
- attempt signature 的输出与 [0014](0014-reflective-memory.md) 完全一致，既有 lesson 测试全部通过。
- `pytest`、`ruff check`、`ruff format --check`、`mypy` 全部通过。

## Risks

- 账本注入使 plan phase 的 prompt 变长。既有 audit 显示 memory 扩充曾使 planner prompt 从 22352 token 增至 24112 而成功率未变。缓解手段是每条只注入单行文本、条数上限 `object_state_limit` 默认 12、verify phase 完全不注入，且默认关闭。
- 经验跟随风险：Planner 可能因为看到「门已经开了」而跳过必要的复核。缓解手段是每条都带 `confirmed_step`，且失败会打 `disturbed_step`，Planner 可以判断时效；账本是事实陈述而非「不要再开门」这类祈使建议。
- 槽位值未必是对象引用，可能产生噪声条目。缓解手段是每条都带 `slot` 和 `source_event_id`，可审计，且上限淘汰会让噪声条目自然退出。
- 跨 receptacle 移动导致旧容器条目陈旧，已在 Open Questions 记录，当前不做传播。
- 与 `breezexian` 的 `spatial_memory` 分支方向重叠，两者都在 `agent_core/memories/` 下增加空间或世界状态记忆，合并前需要确认分工。
