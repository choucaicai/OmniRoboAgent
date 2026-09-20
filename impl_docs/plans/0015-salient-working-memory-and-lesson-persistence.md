# Salience-Gated Working Memory And Cross-Run Lesson Persistence

Status: DONE

## Goal

在 [0014](0014-reflective-memory.md) 之后继续迭代分层 Memory 的两个薄弱环节。

第一，visual working memory 目前是纯滑动窗口，准入策略只看「新」，不看「是否含有新信息」。RoboCasa 的 chunked execution 下，一个 action chunk 内连续若干步的画面高度相似且 verifier status 不变，这些近似重复帧会把更早的失败帧挤出窗口。既有 audit 显示 `K=4` 帧把单次 planner prompt 从 642 token 推到 5535–5982 token，即视觉层占了 prompt 的绝大部分开销，却按最弱的信号选帧。

第二，`ReflectiveMemory` 的 lesson 只在单个进程生命周期内累积，`lesson_path` 是只写的审计日志。这使「跨 episode 自进化」在跨 run 的评测场景下无法真正成立。

## Confirmed Decisions

- `frame_selection` 放在 `TieredMemory` 而不是 `ReflectiveMemory`。视觉层准入是 working memory 的职责，与 lesson 蒸馏无关；放在基类才能让两者独立消融。
- `frame_selection` 默认 `recent`，与既有行为逐字节一致。改变默认值会在无人要求的情况下改变所有现有配置的 prompt 内容。
- 窗口容量不变，仍为 `visual_window_size`。本次只改变哪些帧值得占用槽位，不改变图片数量，因此 image token 开销不变，便于把效果归因到选帧策略本身。
- boundary 判据只使用 Pipeline 已产出的结构化字段：该 transition 是否产生 key event，以及 verifier status 是否与窗口内上一帧不同。Memory 不做像素比较、感知哈希或视觉推理。
- 非 boundary 帧共用最后一个槽位。最新观测必须始终在窗口中，否则 Planner 看不到当前场景；但它不应该消耗一个本该留给 boundary 的槽位。
- frame record 增加 `event_type`、`status` 和 `pinned` 三个字段。已有四个 recall 分区的键不变，新增字段是附加的。
- `lesson_reload` 默认 `false` 且必须与 `lesson_path` 同时设置。跨 run 累积会把上一轮结论带进本轮，这是评测语义的改变，必须显式开启。
- 重建复用既有审计日志，不引入第二种持久化格式。按 `lesson_id` 取最后一条记录，`evict` 表示丢弃。
- 重建出的 lesson 的 status 按**当前**配置的 `lesson_min_support` 重新判定，不直接沿用日志中的 status。
- 重建出的 lesson 带 `carried_over: true`，与本 run 新建的 lesson 可区分。

## Open Questions

- `event` 策略在真实 RoboCasa rollout 上的实际保留帧分布未知，需要在对照实验中统计 boundary frame 占比。若 verifier status 抖动频繁，boundary 判据可能退化回接近滑动窗口。
- 跨 run 重建目前不区分 task。同一个 `lesson_path` 被不同 task 复用时会混入无关 lesson，当前只靠 recall 阶段的词面重叠排序和条数上限缓解。是否需要按 task 分文件或在 lesson 上记录 task，等多 task 评测出现后再定。
- 未引入感知哈希做帧去重。等 diagnostic 显示结构化信号不足以识别 steady state 后再考虑。

## Scope

- `TieredMemory` 增加 `frame_selection` 参数，取值 `recent` 或 `event`，并在构造时校验。
- `TieredMemory.update()` 将 `event_type` 提取与校验、`status` 提取上移到方法开头，供选帧判据使用。
- 新增 `_is_salient()` 和 `_admit_frame()`，实现 boundary 独占槽位、steady-state 帧共用尾槽的准入策略。
- frame record 增加 `event_type`、`status`、`pinned` 字段。
- `ReflectiveMemory` 透传 `frame_selection`。
- `ReflectiveMemory` 增加 `lesson_reload` 参数、`_load_lessons()`、`_restore_lesson()` 和 `_lesson_index()`，并在 lesson schema 增加 `carried_over`。
- 补充 unit tests、用户文档、架构文档和 change record。

## Out of Scope

- 不引入新依赖，不做感知哈希、embedding 或任何像素级比较。
- 不改变 `visual_window_size` 的语义，不改变窗口容量。
- 不改变 `frame_selection` 的默认值，不改动现有 benchmark 配置。
- 不修改 `SkillExecutionPipeline`、Verifier 或 Planner 的逻辑。Planner 仍然只把 working frames 当作 image content，本次不新增 frame 级别的 prompt 标注。
- 不为 lesson 引入第二种持久化格式或数据库。
- 不做跨 run 的在线评测，验收只到 unit test 级别。

## Tasks

1. [x] `DONE` 在 `TieredMemory` 实现 `frame_selection` 与 salience-gated 准入。
2. [x] `DONE` 在 `ReflectiveMemory` 透传 `frame_selection` 并实现 `lesson_reload` 重建。
3. [x] `DONE` 补充 unit tests，覆盖 boundary 保留、滑动窗口对照、参数校验、跨 run 重建和脏日志容错。
4. [x] `DONE` 更新 `docs/agent_core/memory.md`、`docs/configuration.md`、`impl_docs/architecture/overview.md`、`impl_docs/TODO.md` 和 change record。

Implementation record: [2026-09-20 salient working memory](../changes/2026-09-20-salient-working-memory.md)。

## Acceptance Criteria

- `frame_selection` 缺省时 working frames 与改动前完全一致，既有 `TieredMemory` 测试全部通过。
- `frame_selection: event` 下，一个失败帧后连续多步 steady-state transition，失败帧仍留在窗口中，而 `recent` 下已被挤出。
- 两种策略下 `len(working_frames)` 上界相同。
- 非法 `frame_selection` 在构造时报错。
- `lesson_reload` 为 `true` 但未设置 `lesson_path` 时构造报错。
- 跨进程重建后 lesson 的 `support_count`、`session_ids` 保留，`carried_over` 为 `true`，status 按当前阈值重新判定，且新 lesson 的 `lesson_id` 不与重建出的 id 冲突。
- 日志中无法解析的行、缺少证据计数的行被跳过，`evict` 记录对应的 lesson 不被重建。
- `pytest`、`ruff check`、`ruff format --check`、`mypy` 全部通过。

## Risks

- boundary 判据依赖 verifier status 的稳定性。status 频繁抖动会让几乎每帧都成为 boundary，策略退化为滑动窗口；此时行为不劣于现状，但收益消失。
- steady-state 帧共用尾槽意味着窗口内相邻帧的 step 不再连续。若 Planner 隐含假设帧是等间隔时间序列，可能产生误判。缓解手段是每个 frame 都带 `step` 和 `event_type`，信息可核对，并且本次不改变 Planner 对 frame 的使用方式。
- 跨 run 重建可能引入陈旧或跨 task 的结论，即记忆投毒。缓解手段是默认关闭、每条 lesson 带 `session_ids` 与 `carried_over` provenance、status 按当前阈值重判、以及注入条数上限 3。
- 审计日志随 run 增长，重建时需要全量读取。lesson 数量受 `lesson_limit` 约束，但日志行数不受约束；长期运行需要外部轮转。
