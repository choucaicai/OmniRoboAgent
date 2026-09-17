# Quickstart

## 1. Install

```bash
git clone --recurse-submodules https://github.com/choucaicai/OmniRoboAgent.git
cd OmniRoboAgent
conda create -n omniagent python=3.11 -y
conda activate omniagent
uv pip install --python "$CONDA_PREFIX/bin/python" --editable . --group dev
```

基础环境只包含 framework 和开发依赖，不安装 simulator 或 benchmark SDK。需要运行具体 benchmark 时，按对应页面创建独立环境：

- [EB-ALFRED](eb_alfred.md)
- [LIBERO](libero.md)
- [RoboCasa365](robocasa365.md)

## 2. Choose An AgentConfig

AgentConfig 组合 Agent、Planner、Verifier、Memory 和 SkillBackend。模型由 Planner/Verifier 内部的 [Model Backend](components/model_backend.md) 选择，不是 OmniRoboAgent 的固定依赖。

使用 `OpenAICompatibleLLMBackend` 时，将 AgentConfig 中的值改为实际 endpoint 和 model ID：

```yaml
backend:
  class_path: omniroboagent.backends.llm.OpenAICompatibleLLMBackend
  init_args:
    base_url: <OPENAI_COMPATIBLE_BASE_URL>
    model: <MODEL_ID>
```

该 adapter 可以连接满足所需 OpenAI-compatible endpoints 和 model capabilities 的本地 server、hosted API 或 gateway。其他协议通过自定义 `LLMBackend` 接入。仓库 `configs/agents/*.yaml` 中的具体 endpoint/model 只代表对应 smoke 配置。

配置完成后检查所有 Agent components：

```bash
omniroboagent health --agent-config <AGENT_CONFIG>
```

healthcheck 不会启动或关闭外部 model/policy server。成功输出中顶层 `healthy` 以及 planner、verifier、memory、skill_backend 的 `healthy` 均为 `true`。

## 3. Run Fast Checks

```bash
python -m pytest
ruff check src tests
ruff format --check src tests
mypy
```

默认 tests 不启动外部模型、AI2-THOR、RoboCasa simulator、GR00T 或 OpenPI server。

## 4. Run A Config

通用入口：

```bash
omniroboagent run --config <RUN_CONFIG>
```

RunConfig 选择 AgentConfig、Pipeline、Runtime、Environment、task 或 benchmark evaluator。仓库内当前可运行入口位于 `configs/runs/`。

EB-ALFRED 提供包含 Xvfb 管理的脚本：

```bash
bash scripts/run_eb_alfred_xvfb.sh configs/runs/eb_alfred_smoke.yaml
```

RoboCasa 的 simulator/model 环境、assets 和 policy server 需要单独准备，不能在基础环境中直接运行。具体命令见 [RoboCasa365](robocasa365.md)。

LIBERO 同样使用独立 simulator/model 环境，并复用已有 ClawVLA/LeRobot 本地实现。具体依赖、环境变量和 smoke 配置见 [LIBERO](libero.md)。

## 5. Inspect Outputs

Runtime 为每个 session 写：

```text
<runtime.output_dir>/<session_id>/
├── result.json
├── trace.jsonl
├── agent_trace.jsonl          # observability enabled
├── episode.mp4                # video enabled and frames available
├── artifact_manifest.json     # observability enabled
└── artifacts/
```

Benchmark evaluator 通常另外写：

```text
<benchmark.output_dir>/
├── episodes.jsonl
├── summary.json
└── resolved_config.json    # evaluator 支持时
```

仓库的 EB-ALFRED 和 RoboCasa composite smoke RunConfig 已启用本地 Agent trace 与视频记录。视频要求系统可执行 `ffmpeg`；当前每个 Runtime step 记录一帧。输出覆盖范围见 [Runtime](components/runtime.md)、[Observability](components/observability.md) 和 [Evaluation](components/evaluation.md)。下一步阅读 [Configuration](configuration.md)。
