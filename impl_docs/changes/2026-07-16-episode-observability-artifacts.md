# Episode Observability Artifacts

Date: 2026-07-16
Related plan: `impl_docs/plans/0012-episode-observability-artifacts.md`

## Changed

- 新增独立 `omniroboagent.observability` package，提供 `EpisodeRecorder` contract、`LocalEpisodeRecorder` 和 FFmpeg H.264 video writer。
- `SyncRuntime` 增加可选 recorder lifecycle hooks；recorder failure 写入 `observability_errors`，不改变 episode success 或 termination reason。
- 每个已配置 session 生成精简 `agent_trace.jsonl` 和 `artifact_manifest.json`；存在配置 camera frames 时生成多路横向 `episode.mp4`。
- Agent trace 排除 observation image 和完整 provider response，保留 Planner/skill/subtask、action 摘要、verification、transition 和 environment feedback。
- EB-ALFRED 及 RoboCasa composite remote/local smoke RunConfig 启用本地 trace/video；RoboCasa resolved config 记录 recorder class、camera keys、FPS 和开关。
- 同步 architecture、Runtime、Evaluation、Configuration、Quickstart 和 benchmark 用户文档。

## Files

- `src/omniroboagent/observability/`
- `src/omniroboagent/runtimes/sync.py`
- `src/omniroboagent/evals/benchmarks/robocasa/evaluator.py`
- `configs/runs/eb_alfred_smoke.yaml`
- `configs/runs/robocasa365_groot_composite_{remote,local}_smoke.yaml`
- `tests/unit/`
- `README.md`
- `docs/`
- `impl_docs/`

## Verification

- `conda run -n omniagent python -m pytest -q`：124 passed。
- `conda run -n omniagent ruff check src tests`：通过。
- `conda run -n omniagent mypy`：62 个 source files 无问题。
- `conda run -n omniagent ruff format --check <owned Python files>`：本次 10 个 Python files 已格式化。
- 全部 12 个 checked-in YAML 解析通过。
- 真实 FFmpeg smoke：生成 H.264、80x116、2-frame `episode.mp4`，并通过 `ffprobe` 校验。
- 本地 Markdown link checker：检查本次 16 个变更 Markdown files 的相对链接，全部存在。
- 本次 owned files `git diff --check`：通过。
- Repository-wide `ruff format --check src tests` 未通过，只命中 5 个本次未修改的既有文件；未格式化或纳入这些无关改动。

## Remaining Work

- 尚未重跑真实 EB-ALFRED 和 RoboCasa composite Agent episodes；本次完成 framework/unit/config/FFmpeg artifact 验证。
- 当前视频每个 Runtime step 记录一帧；RoboCasa action chunk 内的 low-level frames 尚未记录。
- session directory 已是完整 artifact bundle；本次未增加 ZIP/download server。
