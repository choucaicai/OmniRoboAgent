# Agent

`BaseAgent` 定义 Agent Core 的组合边界。它持有 Planner、Verifier、Memory 和 SkillBackend，并统一管理 healthcheck、session reset 和 close lifecycle。

## Contract

```python
class BaseAgent:
    def plan(self, inputs: dict[str, Any]) -> Any: ...
    def predict_action(self, inputs: dict[str, Any]) -> Any: ...
    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]: ...
    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None: ...
    def recall(self, query: dict[str, Any]) -> dict[str, Any]: ...
```

Pipeline 决定每个方法的调用顺序和输入字段。Agent contract 不固定 Planner output 或 action payload 的具体类型。

## `DefaultAgent`

`DefaultAgent` 是当前默认组合实现：

- `plan()` 委托给 `Planner.plan()`。
- `predict_action()` 委托给 `SkillBackend.predict()`。
- `verify()` 委托给 `Verifier.verify()`。
- `update()` 和 `recall()` 由 `BaseAgent` 委托给 Memory。

它不包含 benchmark、provider 或 Pipeline-specific 分支。大多数场景只需要替换内部组件，不需要创建新的 Agent 子类。

## Lifecycle

`SyncRuntime` 在 episode 开始时调用 `agent.healthcheck()` 和 `agent.reset(session_id)`。结束时 `agent.close()` 依次关闭 Planner、Verifier、SkillBackend 和 Memory；重复调用 `close()` 不会重复释放资源。

```yaml
agent:
  class_path: omniroboagent.agent_core.DefaultAgent
```

只有当 Agent 本身需要改变组件委托方式时才继承 `BaseAgent`。改变调用顺序或状态转换应实现 [Pipeline](../components/pipeline.md)，改变模型或 policy 连接应实现对应 backend。

下一节：[Planner](planner.md)。
