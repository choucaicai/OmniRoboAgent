# Memory

Memory 保存已发生的事实和事件，并通过显式 recall 向 Planner 或 Verifier 提供上下文。Memory 不重新判断执行状态，也不直接改变 Pipeline transition。

## Contract

```python
class Memory:
    def reset(self, session_id: str) -> None: ...
    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None: ...
    def recall(self, query: dict[str, Any]) -> dict[str, Any]: ...
```

当前 recall 返回统一的普通字典：

```text
working_frames
recent_events
key_events
summary
```

`ReflectiveMemory` 在此之上附加 `lessons`、`object_state` 和 `procedures` 三个键；上面四个键的语义和字段不变。

## Current Implementations

| Memory | Behavior | Suitable for |
| --- | --- | --- |
| `InMemoryMemory` | 保存当前 session 的所有 events，reset 时清空 | tests、短任务和最小闭环 |
| `JsonlMemory` | 将可序列化 event append 到指定 JSONL | 简单持久化和离线检查 |
| `TieredMemory` | bounded visual frames、recent events、long-term key events 和 text summary | 长程、多模态 skill execution |
| `ReflectiveMemory` | 在 `TieredMemory` 之上把重复失败蒸馏成带证据计数的 lessons，并可选维护按对象索引的已确认世界状态和由 task 成功归纳的 procedures | 需要跨 attempt 和跨 episode 积累经验、或场景部分可观测的长程任务 |

## `TieredMemory`

```yaml
memory:
  class_path: omniroboagent.agent_core.TieredMemory
  init_args:
    visual_window_size: 4
    recent_event_limit: 20
    key_event_limit: 20
    summary_max_chars: 4096
    save_key_event_artifacts: false
    frame_selection: recent
```

`reset(session_id)` 清理 working frames、recent events 和当前 summary，但保留 long-term key events。Key events 包括 subtask complete/fail、recovery、fallback、abort 和 task terminal。

`frame_selection` 决定 visual working memory 的准入策略，窗口容量始终是 `visual_window_size`：

| 取值 | 行为 |
| --- | --- |
| `recent` | 每一步都占用一个槽位，窗口等于最近 K 帧的滑动窗口 |
| `event` | 只有 boundary frame 独占槽位，连续的 steady-state frame 共用最后一个槽位 |

Boundary frame 指该 transition 产生了 key event，或 verifier status 与窗口中上一帧不同。在 action chunk 执行期间，连续若干步的画面高度相似且 status 不变，`recent` 会让这些近似重复帧挤掉更早的失败帧；`event` 下它们只占一个槽位，窗口因此保留「失败时的画面 + 当前画面」。两种取值的图片数量相同，即 prompt 中的 image token 开销不变。

每个 frame 额外带 `event_type`、`status` 和 `pinned` 三个字段，可用于核对窗口里实际留下了哪些帧。默认值 `recent` 与此前行为完全一致。

Planner 和 Verifier 注入 working frames 时会**按帧插入一行标注**（`step=... event=... status=...`）再贴该帧图片，两种 `frame_selection` 下都生效。若干张画面高度相似时，模型靠这行标注才能分辨哪一张是失败发生的那一刻；没有标注的话 salience gating 选对了帧，下游却看不出来。渲染逻辑集中在 `agent_core/prompting.py` 的 `working_frame_content()`，三处注入点共用。

启用 `save_key_event_artifacts` 后，Runtime 必须在 state 中提供 `artifact_dir`。Memory 会把关键事件对应的 camera frames 保存为 PNG，并在 `artifacts/key_events/events.jsonl` 写结构化 metadata；普通 `in_progress` event 不保存图片。

不可序列化 action、tensor 或 image 不应直接写入 JSONL。应保存摘要、独立 artifact 或引用。

## `ReflectiveMemory`

```yaml
memory:
  class_path: omniroboagent.agent_core.ReflectiveMemory
  init_args:
    visual_window_size: 4
    recent_event_limit: 20
    key_event_limit: 20
    summary_max_chars: 4096
    save_key_event_artifacts: false
    frame_selection: event
    lesson_recall_limit: 3
    lesson_min_support: 2
    lesson_limit: 64
    lesson_path: outputs/lessons.jsonl
    lesson_reload: false
    track_object_state: false
    object_state_limit: 12
    track_procedures: false
    procedure_recall_limit: 1
    procedure_min_support: 1
    procedure_limit: 32
```

`ReflectiveMemory` 继承 `TieredMemory` 的全部行为和参数，并额外维护一个 lesson 分区。把上面的 `class_path` 换回 `TieredMemory` 即可得到不含 lesson 的对照配置，其余参数不需要改动。

