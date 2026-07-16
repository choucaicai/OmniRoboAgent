# Episode Observability Artifacts

Status: DONE

## Objective

新增独立 `omniroboagent.observability` package，为每个 Runtime session 生成可下载的结构化 Agent trace、episode video 和 artifact manifest。Runtime 只负责调用 recorder lifecycle，不包含日志抽取、画面布局或视频编码实现。

## Reference

RAI 将 Langfuse/LangSmith tracing 作为可注入 callbacks，与 Agent graph state 分离。OmniRoboAgent 借鉴该 provider boundary，但不引入 LangChain、Langfuse 或 LangSmith 依赖；第一版实现本地 deterministic artifacts，并保留以后增加 remote tracing recorder 的 contract。

## Scope

- 新增 `observability.EpisodeRecorder` contract 和 `LocalEpisodeRecorder`。
- 生成 `agent_trace.jsonl`，记录 episode、Planner/skill、verification、transition、environment feedback 和 terminal event，不复制完整 observation image 或 provider raw response。
- 使用 FFmpeg 将配置的 observation camera keys 合成为 `episode.mp4`，并叠加 step、skill/subtask 和 verification 信息。
- 生成 `artifact_manifest.json`，列出 result、完整 trace、精简 Agent trace、video 和 artifact directory。
- `SyncRuntime` 增加可选 `observability` 参数；未配置时保持现有输出和行为。
- 为 EB-ALFRED 和 RoboCasa composite smoke RunConfig 增加 recorder 配置。
- 更新 architecture、user docs、TODO 和 change record。

## Boundaries

- `observability` 只依赖标准库、Pillow 和 framework serialization helper，不依赖 benchmark SDK、LangChain 或 remote tracing SDK。
- Recorder 只观察 episode events，不修改 state、Planner output、Verifier result 或 Pipeline transition。
- 第一版每个 Runtime step 记录一帧；RoboCasa action chunk 内的 low-level frame recording 留在 benchmark Environment 后续扩展。
- 视频启用时要求可用 FFmpeg executable；不新增 Python video dependency。
- observability failure 必须显式记录，不能静默生成损坏 artifact，也不能覆盖 episode 原始 success/termination result。

## Tasks

- [x] 实现 recorder contract、本地 structured trace、video writer 和 manifest。
- [x] 将 optional recorder lifecycle 接入 `SyncRuntime`。
- [x] 增加 unit tests，覆盖 trace fields、manifest、video frame composition、异常和复用。
- [x] 更新 EB-ALFRED 与 RoboCasa composite smoke configs。
- [x] 更新 architecture、Runtime/benchmark user docs 和输出说明。
- [x] 运行 scoped unit tests、lint、format、type check、link check 和 FFmpeg smoke。

## Acceptance

- 配置 recorder 后，每个成功或失败 session 都有 `agent_trace.jsonl` 和 `artifact_manifest.json`。
- 有可用 camera frame 时生成可播放的 H.264 `episode.mp4`，manifest 和 Runtime result 包含 artifact paths 与 frame count。
- Agent trace 可直接定位每步 skill/subtask、Planner call、verification、decision/recovery 和 environment feedback。
- recorder 可跨 benchmark episodes 复用且不泄漏上一 session state。
- 未配置 recorder 时现有 Runtime tests 和输出保持兼容。
