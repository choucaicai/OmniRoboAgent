# Interface Reference

公共 contracts 位于各自 ownership package 的 `base.py`。Agent、Planner、Verifier 和 Memory 位于 [`agent_core/`](https://github.com/choucaicai/OmniRoboAgent/tree/master/src/omniroboagent/agent_core)，其他 contracts 位于 `pipelines/`、`runtimes/`、`environments/` 和对应 backend package。Core 只依赖标准库和轻量 contract 依赖。

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
memory_context
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

`TaskSkillPlanner` 用于 RoboCasa VLA evaluation：它把当前 concrete task name 作为 `skill`，把 environment task description 作为 `subtask`，并提供 `grounded_arguments` 与 `expected_outcome`，不调用 LLM。GR00T `model_moe_v1` 因此收到例如 `CloseBlenderLid`，而不是宽泛的 `Close_Lid` 标签。

`SubtaskSkillPlanner` 用于 RoboCasa composite task。它从 observation 的 `available_skills` 中选择 macro skill，生成具体 `subtask`、结构化 `grounded_arguments` 和可观察的 `expected_outcome`，并通过 AgentConfig 中的可信 `skill_ids` 映射补充整数 ID。Planner 只提出 execution proposal，不判断 subtask completion；continue 由 Pipeline 保持同一个 `active_execution` 实现，不依赖模型重复相同 wording。

两个 LLM Planner 都显式读取 `memory_context.summary`、最近 10 条 `recent_events` 和 `working_frames`。summary/events 进入 text prompt，working frames 作为按时间排序的 image content；缺少 memory context 时行为保持兼容。

模型 JSON 字段为 `reasoning`、`skill`、`subtask`、`grounded_arguments` 和 `expected_outcome`。Planner 返回值额外包含本地映射的 `skill_id`、原始 `model_output` 和 `raw_response`；`reasoning` 用于 trace，不作为 GR00T language instruction。Composite VLA request 使用 `subtask` 覆盖 `annotation.human.task_description`。

## SkillBackend

```python
predict(inputs: dict[str, Any]) -> Any
```

`LanguageSkillBackend` 返回同一个 `inputs["skill"]` 对象。

`SkillBackendRegistry` 将稳定配置名映射到 backend class。内置 `groot_remote`、`openpi_remote` 和 `local`；`build_agent()` 接受 `skill_backend.name + init_args`，并保留 `class_path` fallback。registry 只支持代码显式注册，不扫描 Python entry points。

`GR00TRemotePolicyBackend` 兼容 RoboCasa GR00T 的 ZeroMQ + `torch.save` 协议，负责 healthcheck、metadata、timeout、一次 reconnect、episode memory reset、GR00T observation batch 维度和五个 action key 的 shape/dtype/range 校验。

GR00T local/remote 共用 request builder。没有显式 `planner_output.skill_id` 时，backend 严格要求 `skill == task_name`，用于 atomic task；存在合法非负整数 ID 时，request 可以同时发送 composite `task`、atomic macro `skill`、`skill_id` 和 concrete subtask。

`LocalPolicyBackend` 包装已经实例化的 in-process policy，支持 `predict`、`infer`、`get_action` 或 callable entrypoint，可选从 mapping 中提取 `action_key`。存在 policy `healthcheck()` / `close()` 时会委托调用。`GR00TLocalPolicyAdapter` lazy load 参考 GR00T policy，避免构造 Agent 时立即占用 CUDA。

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
conda activate omniagent
uv pip install --python "$CONDA_PREFIX/bin/python" --editable '.[openpi]'
```

该版本固定到 `robocasa-benchmark/openpi` commit `5a6beda9ff99da30b4e1b59320f6a32971d7c397`，其 client metadata 兼容 RoboCasa 使用的 NumPy 2。

构造参数：

- `host`、`port`：OpenPI server 地址。
- `api_key`：可选鉴权信息。
- `timeout_seconds`：healthcheck 和单次 infer timeout。
- `action_key`：从 server response 中读取 action chunk 的 key，默认 `actions`。

`predict()` 要求 `inputs["observation"]` 是 dict，返回 response 中 `action_key` 对应的对象。首次请求前执行 `/healthz`，连接或推理失败时最多重建一次 client。`close()` 只关闭 WebSocket client，不关闭 policy server。

registry 的 `openpi_remote` 使用 `OpenPIRoboCasaPolicyBackend`：按官方 RoboCasa OpenPI evaluator 构造三路 image、16-D state、prompt，并把 `[T,12]` response 拆成 Environment 接受的五个 action key。通用 `OpenPIWebSocketPolicyBackend` 仍可通过 `class_path` 做 passthrough。

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

`SubtaskVerifier` 为 `SkillExecutionPipeline` 输出：

```text
execution_status = in_progress | completed | failed | uncertain
reason
confidence
evidence
task_success / task_progress / last_action_success / environment_done
```

benchmark `task_success`、environment done 和 action failure 优先于视觉模型。配置 `backend` 后，Verifier 比较 action 前后 observation 与 active execution 的 `expected_outcome`；`check_interval_chunks` 控制视觉语义检查频率。未配置 backend 时，成功执行且没有结构化 completion evidence 的 action 返回 `in_progress`。

`SubtaskVerifier` 的 VLM 请求显式包含 `memory_context.summary`、最近 events 和 working frames。Pipeline 只负责传递 context，不读取图像或 summary 判断 completion。

## Memory

```python
reset(session_id: str) -> None
update(state: dict[str, Any], event: dict[str, Any]) -> None
recall(query: dict[str, Any]) -> dict[str, Any]
healthcheck() -> dict[str, Any]
close() -> None
```

- `InMemoryMemory`：保存当前 episode 的 event 列表，reset 时清空。
- `JsonlMemory`：append-only JSONL；array、image 和自定义对象记录摘要。
- `TieredMemory`：bounded visual working frames、structured long-term events 和 bounded deterministic text summary。

`TieredMemory.recall()` 返回：

```text
working_frames
recent_events
summary
```

`visual_window_size` 默认 `4`，按 observation timestep 计数，每个 timestep 可以包含多 camera。raw frames 只存在 bounded working deque；event JSONL 不保存 raw observation、action tensor 或 provider raw response。`event_path` 可选，未配置时 event memory 保存在当前 Agent 进程中。

Pipeline 使用 `session_id` 查询当前 episode context，避免默认把其他 episode 的 event 注入 Planner/Verifier；调用方显式设置其他 scope 时仍可访问长期 event memory。

Runtime 自己始终写 episode trace，因此 Memory 是否持久化不会影响评测结果文件。

`JsonlMemory` 和 `TieredMemory.event_path` 不会在构造时清空已有文件；重复使用同一路径会继续 append。Runtime session trace 则会在同名 session 开始时清空。

## Environment

```python
reset(task: Any) -> Any
execute(action: Any, execute_steps: int | None = None) -> dict[str, Any]
close() -> None
```

Environment 在使用点校验开放 action payload。benchmark SDK 类型不能扩散到 Core。

当前 contract 没有独立 `observe()`：初始 observation 由 `reset()` 返回，后续 observation 放在 `execute()` 结果的 `observation` 字段中。

`RoboCasaEnvironment` lazy import 固定 submodule，创建一个官方 Gym environment，逐 low-level step 执行 action chunk，并在 authoritative `info["success"]`、simulator termination 或 task horizon 时停止。它严格要求五个 action key 具有同一正 chunk horizon、floating dtype、有限值和 controller range；为兼容官方 GR00T min-max inverse 的轻微数值越界，range check 允许 `0.05` tolerance，但不 clip action。

默认 observation 的 `available_skills` 为当前 `[task_name]`。Composite RunConfig 可以通过构造参数提供非空、唯一的 macro skill 列表；Environment 只暴露 catalog，不负责选择 skill 或映射 ID。

`RoboCasa365Evaluator` 不是 core base class。它解析官方 `task_set` 与独立 `split`，运行 task/episode loop，并写入 `episodes.jsonl`、`summary.json` 和 `resolved_config.json`。当前 `episode_index` 通过 `seed + index` 驱动 reset，不是 dataset scenario id。

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

`BaseAgent` constructor 固定组合 Planner、Verifier、Memory 和 SkillBackend。继承类实现 `plan()`、`predict_action()` 和 `verify()`；基类提供 `reset()`、`update()`、`recall()`、`healthcheck()` 和幂等 `close()`。`healthcheck()` 同时检查四个组件；`close()` 会尝试关闭全部四个组件，并聚合 close error。

## Pipeline

```python
step(agent, environment, state) -> dict[str, Any]
is_terminal(output, state) -> bool
```

`DirectPipeline` 的内部 decision 为 `continue`、`retry`、`success`、`failure`，但这不是所有 Pipeline 必须遵守的全局协议。

当前 `DirectPipeline` 从 observation 读取 `available_skills`；非 list 时按空列表处理，非空时验证 Planner 选择的 skill。`LanguageSkillPlanner` 本身要求该列表非空。Pipeline 每轮只执行一个 action，把 `last_action_success=false` 记为 invalid action，并把 task success 和 environment done 分别映射为成功与失败终止。

`SkillExecutionPipeline` 在 Runtime state 中维护 `active_execution`、`verification`、`transition`、`completed_executions`、`failed_executions` 和 `execution_history`。`active_execution` 包含稳定 `execution_id`、可递增 `attempt_id`、skill/subtask、grounded arguments、expected outcome、status 和 counters。

每个 `step()` 最多执行一个 Environment action；`uncertain` 的下一 step 只 reverify，执行零个 action。确定性转换为：

```text
completed -> close execution -> plan next
in_progress -> keep execution
failed -> retry_current / replan / fallback / abort
uncertain -> reverify, exhausted 后 recovery
task_success -> terminal
```

构造参数包括 `max_chunks_per_skill`、`max_attempts_per_execution`、`max_uncertain_verifications`、可选 `max_no_progress_steps`、可选 `max_replans` 和可选 `fallback_proposal`。`planner_check_interval_chunks` 只为旧 RunConfig 兼容保留，不再控制 completion。loop signature 使用 skill、grounded arguments 和 expected outcome，不依赖 subtask wording。

`PlannerOutputError` 会产生一个没有 Environment action 的 retry step，并计入 Runtime 的 invalid/retry budget。因此 composite evaluation 的 `invalid_actions` 可能表示 Planner contract mismatch，不一定是 VLA action array 非法。

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
planner_calls, action_chunks, environment_steps, latency_seconds,
termination_reason, trace_path
```

正常终止原因包括 `task_success`、`environment_done`、`execution_aborted`、`pipeline_terminal`、`invalid_action_limit`、`retry_limit`、`step_limit` 和 `timeout`。未处理异常记录为 `exception`，同时保存 `error_type` 与 `error`。资源关闭错误写入 `close_errors`，不会覆盖 episode 结果。

`planner_calls` 是 planner 总调用次数。`replans` 统计 invalid action 触发的重新规划，以及 Pipeline 明确报告的 replan/fallback recovery；`in_progress` execution 不调用 Planner。
