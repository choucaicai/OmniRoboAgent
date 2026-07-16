# Tiered Agent Memory

Status: IN_PROGRESS

## Goal

设计一个集中组合、分层存储的 Agent Memory，实现 bounded visual working memory、长期事件记忆和文本总结，同时避免 raw image/action 在 episode 内无界增长。

## Confirmed Decisions

- 集中 memory 是一个 `Memory` 实现，不新增全局 singleton、MemoryManager 或独立 Runtime。
- control state 的唯一真值仍在 Pipeline/Runtime state；Memory 只保存 observation facts、execution events、summary 和 artifact references。
- Planner/Verifier 只能通过显式 `memory_context`/`recall()` 输入读取 memory，Memory 不暗中修改 proposal 或 transition。
- 第一阶段使用标准库和现有 JSONL/artifact 机制，不引入 vector database 或 embedding dependency。
- raw frame 只进入 bounded working set 或独立 artifact；长期 key event record 只保存摘要和引用。

## Resolved Decisions

- 第一阶段默认视觉窗口 `K=4`，每个 timestep 可包含配置的多 camera；真实 RoboCasa audit 后再调整。
- 文本 summary 使用 deterministic transition ledger，不调用 LLM。
- 长期 key event memory 保存在进程内结构化列表，可选写入 session artifact JSONL；暂不引入 SQLite 或 semantic index。

## Open Questions

- 固定 RoboCasa real smoke 已确认 `K=4` 能提供有效完成证据，但还需 peak RSS 采样和多 episode matrix 后才能决定是否调整 K。
- Verifier backend usage/latency 当前未进入 trace，需要补齐后再分离 memory 与 verifier 的具体 latency 成本。
- 跨进程和跨 run retrieval 出现明确需求后，再决定持久化索引。

## Scope

集中 `TieredMemory` 包含四个明确层次：

