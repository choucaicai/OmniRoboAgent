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

## Current Implementations

| Memory | Behavior | Suitable for |
| --- | --- | --- |
| `InMemoryMemory` | 保存当前 session 的所有 events，reset 时清空 | tests、短任务和最小闭环 |
| `JsonlMemory` | 将可序列化 event append 到指定 JSONL | 简单持久化和离线检查 |
| `TieredMemory` | bounded visual frames、recent events、long-term key events 和 text summary | 长程、多模态 skill execution |

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
```

`reset(session_id)` 清理 working frames、recent events 和当前 summary，但保留 long-term key events。Key events 包括 subtask complete/fail、recovery、fallback、abort 和 task terminal。

启用 `save_key_event_artifacts` 后，Runtime 必须在 state 中提供 `artifact_dir`。Memory 会把关键事件对应的 camera frames 保存为 PNG，并在 `artifacts/key_events/events.jsonl` 写结构化 metadata；普通 `in_progress` event 不保存图片。

不可序列化 action、tensor 或 image 不应直接写入 JSONL。应保存摘要、独立 artifact 或引用。

接下来：[Framework Components](../interfaces.md)。
