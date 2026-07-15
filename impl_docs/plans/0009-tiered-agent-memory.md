# Tiered Agent Memory

Status: TODO

## Goal

设计一个集中组合、分层存储的 Agent Memory，实现 bounded visual working memory、长期事件记忆和文本总结，同时避免 raw image/action 在 episode 内无界增长。

## Confirmed Decisions

- 集中 memory 是一个 `Memory` 实现，不新增全局 singleton、MemoryManager 或独立 Runtime。
- control state 的唯一真值仍在 Pipeline/Runtime state；Memory 只保存 observation facts、execution events、summary 和 artifact references。
- Planner/Verifier 只能通过显式 `memory_context`/`recall()` 输入读取 memory，Memory 不暗中修改 proposal 或 transition。
- 第一阶段使用标准库和现有 JSONL/artifact 机制，不引入 vector database 或 embedding dependency。
- raw frame 只进入 bounded working set 或独立 artifact；长期 event record 只保存摘要和引用。

## Open Questions

- 默认视觉窗口 `K`、关键帧保存规则和每 camera 的采样频率需要通过 RoboCasa RSS/quality audit 决定。
- 文本 summary 使用规则模板还是 LLM；第一阶段优先确定性 execution ledger summary。
- 跨 episode retrieval 达到明确需求后，再决定 JSONL scan、SQLite index 或 semantic index。

## Scope

集中 `TieredMemory` 包含三个明确层次：

```text
visual_working_memory
  bounded deque[K] of frame/artifact references and observation summaries

event_memory
  append-only execution/verification/transition records

text_summary
  bounded task state, completed/failed executions, blockers and salient facts
```

建议 event schema：

```text
session_id / step / execution_id / attempt_id
event_type / skill / subtask / status
reason / confidence / evidence_summary
artifact_refs / timestamp
```

生命周期：

- `reset(session_id)` 清空 episode working frames 和当前 summary，不删除长期 event memory。
- `update(state, event)` 接收 Pipeline 已形成的结构化 event，提取 bounded summary 和 artifact reference。
- `recall(query)` 返回命名分区，不直接拼接 prompt：`working_frames`、`recent_events`、`summary`。
- `close()` flush 持久化 store；不关闭 Planner/Verifier backend。

## Out of Scope

- 本阶段不实现 semantic/spatial graph、embedding service、vector database 或 learned retrieval policy。
- 不把 action tensor、完整 observation、model raw response 长期内联到 JSONL。
- 不让 Memory 决定 skill、completion、recovery 或 benchmark success。

## Tasks

1. [ ] 扩展 Memory contract：`reset()`、`update()`、`recall()`、`close()`，默认实现保持现有 Memory 兼容。
2. [ ] 实现 bounded visual working memory，优先保存 artifact reference 和 camera/step metadata。
3. [ ] 将 skill graph transition 写入 append-only event memory。
4. [ ] 实现 bounded deterministic text summary，并在 execution close/episode end 更新。
5. [ ] 在 Agent/Pipeline 输入中显式传递 memory context，增加序列化和容量测试。
6. [ ] 用 RoboCasa 长 episode audit K、RSS、artifact 数量和 planner/verifier context 大小。
7. [ ] 更新 architecture、configuration、TODO 和 change record。

## Acceptance Criteria

- working frames 数量始终不超过配置的 `K`。
- 长期 event memory 不内联 raw frame、action tensor 或 provider raw response。
- summary 有明确长度上限和更新时机。
- recall 返回稳定命名字段，并且不改变 Pipeline graph state。
- episode reset 后 working memory 清空，长期 event record 保留。

## Risks

- 同时保存多 camera raw frames 会快速占用内存；默认应保存引用并限制每 step/camera 数量。
- LLM summary 会引入成本和非确定性；在 deterministic ledger summary 验证前不启用。
- 过早实现 semantic retrieval 会掩盖 event schema 和 artifact policy 的问题。
