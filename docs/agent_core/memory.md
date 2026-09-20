# Memory

Memory 保存已发生的事实和事件，并通过显式 recall 向 Planner 或 Verifier 提供上下文。Memory 不重新判断执行状态，也不直接改变 Pipeline transition。

## Contract

```python
class Memory:
    def reset(self, session_id: str) -> None: ...
    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None: ...
    def recall(self, query: dict[str, Any]) -> dict[str, Any]: ...
```

`recall()` 统一返回普通字典，具体字段由实现负责。`TieredMemory` 使用：

```text
working_frames
recent_events
key_events
summary
```

`SpatialMemory` 则只返回 `spatial` localization。`LanguageSkillPlanner` 在
`memory_context` 中检测到该字段时，会将其加入文本形式的 `Memory context`；因此
仅启用 `SpatialMemory`、没有事件摘要时，空间记忆也能进入模型提示词。

## Current Implementations

| Memory | Behavior | Suitable for |
| --- | --- | --- |
| `InMemoryMemory` | 保存当前 session 的所有 events，reset 时清空 | tests、短任务和最小闭环 |
| `JsonlMemory` | 将可序列化 event append 到指定 JSONL | 简单持久化和离线检查 |
| `TieredMemory` | bounded visual frames、recent events、long-term key events 和 text summary | 长程、多模态 skill execution |
| `SpatialMemory` | 全局 PLY 单次定位，或 RGB-D 增量 voxel 建图与布局定位 | 需要显式空间布局上下文的任务 |

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

## `SpatialMemory`

已有完整全局场景点云时，可以配置静态定位模式：

```yaml
memory:
  class_path: omniroboagent.agent_core.memories.spatial.SpatialMemory
  init_args:
    global_scene_ply: <GLOBAL_SCENE_PLY>
    spatial_backend:
      class_path: omniroboagent.backends.spatial.SpatialLMBackend
      init_args:
        model_path: <MODEL_PATH>
```

`SpatialMemory` 会在构造时对 PLY 定位一次，后续 session reset 和 memory update 都
复用该结果，不接收 RGB-D 帧、不更新地图，也不重复运行 SpatialLM。未配置
`global_scene_ply` 时才使用在线 RGB-D 关键帧建图模式；此时 Environment 必须在
observation 的 `spatial_frames` 字段提供同步 RGB-D、内参和米制绝对相机位姿。
两种方式的完整输入字段、单位、坐标系、校验规则和参数见
[SpatialMemory 空间记忆组件](../components/spatialmemory_memory.md)。

接下来：[Framework Components](../interfaces.md)。
