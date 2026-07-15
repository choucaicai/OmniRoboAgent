# Custom Components

自定义组件继承对应 contract，然后通过 `class_path` 加载。

自定义类必须位于当前 Python 环境可 import 的 module 中，构造参数放在 `init_args`。配置 loader 不做自动 plugin discovery；SkillBackend 额外支持显式 registry 注册。

## Custom Planner

```python
from typing import Any

from omniroboagent.agent_core import Planner


class MyPlanner(Planner):
    def plan(self, inputs: dict[str, Any]) -> Any:
        return {"skill": "find a Mug"}
```

```yaml
planner:
  class_path: my_package.planner.MyPlanner
```

## Custom Verifier

```python
from typing import Any

from omniroboagent.agent_core import Verifier


class MyVerifier(Verifier):
    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        result = inputs["environment_result"]
        return {
            "finished": result.get("score", 0) >= 1,
            "action_valid": result.get("valid", False),
        }
```

自定义 Pipeline 负责解释 `finished` 和 `action_valid`。Runtime 不读取这些字段。

## Custom SkillBackend

```python
from typing import Any

from omniroboagent.backends.skills import SkillBackend


class MyPolicyBackend(SkillBackend):
    def predict(self, inputs: dict[str, Any]) -> Any:
        observation = inputs["observation"]
        return local_policy(observation)
```

SkillBackend 只生成 action，不调用 Environment。

CLI 配置自定义 backend 时直接使用 `class_path`。在嵌入式 Python 进程中，也可以先显式注册稳定名称：

```python
from omniroboagent.backends.skills import register_skill_backend

register_skill_backend("my_policy", MyPolicyBackend)
```

注册后可使用 `skill_backend: {name: my_policy}`。CLI 不会自动 import 注册 module，因此 stock CLI 的外部 backend 仍应使用 `class_path`。

## Custom Environment

```python
from typing import Any

from omniroboagent.environments import Environment


class MyEnvironment(Environment):
    def reset(self, task: Any) -> Any:
        return simulator.reset(task)

    def execute(
        self, action: Any, execute_steps: int | None = None
    ) -> dict[str, Any]:
        if not supports(action):
            raise ValueError("Unsupported action payload")
        return simulator.execute(action, execute_steps=execute_steps)

    def close(self) -> None:
        simulator.close()
```

Environment 必须把 Pipeline 需要的执行反馈整理成普通字典，并为所有失败提供明确异常或状态字段。

## Custom Pipeline

自定义 Pipeline 可以使用任何 Verifier 输出语义：

```python
from typing import Any

from omniroboagent.agent_core import BaseAgent
from omniroboagent.environments import Environment
from omniroboagent.pipelines import Pipeline


class MyPipeline(Pipeline):
    def step(
        self,
        agent: BaseAgent,
        environment: Environment,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        return {"finished": True}

    def is_terminal(
        self,
        output: dict[str, Any],
        state: dict[str, Any],
    ) -> bool:
        return bool(output["finished"])
```

Runtime 不要求 `decision` 字段。

## Custom Agent

多数场景只需继续使用 `DefaultAgent` 并替换组件。只有 Agent 本身的委托方式需要改变时才继承 `BaseAgent`；HTTP、WebSocket 或本地推理差异应实现为 backend，不能据此创建协议专用 Agent。

自定义 Agent 必须调用 `BaseAgent` constructor，并只实现三个决策方法：

```python
from typing import Any

from omniroboagent.agent_core import BaseAgent


class MyAgent(BaseAgent):
    def plan(self, inputs: dict[str, Any]) -> Any:
        return self.planner.plan(inputs)

    def predict_action(self, inputs: dict[str, Any]) -> Any:
        return self.skill_backend.predict(inputs)

    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.verifier.verify(inputs)
```

`update()`、healthcheck 和幂等 close 由 `BaseAgent` 提供。Agent 不应持有或执行 Pipeline、Runtime、Environment。

## Resource Rules

- Planner 负责关闭自己的 LLM backend。
- SkillBackend 负责关闭 policy client。
- Memory 负责关闭自己的持久化资源。
- Environment 负责关闭 simulator 或 robot connection。
- Runtime 在单任务运行结束时关闭 Agent 和 Environment；benchmark 多 episode 运行通过 `close_resources=False` 复用资源，并在全部 episode 后统一关闭。
