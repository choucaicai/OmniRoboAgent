# Skill Backend

SkillBackend 将 Agent/Pipeline 构造的输入转换为 Environment 可执行的 action payload。它可以封装规则、远程 policy、本地 policy 或任意 action generator，但不执行 environment action，也不负责全局任务规划。

## Contract

```python
class SkillBackend:
    def predict(self, inputs: dict[str, Any]) -> Any: ...
    def healthcheck(self) -> dict[str, Any]: ...
    def close(self) -> None: ...
```

返回值保持开放，可以是字符串、字典、NumPy array、tensor、action chunk 或自定义对象。Environment 必须在 `execute()` 使用点校验 payload。

## Current Implementations

| Backend | Purpose |
| --- | --- |
| `LanguageSkillBackend` | 原样返回 `inputs["skill"]`，用于 language-action environment |
| `LocalPolicyBackend` | 包装已实例化的 in-process policy，支持 `predict`、`infer`、`get_action` 或 callable |
| `GR00TRemotePolicyBackend` | RoboCasa GR00T ZeroMQ remote protocol |
| `GR00TLocalPolicyAdapter` | lazy-load GR00T in-process policy |
| `OpenPIWebSocketPolicyBackend` | 通用 OpenPI WebSocket passthrough client |
| `OpenPIRoboCasaPolicyBackend` | RoboCasa observation/action schema adapter |

GR00T 和 OpenPI 是当前 benchmark integrations，不限制 SkillBackend contract。其他 policy 通过自定义 backend 接入。

## Selection

内置 registry 名称为：

```text
groot_remote
openpi_remote
local
```

```yaml
skill_backend:
  name: local
  init_args:
    policy:
      class_path: your_package.YourPolicy
```

`name` 只用于少量稳定内置项。自定义实现直接使用 `class_path`，不需要注册：

```yaml
skill_backend:
  class_path: your_package.YourSkillBackend
  init_args:
    option: value
```

`name` 和 `class_path` 不能同时设置。框架不扫描 Python entry points，也没有 plugin manager。

下一节：[Pipeline](pipeline.md)。
