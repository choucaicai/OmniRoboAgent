# Reflective Memory With Evidence-Gated Lessons

Status: DONE

## Goal

在现有 `TieredMemory` 之上增加一层由 Verifier 结论驱动的**失败蒸馏分区**，把语义等价的重复失败聚合成带证据计数的 lesson，并按 recall phase 收紧注入范围，使 Planner 在重新规划时能显式看到"同一个 subtask 已经以同样方式失败过几次"，同时不增加 Verifier 的 prompt 负担。

该分区跨 episode 保留，随后续 episode 的 completed/failed 结论自动升级或退役，构成确定性的自进化闭环。

## Confirmed Decisions

- 不新增与 `TieredMemory` 并列的 MemoryManager、LessonStore、registry 或 factory。新增 `ReflectiveMemory(TieredMemory)` 单一实现，由 `class_path` 选择。
- 保留 `TieredMemory` 不变，作为消融对照臂；两者除 lesson 分区外行为一致。
- lesson 蒸馏**不调用 LLM**，只由 Pipeline 已产出的结构化字段确定性推导。Memory 不做视觉或语义推理。
- lesson 内容是**事实陈述**（某 signature 以某 failure class 失败过 N 次，最近原因为 X），不包含祈使式建议。Planner 自行决定如何使用。
- 证据门控：lesson 在 `support_count` 达到阈值前只是 `candidate`，不进入 recall 结果；达到阈值后置为 `active`。
- 退役而非删除：同 signature 出现 `subtask_completed` 时增加 `refutation_count`，超过 support 后置为 `retired` 并停止注入，但记录保留并带 `revision` 版本号。显式拒绝 A-MEM 式的无版本原地改写。
- 按 phase 收紧：`phase == "verify"` 时 lesson 分区返回空列表。Verifier 只判断当前这一次执行，历史失败对它是干扰项，也会诱导先验偏置。
- recall 返回的四个既有分区 `working_frames` / `recent_events` / `key_events` / `summary` 语义和字段不变，lesson 是**附加**分区。
- signature 不包含 `grounded_arguments` 中的数值坐标和 `expected_outcome`，只保留 skill 与规范化后的对象槽位，以保证语义等价的重复尝试能对齐。
- 注入条数硬上限默认 3。上下文腐烂的证据表明无关条目随 prompt 长度加剧伤害，不做大 top-k。

## Open Questions

- lesson 排序目前使用词面重叠加证据计数的确定性打分。是否需要 embedding 检索，等 diagnostic 显示词面召回不足后再决定，本阶段不引入。
- 跨 episode lesson 的持久化目前依赖 `lesson_path` JSONL。是否需要在 Runtime 层自动装载上一轮 lesson 文件，等出现多轮评测需求后再定。
- failure class 关键词表是人工固定的最小集合。是否扩展为 AgentErrorTaxonomy 的完整五模块分类，待真实失败样本统计后再定。

## Scope

- 新增 `ReflectiveMemory`，在 `TieredMemory` 的 update 流程后追加 lesson 生命周期处理。
- 新增确定性的 attempt signature 推导：skill 加规范化对象槽位。
- 新增确定性的 failure class 分类：control loop、no progress、chunk budget、precondition unmet、verifier uncertain、environment error、unclassified。
- 新增 lesson 生命周期算子 add、upvote、refute、promote、retire，每次变更写入可选的 JSONL 审计日志。
- `recall()` 增加 `lessons` 分区，按 phase 门控并按确定性打分取 top-k。
- `reset()` 保留 lesson，与既有 key events 的保留语义一致，不需要额外的 session 级记账。
- `LanguageSkillPlanner` 的 memory prompt 在 lesson 非空时附加该分区。
- 导出新实现，补充 unit tests、用户文档和 change record。

## Out of Scope

- 不引入 vector database、embedding service、sentence-transformers、faiss 或任何新依赖。
- 不在 Memory 内调用 LLM 做反思或摘要。
- 不修改 `SkillExecutionPipeline` 的 graph state、transition 条件或 loop abort 逻辑。Memory 只陈述重复失败的事实，是否据此中止由 Pipeline 和 Planner 决定。
- 不修改 Verifier 实现，不向 Verifier 注入 lesson。
- 不改变 `TieredMemory`、`InMemoryMemory`、`JsonlMemory` 的既有行为。
- 不改动现有 benchmark 配置的默认 memory 实现。
- 不做跨 episode 的在线评测；本阶段验收只到 unit test 与离线重放级别。

## Tasks

1. [ ] 实现 `ReflectiveMemory`：signature、failure class、lesson 生命周期、phase-aware recall、JSONL 审计。
2. [ ] 在 `memories/__init__.py` 和 `agent_core/__init__.py` 导出。
3. [ ] 在 `LanguageSkillPlanner._memory_prompt` 中显式附加 lesson 分区。
4. [ ] 补充 unit tests，覆盖 signature 稳定性、证据门控、退役、phase 门控、reset 保留和 JSONL 可序列化。
5. [ ] 更新 `docs/agent_core/memory.md`、`impl_docs/architecture/overview.md`、`impl_docs/TODO.md` 和 change record。

Implementation record: [2026-09-20 reflective memory](../changes/2026-09-20-reflective-memory.md).

## Acceptance Criteria

- 同一 skill 与对象、但 `grounded_arguments` 数值不同的重复失败，产生同一个 signature 并聚合到同一条 lesson。
- `support_count` 未达阈值的 lesson 不出现在 recall 结果中。
- 同 signature 的 `subtask_completed` 使 lesson 的 `refutation_count` 增加，超过 support 后 `status` 变为 `retired` 且不再注入。
- `phase == "verify"` 时 `lessons` 为空列表。
- `reset()` 之后 lesson 仍然保留，working frames 和 recent events 仍按既有语义清空。
- recall 结果始终包含 `working_frames`、`recent_events`、`key_events`、`summary` 四个既有键，字段语义不变。
- lesson JSONL 只包含可序列化字段，不内联 raw image、array 或自定义对象。
- 未启用 `ReflectiveMemory` 的既有配置行为不回归，`TieredMemory` 相关测试全部通过。
- `pytest`、`ruff check`、`ruff format --check`、`mypy` 全部通过。

## Risks

- 经验跟随与错误传播：注入历史失败可能让 Planner 过度模仿而非推理（arXiv:2505.16067）。缓解手段是证据门控、注入条数上限 3、以及用后续 `subtask_completed` 作为免费质量标签自动退役。
- prompt 增长：既有 audit 显示 memory 扩充曾使 planner prompt token 从 22352 增至 24112 而成功率未变。因此 lesson 只在 plan phase 注入、最多 3 条、每条为单行文本，并且 verify phase 反而比 `TieredMemory` 更省。
- 关键词式 failure 分类可能误判。缓解手段是保留 `unclassified` 兜底类，并在 lesson 中同时保存原始 reason 片段供人工核对。
- 跨 episode 收益需要足够多 episode 才能显现（Voyager 的技能库在约 80 轮前几乎无效，AWM 约 40 例饱和）。因此不承诺单次 smoke 上的成功率提升，验收只落在机制正确性上。
- lesson 文件跨 run 累积可能引入陈旧结论。缓解手段是每条 lesson 记录 `first_seen_step`、`last_seen_step`、`session_ids` 和 `revision`，可审计可回溯。
