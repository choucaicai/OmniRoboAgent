# Environment

Environment 连接 benchmark、simulator 或 robot，并在自身边界把 framework payload 转换为外部系统调用。Core 不依赖具体 benchmark SDK。

## Contract

```python
class Environment:
    def reset(self, task: Any) -> Any: ...
    def execute(
        self,
        action: Any,
        execute_steps: int | None = None,
    ) -> dict[str, Any]: ...
    def close(self) -> None: ...
```

当前 contract 没有独立 `observe()`。初始 observation 来自 `reset()`，后续 observation 位于 `execute()` 返回的 result 中。

## Responsibilities

- 校验 action type、key、shape、dtype、range、单位和 protocol。
- 执行 action 或 action chunk。
- 返回新的 observation 和 Pipeline/Verifier 需要的 environment signals。
- 隔离 benchmark SDK 类型，不把它们扩散到 Agent Core。
- 释放 simulator 或外部 client 资源。

Environment result 是普通 `dict`。常见字段包括：

```text
observation
done
task_success
task_progress
last_action_success
env_feedback
executed_steps
```

具体 Pipeline 只读取它需要的字段，框架不要求所有 Environment 返回完全相同的 schema。

## Current Adapters

| Environment | Location | Action |
| --- | --- | --- |
| `EBAlfredEnvironment` | `environments/benchmarks/embodiedbench/` | 单个 language skill |
| `LiberoEnvironment` | `environments/benchmarks/libero/` | 7D relative VLA action chunk |
| `RoboCasaEnvironment` | `environments/benchmarks/robocasa/` | VLA action chunk |

Benchmark-specific 安装和字段见 [EB-ALFRED](../eb_alfred.md)、[LIBERO](../libero.md) 与 [RoboCasa365](../robocasa365.md)。

下一节：[Evaluation](evaluation.md)。
