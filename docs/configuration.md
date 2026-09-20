# Configuration

OmniRoboAgent 使用两层 YAML：

- `AgentConfig`：组合 Agent Core 和 model/policy backends，不绑定 benchmark。
- `RunConfig`：选择 AgentConfig、Pipeline、Runtime、Environment、task 或 benchmark evaluator。

## AgentConfig

AgentConfig 必须包含 `agent`、`planner`、`verifier`、`memory` 和 `skill_backend`：

```yaml
agent:
  class_path: omniroboagent.agent_core.DefaultAgent

planner:
  class_path: omniroboagent.agent_core.LanguageSkillPlanner
  init_args:
    backend:
      class_path: omniroboagent.backends.llm.OpenAICompatibleLLMBackend
      init_args:
        base_url: <OPENAI_COMPATIBLE_BASE_URL>
        model: <MODEL_ID>
        timeout_seconds: 120
        max_retries: 2
    max_tokens: 1024
    temperature: 0

verifier:
  class_path: omniroboagent.agent_core.EnvironmentVerifier

memory:
  class_path: omniroboagent.agent_core.InMemoryMemory

skill_backend:
  class_path: omniroboagent.backends.skills.LanguageSkillBackend
```

`<OPENAI_COMPATIBLE_BASE_URL>` 和 `<MODEL_ID>` 必须替换为用户选择的服务配置。这个例子展示当前内置 protocol adapter，不代表 framework 只能使用 OpenAI-compatible model；其他协议通过自定义 `LLMBackend` 的 nested `class_path` 接入。

各元素说明：

- [Agent](agent_core/agent.md)
- [Planner](agent_core/planner.md)
- [Verifier](agent_core/verifier.md)
- [Memory](agent_core/memory.md)
- [Model Backend](components/model_backend.md)
- [Skill Backend](components/skill_backend.md)

## RunConfig

```yaml
agent_config: ../agents/example.yaml

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
    output_dir: runs/example/traces

environment:
  class_path: your_package.YourEnvironment
  init_args: {}

task:
  instruction: example task
```

有 `benchmark` 时，CLI 将 Environment 注入 benchmark，并调用 `benchmark.run(agent, pipeline, runtime)`：

```yaml
benchmark:
  class_path: your_package.YourBenchmark
  init_args:
    output_dir: runs/example
```

没有 `benchmark` 时，RunConfig 必须直接提供 `task` 和 `environment`，CLI 只运行一个 episode。

## `class_path` And `init_args`

所有组件使用相同格式：

```yaml
class_path: package.module.ClassName
init_args:
  argument: value
```

`init_args` 中嵌套的 `class_path` 会先实例化，再传给外层组件。不存在的模块、类或不匹配的构造参数会抛出 `ConfigError`。

`agent_config` 相对路径以 RunConfig 文件所在目录解析。其他相对路径以运行命令的当前目录解析，建议始终从 repository root 运行。

## SkillBackend Registry

SkillBackend 除 `class_path` 外，还支持少量稳定内置名称：

```yaml
skill_backend:
  name: groot_remote
  init_args:
    host: <POLICY_HOST>
    port: <POLICY_PORT>
    timeout_seconds: 120
```

当前名称为 `groot_remote`、`openpi_remote` 和 `local`。`name` 与 `class_path` 只能选择一个。自定义 SkillBackend 直接使用 `class_path`，无需注册。

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

## Memory Artifacts

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
      - camera.front
      - camera.wrist
```

启用 key-event artifacts 后，Memory 将关键事件 frames 保存到 Runtime session 的 `artifacts/key_events/`。`camera_keys` 必须与 Environment observation 实际字段一致。

`frame_selection` 默认 `recent`，即最近 K 帧的滑动窗口。改成 `event` 后窗口容量不变，但只有 key event 和 verifier status 变化对应的 frame 独占槽位，chunk 执行期间的连续近似帧共用最后一个槽位。image token 开销不变。

把 `class_path` 换成 `omniroboagent.agent_core.ReflectiveMemory` 可以在上述参数之外额外积累失败 lessons，`lesson_recall_limit`、`lesson_min_support`、`lesson_limit`、`lesson_path` 和 `lesson_reload` 都有默认值，不填即可使用。两个 class 的其余参数完全一致，因此可以直接对照运行。字段含义见 [Memory](agent_core/memory.md)。

## Episode Observability

Agent trace 和视频属于 Runtime session artifacts，通过可选 recorder 配置：

```yaml
runtime:
  class_path: omniroboagent.runtimes.SyncRuntime
  init_args:
    output_dir: runs/example/traces
    observability:
      class_path: omniroboagent.observability.LocalEpisodeRecorder
      init_args:
        record_agent_trace: true
        record_video: true
        video_camera_keys:
          - camera.front
          - camera.wrist
        video_fps: 4
        ffmpeg_path: ffmpeg
```

`record_agent_trace` 和 `record_video` 可以独立关闭。启用视频时，camera keys 必须匹配 observation，系统还需要 FFmpeg。完整输出和错误语义见 [Observability](components/observability.md)。

## Checked-in Examples

`configs/agents/` 和 `configs/runs/` 是当前 benchmark smoke 的可运行示例，其中的 model ID、endpoint、port、GPU ID、task subset 和 limits 只在对应文件范围内有效：

- [EB-ALFRED](eb_alfred.md)
- [RoboCasa365](robocasa365.md)

复制这些配置用于其他环境时，应逐项检查 external services、model capability、dataset/assets、hardware、task scope 和 output path。

## Secrets

`OpenAICompatibleLLMBackend` 默认读取 `OPENAI_API_KEY`。其他 backend 可以定义自己的环境变量：

```bash
export OPENAI_API_KEY=...
```

密钥不应写入 YAML、trace 或 benchmark output。

下一节：[Agent Core](agent_core/README.md)。