`frame_selection`、lesson 机制、object state 账本和 procedure 归纳四者相互独立：分别影响视觉层准入、`lessons`、`object_state` 和 `procedures` 分区。做消融时可以分别开关，不要把它们绑在同一个开关上。

每次 `subtask_failed` 或 `execution_aborted` 会生成一个 attempt signature。Signature 只包含 skill 和 `grounded_arguments` 中的字符串槽位，忽略坐标等易变数值，因此同一个 subtask 的多次重复尝试会聚合到同一条 lesson 上，而不是每次新建一条。

Failure class 由 `environment_result["control_failure"]` 和 verifier reason 的关键词确定性推导，取值为 `control_loop`、`no_progress`、`chunk_budget`、`precondition_unmet`、`grasp_failed`、`placement_failed`、`environment_error` 或 `unclassified`。Memory 不调用 LLM，也不做视觉判断。

Lesson 有三种状态：

| 状态 | 含义 | 是否进入 recall |
| --- | --- | --- |
| `candidate` | 证据不足，`support_count - refutation_count` 未达 `lesson_min_support` | 否 |
| `active` | 证据充足 | 是 |
| `retired` | 后续同 signature 的 `subtask_completed` 已经推翻它 | 否 |

Lesson 只被退役，不被删除或原地覆盖；每次变更递增 `revision`，并保留 `first_seen_step`、`last_seen_step`、`session_ids` 和 `source_event_ids` 供回溯。

`recall({"phase": "verify", ...})` 返回的 `lessons` 恒为空列表。Verifier 只判断当前这一次执行，历史失败对它是干扰项。`phase` 为其他值或缺失时按词面重叠和证据计数排序，最多返回 `lesson_recall_limit` 条。

`reset(session_id)` 保留 lessons，因此该分区跨 episode 演化。设置 `lesson_path` 后，每次 `add`、`upvote`、`refute`、`promote`、`demote`、`retire` 和 `evict` 都会 append 一条可序列化的审计记录。

`lesson_reload: true` 时，构造阶段会重放 `lesson_path` 的审计日志重建 lesson 分区，使积累跨进程保留；该选项要求同时设置 `lesson_path`。重建时按 `lesson_id` 取每条 lesson 的最后一次记录，`evict` 记录表示丢弃，无法解析或缺少证据计数的行被跳过。重建出的 lesson 带 `carried_over: true`，status 按**当前**的 `lesson_min_support` 重新判定，因此调小阈值不会让旧 lesson 保持在过期的状态上。默认 `false`：跨 run 累积会把上一轮的结论带进本轮，多轮评测时应显式开启并注意 `session_ids` 的来源。

Lesson 内容是事实陈述（某 signature 以某 failure class 失败过几次、最近原因是什么），不包含祈使式建议。Planner 通过 `memory_context["lessons"]` 显式读取并自行决定如何使用；Memory 不修改 proposal、verification 或 Pipeline transition。

### Object State Ledger

开启 `track_object_state` 后，`recall()` 的 `object_state` 分区维护一份按对象索引的、已被 Verifier 确认的世界状态。它解决的是 `summary` 和 `key_events` 的共同缺陷：两者都是**叙事**，按时间排列且超限时从头丢弃，最早确认的事实（「第 3 步已经把柜门打开了」）最先消失；同一对象被多次操作时两条陈述都留着，Planner 必须自己判断哪条还成立。账本是**状态**，按对象去重，只保留最新一条。

条目的 key 取 `grounded_arguments` 中字符串槽位的值，与 lesson signature 用的是同一套提取逻辑，因此不需要实体抽取或 LLM。一次 `subtask_completed` 会为它涉及的每个对象各记一条：`object=mug, target=tray` 时 `mug` 和 `tray` 下都记录「杯子在托盘上」，因为这对两个对象都是事实。陈述内容取 `expected_outcome`，缺失时退化为 `subtask`，两者都没有时不记录。

| 后续事件 | 对已有条目的影响 |
| --- | --- |
| 同对象的 `subtask_completed` | supersede：`revision` 递增，`superseded_step` 记下前一次的 `confirmed_step`，`state` 换成新陈述 |
| 涉及同对象的失败 | 设置 `disturbed_step`，但 `state` 和 `confirmed_step` 不变 |

失败**不确认任何事实**，所以不 supersede；但它可能物理扰动了触碰到的对象，因此打上 `disturbed_step`，Planner 看到的是「杯子在第 10 步被确认放在托盘上，但第 22 步有一次涉及杯子的尝试失败了」这样的事实，而不是「别再碰杯子」这样的建议。

`reset(session_id)` **清空**账本，这与 lesson 的处理相反：

