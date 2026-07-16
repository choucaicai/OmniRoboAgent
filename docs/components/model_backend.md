# Model Backend

Model Backend 隔离 Planner 或 Verifier 与具体模型 provider、serving stack 和请求协议。Agent Core 只依赖 `LLMBackend` contract。

## Contract

```python
class LLMBackend:
    def complete(self, inputs: dict[str, Any]) -> dict[str, Any]: ...
    def healthcheck(self) -> dict[str, Any]: ...
    def close(self) -> None: ...
```

Planner 负责 prompt、structured output schema 和业务校验。Backend 负责序列化请求、鉴权、timeout、retry、provider response 和连接释放。

## Built-in Adapter

当前内置 `OpenAICompatibleLLMBackend`。它是 provider-neutral protocol adapter，不绑定任何单一服务：

- `base_url` 自动规范到 `/v1`。
- `healthcheck()` 请求 `/v1/models` 并检查配置的 model ID。
- `complete()` 请求 `/v1/chat/completions`。
- `api_key` 未显式传入时读取 `OPENAI_API_KEY`，仍为空时使用 `EMPTY`。
- 支持 text、HTTP/data URL、本地 image path、bytes、PIL image 和 NumPy image。
- 返回 provider 原始 JSON，并增加 `_backend` latency 和 attempts。

任何本地 server、hosted API 或 gateway 只有在这些 endpoints、payload 和所需 multimodal/structured-output capability 匹配时才能使用该 adapter。协议兼容不等于本项目已经验证其行为。

```yaml
backend:
  class_path: omniroboagent.backends.llm.OpenAICompatibleLLMBackend
  init_args:
    base_url: <OPENAI_COMPATIBLE_BASE_URL>
    model: <MODEL_ID>
    timeout_seconds: 120
    max_retries: 2
```

`<OPENAI_COMPATIBLE_BASE_URL>` 和 `<MODEL_ID>` 是用户配置值，不是项目默认。仓库 `configs/agents/` 中的具体值是对应 smoke 的 verified example。

## Other Protocols

当 provider 不符合当前 OpenAI-compatible contract 时，实现自定义 `LLMBackend`，并在 Planner 或 Verifier 的 nested `class_path` 中选择它。无需创建 provider-specific Agent 或修改 Pipeline。

```yaml
planner:
  class_path: omniroboagent.agent_core.LanguageSkillPlanner
  init_args:
    backend:
      class_path: your_package.YourLLMBackend
      init_args:
        provider_specific_option: value
```

实现方法见 [Custom Components](../custom_components.md#custom-llmbackend)。
