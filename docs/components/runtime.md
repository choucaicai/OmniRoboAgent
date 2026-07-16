# Runtime

Runtime 管理 episode lifecycle、limits、trace、异常捕获和资源释放。它调用 Pipeline，但不解释 Planner、action 或 Verifier 的业务语义。

## Contract

```python
class Runtime:
    def run(
        self,
        agent: BaseAgent,
        pipeline: Pipeline,
        environment: Environment,
        task: Any,
        **kwargs: Any,
    ) -> dict[str, Any]: ...
```

## `SyncRuntime`

当前实现是同步单环境 `SyncRuntime`。每个 session 的初始 state 包含：

```text
task
observation
step
session_id
artifact_dir
history
```

运行顺序：

1. 启动可选的 episode recorder。
2. 检查 Agent health。
3. `agent.reset(session_id)`。
4. `environment.reset(task)` 获取初始 observation 并记录首帧。
5. 循环调用 `pipeline.step()`，直到 Pipeline terminal 或 Runtime limit；每个 step 通知 recorder。
6. 写入 result/trace、结束 recorder，并按 ownership 关闭资源。

## Limits

```yaml
runtime:
  class_path: omniroboagent.runtimes.SyncRuntime
  init_args:
    max_steps: 30
    max_invalid_actions: 10
    max_retries: 10
    timeout_seconds: 1800
    output_dir: runs/example/traces
    observability:
      class_path: omniroboagent.observability.LocalEpisodeRecorder
      init_args:
        record_agent_trace: true
        record_video: true
        video_camera_keys: [camera.front]
        video_fps: 4
```

Runtime 可能产生 `timeout`、`invalid_action_limit`、`retry_limit`、`step_limit`、Pipeline terminal reason 或 `exception`。每条退出路径都会写明确的 `termination_reason`。

## Outputs

```text
<output_dir>/<session_id>/
├── result.json
├── trace.jsonl
├── agent_trace.jsonl          # configured recorder
├── episode.mp4                # configured recorder with camera frames
├── artifact_manifest.json     # configured recorder
└── artifacts/
```

`result.json` 包含 success、progress、steps、invalid actions、replans、planner calls、action chunks、environment steps、latency 和 termination reason。`trace.jsonl` 保存 episode start、每个 step、exception 和 episode end。

启用 recorder 后，artifact paths 和 video frame count 也会写入 `result.json`。Recorder 失败记录在 `observability_errors`，不改变 episode success 或 termination reason。详细字段、FFmpeg 要求和当前帧率限制见 [Observability](observability.md)。

下一节：[Environment](environment.md)。
