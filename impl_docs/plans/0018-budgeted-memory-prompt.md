# De-duplicated And Budgeted Memory Prompt

Status: DONE

## Goal

[0009](0009-tiered-agent-memory.md) 到 [0017](0017-procedural-memory-and-labelled-frames.md) 一路在给 memory **加分区**：key events、lessons、object state、procedures。但这些分区怎么进 prompt 一直没人管——`_memory_prompt` 从第一版起就是「把几个分区原样 `json.dumps` 一遍」，加一个分区就在后面接一段。

实测这条路已经走到头了。用 30 条合成 event 喂 `ReflectiveMemory`，按分区量一遍注入端渲染出的字符数：

| 分区 | 字符 | 占比 |
| --- | --- | --- |
| `key_events` | 7774 | 42.1% |
| `recent_events` | 5294 | 28.7% |
| `summary` | 4104 | 22.2% |
| `lessons` | 627 | 3.4% |
| `object_state` | 595 | 3.2% |

两个问题。

**其一，`key_events` 是纯重复。** `summary` 的构造方式就是把各条 key event 的 `text_summary` 顺序拼接。上面这段记忆里，最近 10 条 key event 的 `text_summary` **全部 10 条**逐字出现在 `summary` 中。也就是说 prompt 里最大的一块，携带的新信息只有 `evidence_summary`——恰恰是 `summary` 唯一丢掉的字段。

**其二，价值密度最高的分区拿到的份额最低。** 花三个 plan 蒸馏出来的 `lessons` + `object_state` 合计只占 6.6%，被两块叙事挤在角落。Context Rot 的结论是，长上下文中被大量近似重复包围的少量关键信息会被稀释；这里的排布正好是那个反面教材。

而且现在**没有任何上限**。`recent_events` 和 `key_events` 各自硬编码 `[-10:]`，但单条记录的长度不受控，`summary_max_chars` 只管 `summary` 一个分区。prompt 里的 memory 部分实际可以长到多少，配置上答不出来。

## Confirmed Decisions

- 去重方向是**用 `summary` 压 `key_events`**，不是反过来。`summary` 有 `summary_max_chars` 管着且天然连续，`key_events` 是离散记录，砍掉重复部分后剩下的 `evidence_summary` 正好是 `summary` 缺的那块。
- 被 `summary` 覆盖的 key event，只发 `step=N evidence=...`；既被覆盖又没有 evidence 的**整条不发**。
- `recent_events` 压成每条一行 `step/event/status/reason`。原记录里的 `artifact_refs`、`timestamp`、`session_id` 对下一步决策没有用。
- 填充顺序按**决策价值密度**：`object_state` → `lessons` → `procedures` → `key_events` → `recent_events` → `summary`。
- `summary` 排在**最后**。它是重复度最高的一块，若按原来的想法排在 `key_events` 之前，实测会吃掉 4096 预算里的 2907，把后面所有分区饿死（第一版实现出现过这个结果）。
- 因此 `key_events` 的去重对照的是**未截断**的 `summary`。`summary` 从最旧一端截断而 key events 取最新 10 条，被检查的那批事件正是 summary 行能留下来的那批。
- 预算以**字符**计，不是 token。core 依赖只有 `httpx`、`Pillow`、`PyYAML`，为了计 token 引入 tokenizer 会破坏这条边界；字符数是 token 数的稳定上界，够用。
- 超限必须**显式报告**。丢掉的内容写进 payload 的 `dropped` 键，列表分区记 `"name[oldest N]"`，整块放不下记 `"name"`。被截断的 prompt 不能看起来像完整的 prompt。
- 预算归**注入端**所有，不归 Memory。Planner 和 Verifier 各有一个 `memory_char_budget`，默认 4096。Memory 决定记住什么，注入端决定这次发多少——两者不该耦合。
- Verifier 也走同一个渲染函数。此前 `SubtaskVerifier` 自己维护一份只含 `summary`/`recent_events`/`key_events` 的渲染，既重复又拿不到 0014 之后新增的分区。
- 不改 `recall()` 的任何返回值。这是纯注入端改动，Memory 的 contract 不动。

## Open Questions

- 默认 4096 字符没有经过真实 rollout 校准。既有 audit 里 planner prompt 在 22k–24k token 量级，4096 字符（约 1k–1.5k token）是个保守起点，合适与否未测。
- 覆盖判断用的是 `text in summary` 的子串匹配。`text_summary` 由同一段代码生成且逐字拼进 `summary`，所以当前精确成立；若将来 `summary` 改成摘要式生成，这个判断会失效并退化为「全部保留」（偏安全的方向）。
- 按 `json.dumps` 长度计费，包含引号和转义开销。相对排序不受影响，绝对值略高于纯文本长度。
- 各分区之间没有配额下限。极小预算下靠优先级顺序保证蒸馏分区先进，但没有「`summary` 至少留 N 字符」这类约束。
- 去重省下的空间是否真的转化为决策质量，未做在线测量。当前只有离线字符数。

## Scope

- `agent_core/prompting.py` 增加 `DEFAULT_MEMORY_CHAR_BUDGET`、`EVENT_RENDER_LIMIT`、`MEMORY_PARTITION_PRIORITY` 和 `memory_text_payload()`，以及 `_entry_texts()`、`_recent_event_lines()`、`_key_event_lines()`、`_fit()`、`_cost()` 五个私有渲染函数。
- `LanguageSkillPlanner._memory_prompt` 改为调用 `memory_text_payload()`；`_memory_prompt` 由 `@staticmethod` 改为实例方法以读取预算。
- `LanguageSkillPlanner`、`SubtaskSkillPlanner`、`SubtaskVerifier` 各增加 `memory_char_budget` 参数并校验为正。
- `SubtaskVerifier` 删除自有的 memory 渲染，改走共享函数。
- 补充 unit tests、用户文档、架构文档和 change record。

## Out Of Scope

- 不引入 tokenizer 或任何新依赖。
- 不修改任何 Memory 实现，不改 `recall()` 返回的分区、字段或语义。
- 不修改 working frame 的渲染（`working_frame_content()` 不动），不改变图片数量或顺序。
- 不修改 Pipeline transition、Verifier 判定逻辑或 Planner 的 JSON schema。
- 不做在线评测，不改动现有 benchmark 配置的默认行为之外的部分。

## Tasks

1. [x] `DONE` 实测既有渲染的分区字符占比和 `key_events` / `summary` 的重复率。
2. [x] `DONE` 实现去重、压行、优先级填充和 `dropped` 报告。
3. [x] `DONE` 三处注入点接 `memory_char_budget` 并校验。
4. [x] `DONE` 复测前后字符数。
5. [x] `DONE` 补充 unit tests。
6. [x] `DONE` 更新用户文档、架构文档、`TODO.md` 和 change record。
