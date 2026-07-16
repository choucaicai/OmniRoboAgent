# Verifier

Verifier 在 action 执行后读取 environment result 和相关 evidence，输出结构化 verification。Planner 不负责判断 subtask completion，Runtime 也不解释 Verifier 的业务字段；这些字段由当前 Pipeline 消费。

## Contract

```python
class Verifier:
    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]: ...
    def healthcheck(self) -> dict[str, Any]: ...
    def close(self) -> None: ...
```

Verifier 必须返回普通 `dict`，但框架不定义全局固定 decision enum。

## `EnvironmentVerifier`

用于 Environment 已提供 authoritative signal 的简单闭环。它透传并规范化：

```text
task_success
task_progress
last_action_success
environment_done
env_feedback
```

`DirectPipeline` 根据这些字段决定 success、failure、retry 或 continue。

## `SubtaskVerifier`

用于长程 skill execution，输出：

```text
execution_status: in_progress | completed | failed | uncertain
reason
confidence
evidence
```

判断优先级是：

1. benchmark authoritative `task_success`；
2. environment done 或 action failure；
3. Environment 提供的显式 `execution_status`；
4. 可选 model backend 的 before/after visual verification；
5. 缺少 completion evidence 时保持 `in_progress`。

`check_interval_chunks` 可以降低视觉语义检查频率。`uncertain` 不等于失败，`SkillExecutionPipeline` 可以在不执行新 action 的情况下 reverify。

```yaml
verifier:
  class_path: omniroboagent.agent_core.SubtaskVerifier
  init_args:
    check_interval_chunks: 4
```

仅在需要视觉判断时配置 model backend。具体 provider 由 [Model Backend](../components/model_backend.md) 隔离。

下一节：[Memory](memory.md)。
