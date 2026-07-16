# Key Event Memory And Visual Artifacts

Status: DONE

## Goal

在 `TieredMemory` 内增加长期关键事件分区，记录 subtask completion/failure、recovery 和 task terminal 等结构化事件，并将事件发生后的关键帧保存为独立 artifact，供 Planner/Verifier 显式 recall。

## Confirmed Decisions

- 不新增与 `TieredMemory` 并列的 `EventMemory`、MemoryManager 或 artifact manager。
- 普通 transition 使用 bounded `recent_events`；只有 Pipeline 已分类的关键事件进入长期 `key_events`。
- Pipeline 只根据已有 structured transition 生成确定性 `event_type`，不增加视觉推理。
- Memory 不判断 completion、failure 或 task success，只保存 Pipeline event、Verifier reason/evidence 和 frame artifacts。
- Runtime 在 state 中提供当前 session 的 `artifact_dir`；Memory 不推导 benchmark output path。
- raw image 不写入 JSONL。Pillow 负责将可支持的当前 observation frame 保存为 PNG，event record 只保存 artifact reference。
- Planner/Verifier 默认消费关键事件文本，不自动加载全部历史关键帧，避免 prompt 图像数量无界增长。

## Open Questions

- 跨 episode key-event retrieval 的排序与过滤策略在出现正式 multi-run retrieval 需求后再确定。
- 是否对历史关键帧做 learned retrieval、caption 或 embedding 不在本阶段决定。

## Scope

- `Memory.recall()` 增加稳定的 `key_events` 字段，现有 Memory 实现返回空列表以保持兼容。
- `TieredMemory` 将每步 transition 保存在 bounded `recent_events`，将关键事件保存在长期 `key_events`。
- 关键事件包含 `event_id`、execution/attempt identity、event type、skill/subtask、reason、confidence、evidence、task progress、recovery action、artifact refs 和 timestamp。
- `SyncRuntime` 提供 session-scoped artifact root。
- `SkillExecutionPipeline` 和 `DirectPipeline` 输出确定性 `event_type`。
- RoboCasa composite 配置启用关键帧保存；resolved config 记录相关参数。
- Planner/Verifier prompt 显式包含最近 key-event 文本摘要。

## Out of Scope

- 不保存每一步 frame，不生成 episode video。
- 不引入 vector database、embedding service、semantic graph 或 LLM event summarizer。
- 不让 Memory 修改 proposal、verification、recovery 或 Pipeline graph state。
- 不改变 Environment action execution contract。

## Tasks

1. [x] 扩展 Memory recall contract 和兼容实现。
2. [x] 为 Pipeline event 增加确定性 `event_type`。
3. [x] 实现 bounded recent events、persistent key events 和关键帧 PNG artifact。
4. [x] 将 key-event 文本接入 Planner/Verifier memory context。
5. [x] 更新 RoboCasa config/resolved metadata 和 unit tests。
6. [x] 同步 `docs/`、architecture、TODO 和 change record。

Implementation record: [2026-07-16 key event memory](../changes/2026-07-16-key-event-memory.md).

## Acceptance Criteria

- `recent_events` 长度不超过配置上限，`key_events` 在 session reset 后保留。
- `in_progress` 普通 transition 不创建关键事件 artifact。
- subtask completed/failed、recovery、task success/failure 能创建结构化 key event。
- 可支持的当前 camera frame 保存为 PNG；JSONL 不内联 raw image。
- recall 默认按 session 过滤并返回 `working_frames`、`recent_events`、`key_events`、`summary`。
- Planner/Verifier 显式消费 key-event 文本，缺失字段时保持兼容。
- DirectPipeline 行为、Environment execution boundary 和现有 benchmark config 不回归。

## Risks

- 全 camera 保存会增加磁盘占用，因此只在关键事件触发，并允许配置 camera keys 和 artifact 开关。
- artifact 写入失败不能静默丢失；应抛出明确异常并由 Runtime 记录。
- key-event 文本过多会增加 prompt，Planner/Verifier 只消费 bounded recent slice。
