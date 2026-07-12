# Configuration

配置分为 Agent 和 Run 两层。

## AgentConfig

[`configs/agents/eb_alfred.yaml`](../configs/agents/eb_alfred.yaml) 只描述 Agent 组件，不包含 benchmark：

```yaml
agent:
  class_path: omniroboagent.agents.DefaultAgent

planner:
  class_path: omniroboagent.planners.LanguageSkillPlanner
  init_args:
    backend:
      class_path: omniroboagent.backends.llm.OpenAICompatibleLLMBackend
      init_args:
        base_url: http://127.0.0.1:8000
        model: Qwen3.5-9B
        timeout_seconds: 120
        max_retries: 2
    max_tokens: 1024
    temperature: 0
    extra_body:
      chat_template_kwargs:
        enable_thinking: false

skill_backend:
  class_path: omniroboagent.backends.skills.LanguageSkillBackend

verifier:
  class_path: omniroboagent.verifiers.EnvironmentVerifier

memory:
  class_path: omniroboagent.memory.InMemoryMemory
```

`DefaultAgent` 会把这四个组件组合起来。HTTP、WebSocket 等协议差异只出现在 backend，不创建协议专用 Agent 子类。

## RunConfig

[`configs/runs/eb_alfred_smoke.yaml`](../configs/runs/eb_alfred_smoke.yaml) 描述运行方式和环境：

```yaml
agent_config: ../agents/eb_alfred.yaml

pipeline:
  class_path: omniroboagent.pipelines.DirectPipeline
  init_args:
    action_execution_mode: full

runtime:
  class_path: omniroboagent.runtime.SyncRuntime
  init_args:
    max_steps: 30
    max_invalid_actions: 10
    max_retries: 10
    timeout_seconds: 1800
    output_dir: runs/eb_alfred_smoke/traces

environment:
  class_path: omniroboagent.integrations.embodiedbench.EBAlfredEnvironment
  init_args:
    eval_set: base
    selected_indexes: [0]
    resolution: 300
    exp_name: omniroboagent_smoke
    display: 1
    embodiedbench_root: benchmarks/EmbodiedBench

benchmark:
  class_path: omniroboagent.integrations.embodiedbench.EBAlfredBenchmark
  init_args:
    output_dir: runs/eb_alfred_smoke
```

`agent_config` 相对路径以 RunConfig 所在目录解析。其他相对路径以运行命令的当前目录解析，推荐始终从项目根目录运行。

存在 `benchmark` 时，CLI 将 Environment 注入 benchmark，并调用 `benchmark.run(agent, pipeline, runtime)`。没有 `benchmark` 时，RunConfig 必须直接包含 `task` 和 `environment`，CLI 调用一次 `runtime.run(...)`。

## `class_path`

组件格式为：

```yaml
class_path: package.module.ClassName
init_args:
  argument: value
```

`init_args` 中嵌套的 `class_path` 会先实例化，再传给外层组件。不存在的模块、类或不匹配的构造参数会抛出 `ConfigError`。

`build_agent()` 固定要求顶层存在 `agent`、`planner`、`verifier`、`memory` 和 `skill_backend`。RunConfig 固定要求 `pipeline` 和 `runtime`，`environment` 对 benchmark 和单任务运行都是必需的。

第一版不使用 registry、plugin manager 或依赖注入框架。

## Action Chunk

完整执行：

```yaml
pipeline:
  class_path: omniroboagent.pipelines.DirectPipeline
  init_args:
    action_execution_mode: full
```

Receding horizon：

```yaml
pipeline:
  class_path: omniroboagent.pipelines.DirectPipeline
  init_args:
    action_execution_mode: receding_horizon
    execute_steps: 4
```

Pipeline 将 `execute_steps` 传给 Environment。具体 Environment 负责解释 action chunk、shape、dtype、单位和实际执行方式。

`full` 模式传递 `execute_steps=None`。这表示是否完整执行 chunk 最终由 Environment adapter 实现；当前 EB-ALFRED action 是单个字符串，不使用该参数。

## OpenPI AgentConfig

使用 OpenPI 时替换 `skill_backend`，不要创建新的 Agent 子类：

```yaml
skill_backend:
  class_path: omniroboagent.backends.skills.OpenPIWebSocketPolicyBackend
  init_args:
    host: 127.0.0.1
    port: 8001
    timeout_seconds: 10
    action_key: actions
```

`host` 和 `port` 是当前构造参数；不存在 `url` 参数。OpenPI server 必须由用户提前启动。

## Output Reproducibility

当前 Runtime 会记录 trace、result 和模型原始响应，但不会把 resolved AgentConfig、RunConfig 或 package version 自动复制到输出目录。正式实验应保留本次使用的 YAML；自动写入这些元数据仍在 `docs/TODO.md` 中。

## Secrets

OpenAI-compatible backend 默认读取：

```bash
export OPENAI_API_KEY=...
```

本地 vLLM 不需要真实密钥时默认发送 `Bearer EMPTY`。密钥不应写入 YAML。
