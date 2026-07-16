# Planner

Planner 根据 task、当前 observation、执行历史和显式 memory context 提出下一步计划。它只负责 proposal，不负责执行 action，也不能替代 Verifier 宣告任务完成。

## Contract

```python
class Planner:
    def plan(self, inputs: dict[str, Any]) -> Any: ...
    def healthcheck(self) -> dict[str, Any]: ...
    def close(self) -> None: ...
```

输入和输出保持开放，具体字段由当前 Pipeline 与 Planner 协商。当前 Pipeline 通常提供：

```text
task
observation
step
history
available_skills
memory_context
```

## Current Implementations

| Planner | Use case | Output |
| --- | --- | --- |
| `LanguageSkillPlanner` | 从 Environment 提供的 language skills 中选择一个 skill | `skill`、`reasoning` 和模型原始响应 |
| `TaskSkillPlanner` | atomic VLA task，不调用 LLM | 将 concrete task name 作为 `skill` 和 `subtask` |
| `SubtaskSkillPlanner` | long-horizon composite task | `skill`、可信本地映射的 `skill_id`、`subtask`、`grounded_arguments`、`expected_outcome` |

`SubtaskSkillPlanner` 只接受配置中的 skill catalog 和 trusted `skill_ids`。模型不能直接提供或覆盖 `skill_id`。

## Model-backed Planner

`LanguageSkillPlanner` 和 `SubtaskSkillPlanner` 依赖 [Model Backend](../components/model_backend.md)，而不是依赖某个固定 model provider。Planner 负责 prompt、schema 和输出校验；backend 负责请求协议、timeout、retry 和 provider response。

```yaml
planner:
  class_path: omniroboagent.agent_core.LanguageSkillPlanner
  init_args:
    backend:
      class_path: omniroboagent.backends.llm.OpenAICompatibleLLMBackend
      init_args:
        base_url: <OPENAI_COMPATIBLE_BASE_URL>
        model: <MODEL_ID>
```

这里的 adapter 和参数是示例。其他协议可通过自定义 `LLMBackend` 接入，不需要修改 Planner。

## Failure Boundary

Planner 必须对缺失 input、不可用 skill 和无效 model output 显式报错。`DirectPipeline` 会把 `PlannerOutputError` 转为一次失败 verification；未分类异常由 Runtime 记录为 `termination_reason=exception`。

下一节：[Verifier](verifier.md)。
