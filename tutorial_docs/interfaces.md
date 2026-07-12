# Interface Reference

公共 contracts 位于 [`src/omniroboagent/contracts.py`](../src/omniroboagent/contracts.py)。Core 只依赖标准库和轻量 contract 依赖。

## LLMBackend

```python
complete(inputs: dict[str, Any]) -> dict[str, Any]
healthcheck() -> dict[str, Any]
close() -> None
```

`OpenAICompatibleLLMBackend` 接受 `messages`、`temperature`、`max_tokens`、`response_format` 等字段，返回 provider 原始 JSON，并增加 `_backend` latency 和 attempts。

构造参数为 `base_url`、`model`、可选 `api_key`、`timeout_seconds` 和 `max_retries`。`base_url` 会自动补 `/v1`，`api_key` 未传入时读取 `OPENAI_API_KEY`，仍为空时使用 `EMPTY`。

图片输入支持：

- 本地路径
- HTTP URL
- OpenAI data URL
- `bytes`
- PIL image
- NumPy array
- 单图和多图

图像必须位于 OpenAI multimodal message 的 `image_url.url` 中。backend 会把本地路径、bytes、PIL image 和 NumPy array 转成 data URL，HTTP URL 和已有 data URL 保持不变。

`healthcheck()` 请求 `/v1/models`。只有目标 model 出现在返回列表中，或服务返回空列表时，结果才为 healthy。

## Planner

```python
plan(inputs: dict[str, Any]) -> Any
```

`LanguageSkillPlanner` 使用：

```text
task
observation
available_skills
history
```

它要求模型每轮只返回一个 skill。输出是包含 `skill`、`reasoning`、`model_output` 和 `raw_response` 的普通字典。

`extra_body` 会原样合并到 OpenAI-compatible 请求体，可传 provider-specific 参数。Qwen thinking model 在当前单 skill 评测中建议关闭 thinking，避免 reasoning 占满输出预算后 `content` 为空：

```yaml
planner:
  init_args:
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
```

Planner 要求 response content 是 JSON object。该对象可以使用 `skill`、整数 `action_id`，或 EmbodiedBench baseline 风格的 `executable_plan` 首个 action；`skill` 字段还兼容纯数字字符串和 `64: find a Ladle` 形式的 action-id 前缀。

`LanguageSkillPlanner` 会把动态 `available_skills` 写入 JSON schema enum，并验证最终 skill 确实存在。`PlannerOutputError` 会被 `DirectPipeline` 转换为一次失败验证；其他异常由 Runtime 记录为 `termination_reason=exception`。

## SkillBackend

```python
predict(inputs: dict[str, Any]) -> Any
```

`LanguageSkillBackend` 返回同一个 `inputs["skill"]` 对象。

`OpenPIWebSocketPolicyBackend` 使用官方 OpenPI msgpack/WebSocket client protocol：

```python
backend = OpenPIWebSocketPolicyBackend(
    host="127.0.0.1",
    port=8001,
)
actions = backend.predict({"observation": observation})
```

安装 OpenPI optional dependency：

```bash
python -m pip install -e '.[openpi]'
```

该版本固定到 OpenPI commit `51fb06be280a967e59292cf63bb597aa3efdab6c`。

构造参数：

- `host`、`port`：OpenPI server 地址。
- `api_key`：可选鉴权信息。
- `timeout_seconds`：healthcheck 和单次 infer timeout。
- `action_key`：从 server response 中读取 action chunk 的 key，默认 `actions`。

`predict()` 要求 `inputs["observation"]` 是 dict，返回 response 中 `action_key` 对应的对象。首次请求前执行 `/healthz`，连接或推理失败时最多重建一次 client。`close()` 只关闭 WebSocket client，不关闭 policy server。

## Verifier

```python
verify(inputs: dict[str, Any]) -> dict[str, Any]
```

`EnvironmentVerifier` 读取 Environment result 中的 authoritative fields：

```text
task_success
task_progress
last_action_success
done
env_feedback
```

Verifier 不决定全局终止枚举。`DirectPipeline` 解释这些字段。

## Memory

```python
update(state: dict[str, Any], event: dict[str, Any]) -> None
```

- `InMemoryMemory`：保存当前进程中的 event 列表。
- `JsonlMemory`：append-only JSONL；array、image 和自定义对象记录摘要。

Runtime 自己始终写 episode trace，因此 Memory 是否持久化不会影响评测结果文件。

`JsonlMemory` 不会在构造时清空已有文件；重复使用同一路径会继续 append。Runtime session trace 则会在同名 session 开始时清空。

## Environment

```python
reset(task: Any) -> Any
execute(action: Any, execute_steps: int | None = None) -> dict[str, Any]
close() -> None
```

Environment 在使用点校验开放 action payload。benchmark SDK 类型不能扩散到 Core。

当前 contract 没有独立 `observe()`：初始 observation 由 `reset()` 返回，后续 observation 放在 `execute()` 结果的 `observation` 字段中。

## BaseAgent

```python
plan(inputs) -> Any
predict_action(inputs) -> Any
verify(inputs) -> dict
update(state, event) -> None
healthcheck() -> dict
close() -> None
```

`DefaultAgent` 只委托 Planner、Verifier、Memory 和 SkillBackend，不包含 Pipeline。

`healthcheck()` 同时检查 Planner 和 SkillBackend；两者都 healthy 时 Agent 才 healthy。`close()` 依次关闭 Planner、SkillBackend 和 Memory 的客户端资源。

## Pipeline

```python
step(agent, environment, state) -> dict[str, Any]
is_terminal(output, state) -> bool
```

`DirectPipeline` 的内部 decision 为 `continue`、`retry`、`success`、`failure`，但这不是所有 Pipeline 必须遵守的全局协议。

当前 `DirectPipeline` 从 observation 读取 `available_skills`；非 list 时按空列表处理，非空时验证 Planner 选择的 skill。`LanguageSkillPlanner` 本身要求该列表非空。Pipeline 每轮只执行一个 action，把 `last_action_success=false` 记为 invalid action，并把 task success 和 environment done 分别映射为成功与失败终止。

## Runtime

```python
run(agent, pipeline, environment, task, **kwargs) -> dict[str, Any]
```

`SyncRuntime` 管理 healthcheck、episode 生命周期、step/invalid/retry/time limits、trace、异常终止和资源关闭。它只通过 `Pipeline.is_terminal()` 判断自定义 Pipeline 是否结束。

构造参数：

- `max_steps`：episode 最大 Pipeline step。
- `max_invalid_actions`：累计 invalid action 上限。
- `max_retries`：连续 retry 上限。
- `timeout_seconds`：可选 wall-time 上限，在相邻 step 之间检查。
- `output_dir`：每个 session trace/result 的根目录。

返回结果至少包含：

```text
session_id, success, task_progress, steps, invalid_actions, replans,
latency_seconds, termination_reason, trace_path
```

正常终止原因包括 `task_success`、`environment_done`、`pipeline_terminal`、`invalid_action_limit`、`retry_limit`、`step_limit` 和 `timeout`。未处理异常记录为 `exception`，同时保存 `error_type` 与 `error`。资源关闭错误写入 `close_errors`，不会覆盖 episode 结果。

`replans` 当前只在 invalid action 时递增，不表示 Planner 的总调用次数。