```text
visual_working_memory
  bounded deque[K] of frame/artifact references and observation summaries

recent_events
  bounded deque[N] of ordinary transition records

key_events
  long-term salient execution/recovery/terminal records and artifact references

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

- `reset(session_id)` 清空 episode working frames、recent events 和当前 summary，不删除长期 key events。
- `update(state, event)` 接收 Pipeline 已形成的结构化 event，提取 bounded summary 和 artifact reference。
- `recall(query)` 返回命名分区，不直接拼接 prompt：`working_frames`、`recent_events`、`key_events`、`summary`。
- `close()` flush 持久化 store；不关闭 Planner/Verifier backend。

## Out of Scope

- 本阶段不实现 semantic/spatial graph、embedding service、vector database 或 learned retrieval policy。
- 不把 action tensor、完整 observation、model raw response 长期内联到 JSONL。
- 不让 Memory 决定 skill、completion、recovery 或 benchmark success。

## Tasks

1. [x] 扩展 Memory contract：`reset()`、`update()`、`recall()`、`close()`，默认实现保持现有 Memory 兼容。
2. [x] 实现 bounded visual working memory，优先保存 artifact reference 和 camera/step metadata。
3. [x] 将 skill graph transition 写入 append-only event memory。
4. [x] 实现 bounded deterministic text summary，并在 execution close/episode end 更新。
5. [x] 在 Agent/Pipeline 输入中显式传递 memory context，增加序列化和容量测试。
6. [ ] 用 RoboCasa 长 episode audit K、RSS、artifact 数量和 planner/verifier context 大小。
   - [x] 完成固定 `composite_seen / pretrain / DeliverStraw / episode_index=0 / seed=0` real smoke，对比迁移前同 episode trace。
   - [x] 核对 K=4 的 frame bound、Planner token/latency、visual verifier status/evidence 和 execution ledger。
   - [ ] 使用 peak-RSS 采样器重复运行，并在 verifier trace 中记录 backend usage/latency。
   - [ ] 运行相同 manifest 的多 episode matrix，区分控制逻辑改善与 success-rate 改善。
7. [x] 完成 memory context 接入后更新 architecture、configuration、TODO 和 change record。
8. [x] 增加关键事件分区和 current-frame visual artifacts（[0010 plan](0010-key-event-memory.md)）。

Core implementation record: [2026-07-15 tiered agent memory](../changes/2026-07-15-tiered-agent-memory.md).
Context integration record: [2026-07-15 memory context integration](../changes/2026-07-15-memory-context-integration.md).
Fixed smoke record: [2026-07-15 tiered memory RoboCasa smoke](../changes/2026-07-15-tiered-memory-robocasa-smoke.md).
Key event record: [2026-07-16 key event memory](../changes/2026-07-16-key-event-memory.md).

## RoboCasa Fixed Smoke Audit

运行配置为 `configs/runs/robocasa365_groot_composite_remote_smoke.yaml`，使用 `Qwen3.5-9B`、GR00T `checkpoint-240000`、`TieredMemory(K=4)` 和每 8 个 action chunks 一次的 visual verifier。结果保存在 `runs/robocasa365_groot_composite_remote_smoke/`。

对照是迁移前 `runs/robocasa365_groot_composite_remote_seen_pretrain_5tasks/` 中相同 `DeliverStraw / pretrain / episode_index=0 / seed=0` episode。两次使用相同 GR00T checkpoint 和 simulator seed，但 OmniRoboAgent commit、Python dependency set 和未固定的 policy RNG 不同，因此只能用于 fixed-smoke 诊断，不能视为严格 A/B quality 结论。

| Metric | Pre-graph baseline | Graph + verifier + memory |
| --- | ---: | ---: |
| Success | 0 | 0 |
| Task progress | 0.0 | 0.0 |
| Pipeline steps | 109 | 107 |
| Environment action chunks | 107 | 107 |
| Environment steps | 1700 | 1700 |
| Planner calls | 16 | 5 |
| Replans | 6 | 3 |
| Planner prompt tokens | 22352 | 24112 |
| Planner backend latency | 32.43 s | 19.31 s |
| Episode latency | 134.17 s | 149.49 s |

Verified observations:

- `Open_Door` 在 16 个 chunks 后被判定 `completed`，confidence 为 `0.95`；evidence 明确记录 drawer 已打开且 red straw 可见。
- 后续 4 个 `Pick_Place` executions 均未拿起 straw；其中 3 个耗尽 27-chunk budget，最后一个在 environment horizon 结束。Pipeline 保留了 1 条 completed ledger 和 4 条 failed ledger。
- visual verifier 实际执行 12 次语义检查：1 次 `completed`、11 次 `in_progress`，confidence 范围为 `0.9-1.0`；没有把仍在 drawer 内的 straw 误判为已完成。
- Planner calls 从 16 降至 5，Planner backend 总 latency 从 32.43 s 降至 19.31 s；K=4 图像历史使单次 Planner prompt 从首步 642 tokens 增长到 5535-5982 tokens，总 prompt tokens 略高于 baseline。
- 三路 `256x256x3` camera 在 K=4 时最多保留 12 张 frame，raw array payload 约 2.25 MiB，不含 Python/request serialization overhead。运行输出没有独立 visual artifact；精确 process peak RSS 未采样。
- episode latency 增加 15.32 s。当前 trace 不保存 Verifier backend token/latency，不能把增量严格拆分到 memory image context 与 12 次 verifier call。
- 新流程避免了旧流程在没有完成证据时过早切换到 placement subtask，但 task success 没有提升。当前 loop signature 包含易变化的 `grounded_arguments` 和 `expected_outcome`，语义相同的重复 `Pick_Place` proposal 未触发 loop abort；RunConfig 同时未设置 `max_no_progress_steps` 或 `max_replans`。

结论：固定 smoke 验证了 bounded memory、visual completion 和 deterministic ledger/recovery 的真实连线，控制逻辑优于迁移前行为；现有单 episode 不能证明端到端 quality 提升，主要瓶颈已收敛到 atomic `Pick_Place` policy 与 semantic loop/recovery 配置。

## Acceptance Criteria

- working frames 数量始终不超过配置的 `K`。
- 长期 key event memory 不内联 raw frame、action tensor 或 provider raw response。
- summary 有明确长度上限和更新时机。
- recall 返回稳定命名字段，并且不改变 Pipeline graph state。
- episode reset 后 working frames、recent events 和 summary 清空，长期 key event record 保留。

## Risks

- 同时保存多 camera raw frames 会快速占用内存；默认应保存引用并限制每 step/camera 数量。
- LLM summary 会引入成本和非确定性；在 deterministic ledger summary 验证前不启用。
- 过早实现 semantic retrieval 会掩盖 event schema 和 artifact policy 的问题。