| 分区 | reset 行为 | 原因 |
| --- | --- | --- |
| `lessons` | 保留 | 讲的是 agent 自身的能力，跨 episode 成立 |
| `object_state` | 清空 | 讲的是这一个场景，环境每个 episode 重新随机化，上一轮确认的事实对本轮不是证据 |

`recall({"phase": "verify", ...})` 的 `object_state` 恒为空列表，理由与 lesson 相同：Verifier 必须从当前画面判断，「这里本来应该是什么样」的先验会诱导它盖章放行。条目数上限为 `object_state_limit`，超出时淘汰最久未被确认的对象。

### Procedures

`lessons` 记的是负例（什么反复失败过），`procedures` 记的是正例（整个 task 是怎么做成的）。开启 `track_procedures` 后，每次 `task_success` 会从 `state["completed_executions"]` 归纳出一条有序 procedure：每一步取 skill 和该步的字符串槽位，生成与 attempt signature 同构的步骤签名 `skill|slot=value,...`，坐标等数值不进签名。

Procedure 的 signature 是归一化 task 文本加上有序步骤签名。完全相同的解法再次成功时 `support_count` 递增、`session_ids` 追加，仍然只有一条；步骤不同则各存一条——同一个 task 的多条可行路径都是事实，不互相覆盖。

召回时按 task 与 procedure 的**内容词**重叠排序，内容词取自各步骤的 skill 名和对象槽位值，而不是 task 原文。原因是 `the`、`on` 这类虚词会让几乎任意两条指令都产生重叠，用对象名匹配才有区分度。query 带 task 时，重叠为零的 procedure 直接不召回。最多返回 `procedure_recall_limit` 条，超过 `procedure_limit` 时淘汰证据最弱的一条。

`reset()` **保留** procedure，与 lesson 一致、与 `object_state` 相反：

| 分区 | 讲什么 | reset |
| --- | --- | --- |
| `lessons` | agent 能力的负例 | 保留 |
| `procedures` | 任务解法的正例 | 保留 |
| `object_state` | 当前场景的世界状态 | 清空 |

内容同样是事实陈述（「该 task 曾以这个顺序完成过 N 次」），不是「照这么做」的指令，是否复用由 Planner 决定。`phase == "verify"` 时该分区为空。

注意 `task_success` 样本可能极少（既有 audit 中 composite 40 episodes 仅 1 次成功），单次成功的 procedure 可能来自特定场景布局；`support_count` 和 `session_ids` 就是用来暴露证据强度的。默认关闭。

## Prompt Rendering And `memory_char_budget`

`recall()` 返回什么是 Memory 的职责；这些分区**怎么进 prompt** 是注入端的职责，集中在 `agent_core/prompting.py`。Planner 和 Verifier 都通过 `memory_text_payload()` 渲染，并各自带一个 `memory_char_budget`（默认 4096 字符）：

```yaml
planner:
  class_path: omniroboagent.agent_core.SubtaskSkillPlanner
  init_args:
    memory_char_budget: 4096
```

渲染做三件事。

**一、去重。** `summary` 是各条 key event 的 `text_summary` 顺序拼接，因此原样再发一遍 `key_events` 记录是纯重复。实测一段 30 event 的记忆里，最近 10 条 key event 的 `text_summary` **全部 10 条**逐字出现在 `summary` 中，而 `key_events` 占掉 42% 的 memory prompt。现在 `summary` 已覆盖的 key event 只保留 `summary` 不含的那部分——verifier evidence；完全被覆盖且无 evidence 的直接不发。`recent_events` 压成每条一行的 `step/event/status/reason`，不再发整条记录。

**二、按决策价值排序填充。** 顺序为 `object_state` → `lessons` → `procedures` → `key_events` → `recent_events` → `summary`。蒸馏分区最短也最具体，排在最前；`summary` 排最后正因为它是重复度最高的一块，让它先出价会饿死后面所有分区。

**三、超限时报告。** 列表分区从最旧一端丢，`summary` 按行从最旧一端截断，丢掉的内容写进 `dropped` 键（`"summary[oldest 20]"` 或整块丢失时的 `"summary"`）。被截断的 prompt 不会看起来像一份完整的 prompt。

同一段记忆下，渲染前 18473 字符，仅去重后 7490 字符（−59.5%），再套默认 4096 budget 后 4115 字符（−77.7%）。蒸馏三分区占比从 6.6% 升到 27%。

预算以**字符**而非 token 计：core 依赖只有 `httpx`、`Pillow`、`PyYAML`，引入 tokenizer 会破坏这条边界，而字符数是 token 数的稳定上界。

接下来：[Framework Components](../interfaces.md)。
