# Observability

Observability 负责把一次 episode 的 Agent 调用过程和画面保存为可检查的本地 artifacts。它只观察 Runtime lifecycle，不修改 Pipeline state、Planner output、Verifier decision 或 benchmark result。

## Contract

`EpisodeRecorder` 提供以下 lifecycle：

```python
class EpisodeRecorder:
    def start(self, session_dir: Path, session_id: str, task: Any) -> None: ...
    def record_observation(
        self,
        observation: Any,
        *,
        step: int,
        labels: list[str] | None = None,
    ) -> None: ...
    def record_step(
        self,
        step: int,
        output: dict[str, Any],
        observation: Any,
    ) -> None: ...
    def record_exception(self, step: int, error: Exception) -> None: ...
    def finish(self, result: dict[str, Any]) -> dict[str, Any]: ...
```

当前实现 `LocalEpisodeRecorder` 生成：

```text
<runtime.output_dir>/<session_id>/
├── result.json
├── trace.jsonl
├── agent_trace.jsonl
├── episode.mp4
├── artifact_manifest.json
└── artifacts/
```

- `trace.jsonl`：Runtime 原始 step trace，保留完整的可序列化 Pipeline output。
- `agent_trace.jsonl`：面向诊断的精简 trace，记录 Planner/skill/subtask、action 摘要、verification、transition、environment feedback 和 terminal result，不复制 observation image 或完整 provider response。
- `episode.mp4`：配置 camera keys 的横向合成画面，叠加 step、skill/subtask 和状态信息。
- `artifact_manifest.json`：列出 session artifacts、video frame count、FPS、camera keys 和 recorder errors。

## Configuration

```yaml
runtime:
  class_path: omniroboagent.runtimes.SyncRuntime
  init_args:
    output_dir: runs/example/traces
    observability:
      class_path: omniroboagent.observability.LocalEpisodeRecorder
      init_args:
        record_agent_trace: true
        record_video: true
        video_camera_keys:
          - camera.front
          - camera.wrist
        video_fps: 4
        ffmpeg_path: ffmpeg
```

`video_camera_keys` 必须与 Environment observation 的实际字段一致。多路相机会按配置顺序横向排列；缺少的 camera key 会被跳过。只有所有配置 key 都没有可用 frame 时，视频不会生成，错误会写入 manifest 和 `result.json` 的 `observability_errors`。

视频使用系统 FFmpeg 编码 H.264，不新增 Python video dependency。启用前检查：

```bash
ffmpeg -version
```

Recorder 错误不会覆盖 episode 的 `success` 或 `termination_reason`。当前每个 Runtime step 记录一帧；action chunk 内的 low-level simulator frames 尚未记录，因此视频用于展示 Agent 控制过程，不代表 simulator 原始帧率。

下一节：[Environment](environment.md)。
