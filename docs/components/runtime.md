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

1. 检查 Agent health。
2. `agent.reset(session_id)`。
3. `environment.reset(task)` 获取初始 observation。
4. 循环调用 `pipeline.step()`，直到 Pipeline terminal 或 Runtime limit。
5. 写入 result/trace，并按 ownership 关闭资源。

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
```

Runtime 可能产生 `timeout`、`invalid_action_limit`、`retry_limit`、`step_limit`、Pipeline terminal reason 或 `exception`。每条退出路径都会写明确的 `termination_reason`。

## Outputs

```text
<output_dir>/<session_id>/
├── result.json
├── trace.jsonl
└── artifacts/
```

`result.json` 包含 success、progress、steps、invalid actions、replans、planner calls、action chunks、environment steps、latency 和 termination reason。`trace.jsonl` 保存 episode start、每个 step、exception 和 episode end。

下一节：[Environment](environment.md)。
