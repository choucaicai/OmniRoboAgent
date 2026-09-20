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

`ReflectiveMemory` 在此之上附加一个 `lessons` 键；上面四个键的语义和字段不变。

## Current Implementations

| Memory | Behavior | Suitable for |
| --- | --- | --- |
| `InMemoryMemory` | 保存当前 session 的所有 events，reset 时清空 | tests、短任务和最小闭环 |
| `JsonlMemory` | 将可序列化 event append 到指定 JSONL | 简单持久化和离线检查 |
| `TieredMemory` | bounded visual frames、recent events、long-term key events 和 text summary | 长程、多模态 skill execution |
| `ReflectiveMemory` | 在 `TieredMemory` 之上把重复失败蒸馏成带证据计数的 lessons | 需要跨 attempt 和跨 episode 积累失败经验的长程任务 |

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
```

`ReflectiveMemory` 继承 `TieredMemory` 的全部行为和参数，并额外维护一个 lesson 分区。把上面的 `class_path` 换回 `TieredMemory` 即可得到不含 lesson 的对照配置，其余参数不需要改动。

`frame_selection` 与 lesson 机制相互独立：前者只影响视觉层的准入，后者只影响新增的 `lessons` 分区。做消融时可以分别开关，不要把两者绑在同一个开关上。

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

接下来：[Framework Components](../interfaces.md)。
