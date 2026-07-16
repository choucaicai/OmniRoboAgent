# Configuration

配置分为 Agent 和 Run 两层。

## AgentConfig

[`configs/agents/eb_alfred.yaml`](https://github.com/choucaicai/OmniRoboAgent/blob/master/configs/agents/eb_alfred.yaml) 只描述 Agent 组件，不包含 benchmark：

```yaml
agent:
  class_path: omniroboagent.agent_core.DefaultAgent

planner:
  class_path: omniroboagent.agent_core.LanguageSkillPlanner
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
  class_path: omniroboagent.agent_core.EnvironmentVerifier

memory:
  class_path: omniroboagent.agent_core.InMemoryMemory
```

`DefaultAgent` 会把这四个组件组合起来。HTTP、WebSocket 等协议差异只出现在 backend，不创建协议专用 Agent 子类。

RoboCasa composite Agent 使用 bounded TieredMemory：

```yaml
memory:
  class_path: omniroboagent.agent_core.TieredMemory
  init_args:
    visual_window_size: 4
    recent_event_limit: 20
    key_event_limit: 20
    summary_max_chars: 4096
    save_key_event_artifacts: true
    camera_keys:
      - video.robot0_agentview_left
      - video.robot0_agentview_right
      - video.robot0_eye_in_hand
```

`recent_event_limit` 限制当前 session 的普通 transition，`key_event_limit` 限制 recall 返回的长期关键事件数量。每个 Runtime session 会清空 working frames、recent events 和当前 summary，但保留 key events。

`save_key_event_artifacts` 默认 `false`。启用后，subtask complete/fail、recovery、fallback、abort 和 task terminal 会在 Runtime session 目录下写 `artifacts/key_events/events.jsonl` 与当前 camera PNG。普通 `in_progress` transition 不写图片。`event_path` 仍是可选的全 transition append-only JSONL。

`DirectPipeline` 和 `SkillExecutionPipeline` 会在 plan/verify 阶段显式生成 `memory_context`。当前 RoboCasa composite Planner/Verifier 会消费最近 4 个 timestep 的三路 camera frames、最近 20 条 transitions、最近 20 条 key events 和 bounded summary。历史关键帧默认不重新注入 prompt，只传递 artifact references。

SkillBackend 支持 registry 稳定名称：

```yaml
skill_backend:
  name: groot_remote
  init_args:
    host: localhost
    port: 5555
    timeout_seconds: 120
```

内置名称为 `groot_remote`（GR00T ZeroMQ）、`openpi_remote`（OpenPI WebSocket + RoboCasa schema）和 `local`（in-process policy）。`name` 与 `class_path` 只能选择一个；未知名称会列出可用 backend。自定义 backend 继续使用 `class_path`，无需注册。

## RunConfig

[`configs/runs/eb_alfred_smoke.yaml`](https://github.com/choucaicai/OmniRoboAgent/blob/master/configs/runs/eb_alfred_smoke.yaml) 描述运行方式和环境：

```yaml
agent_config: ../agents/eb_alfred.yaml

pipeline:
  class_path: omniroboagent.pipelines.DirectPipeline
  init_args:
    action_execution_mode: full

runtime:
  class_path: omniroboagent.runtimes.SyncRuntime
  init_args:
    max_steps: 30
    max_invalid_actions: 10
    max_retries: 10
    timeout_seconds: 1800
    output_dir: runs/eb_alfred_smoke/traces

environment:
  class_path: omniroboagent.environments.benchmarks.embodiedbench.EBAlfredEnvironment
  init_args:
    eval_set: base
    selected_indexes: [0]
    resolution: 300
    exp_name: omniroboagent_smoke
    display: 1
    embodiedbench_root: benchmarks/EmbodiedBench

benchmark:
  class_path: omniroboagent.evals.benchmarks.embodiedbench.EBAlfredBenchmark
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

只有 SkillBackend 提供最小显式 registry。框架不做 entry-point scan、自动 plugin discovery、plugin manager 或依赖注入。

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

RoboCasa OpenPI 使用 registry，不创建新的 Agent 子类：

```yaml
skill_backend:
  name: openpi_remote
  init_args:
    host: 127.0.0.1
    port: 8000
    timeout_seconds: 120
```

其他 benchmark 若只需要原始 OpenPI observation/action passthrough，可以直接配置通用 client：

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

## RoboCasa365 RunConfig

五个可运行入口：

```text
configs/runs/robocasa365_groot_remote_smoke.yaml
configs/runs/robocasa365_openpi_remote_smoke.yaml
configs/runs/robocasa365_groot_local_smoke.yaml
configs/runs/robocasa365_groot_composite_remote_smoke.yaml
configs/runs/robocasa365_groot_composite_local_smoke.yaml
```

它们复用同一个 `RoboCasa365Evaluator` 和 `RoboCasaEnvironment`，只替换 AgentConfig。Atomic GR00T 使用 `TaskSkillPlanner`；composite GR00T 使用 `SubtaskSkillPlanner` 和 RunConfig 提供的 11-skill macro catalog。`task_set` 选择官方 task 集合，`split` 独立选择 `pretrain` 或 `target`；`max_tasks`、`episodes_per_task`、`episode_indices` 和 `seed` 控制可复现 smoke。完整字段和命令见 [RoboCasa365 评测](robocasa365.md)。

连续 VLA 使用 `SkillExecutionPipeline`。Planner 只在没有 active execution 或 recovery 要求 replan 时调用；`in_progress` 不再周期调用 Planner。`max_chunks_per_skill` 是 execution hard budget，`max_attempts_per_execution` 控制失败重试，`max_uncertain_verifications` 控制 reverify，`max_no_progress_steps`、`max_replans` 和 `fallback_proposal` 为可选 recovery 限制。`planner_check_interval_chunks` 只为旧配置兼容保留。

RoboCasa atomic 配置使用无 VLM backend 的 `SubtaskVerifier`，依赖 benchmark task success 和 action feedback；composite 配置为 `SubtaskVerifier` 配置同一个 OpenAI-compatible model，并通过 `check_interval_chunks: 8` 每 8 个 action chunks 执行视觉 completion 检查。OpenPI smoke 使用 `receding_horizon + execute_steps=5`，GR00T smoke 执行完整 16-step chunk。

## Output Reproducibility

Runtime 会记录 trace、result 和模型原始响应。`RoboCasa365Evaluator` 额外写入 `resolved_config.json`，包含 task/split/seed、component class、部分 Pipeline/Runtime 限制、repository commit、Python/package version 和 policy health metadata；它不是完整 AgentConfig/RunConfig，也不是原始 YAML 的逐字副本。当前仓库只跟踪 smoke RunConfig，正式 split matrix 还需要提交独立 experiment manifest/RunConfig。EB-ALFRED 当前仍不会自动复制完整 AgentConfig/RunConfig，正式实验必须保留所用 YAML。

## Secrets

OpenAI-compatible backend 默认读取：

```bash
export OPENAI_API_KEY=...
```

本地 vLLM 不需要真实密钥时默认发送 `Bearer EMPTY`。密钥不应写入 YAML。
