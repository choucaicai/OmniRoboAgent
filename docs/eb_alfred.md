# EB-ALFRED Evaluation

## Fixed Versions

以下是当前 verified smoke combination，不是 OmniRoboAgent 对 model provider、endpoint 或 hardware 的项目级默认：

- EmbodiedBench: `9be4e980e9cd6bcb38373cd4aab7c32724bdd401`
- EB-ALFRED dataset: `af55cc721725ed058830fd7a8aee66c1f69efbaa`
- Python: `3.11`
- Conda environment: `omniagent-eb`
- Model: `Qwen3.5-9B`
- Endpoint: `http://127.0.0.1:8000`

## Environment Installation

从项目根目录执行：

```bash
conda create -n omniagent-eb --clone omniagent -y
conda activate omniagent-eb
uv pip install --python "$CONDA_PREFIX/bin/python" --editable '.[eb-alfred]'
```

仅在实际运行 EB-ALFRED 时创建 `omniagent-eb`。不要把 `eb-alfred` extra 安装到基础 `omniagent`。新建的 `omniagent-eb` 从 `omniagent` clone，因此包含 `uv`；已有环境若缺少 `uv`，先执行 `conda install -n omniagent-eb -c conda-forge uv`。

下载数据：

```bash
git clone https://huggingface.co/datasets/EmbodiedBench/EB-ALFRED \
  benchmarks/EmbodiedBench/embodiedbench/envs/eb_alfred/data/json_2.1.0
```

EmbodiedBench 当前 `setup.py` 使用 `find_packages()`，但顶层 `embodiedbench/` 没有 `__init__.py`。OmniRoboAgent adapter 通过 `embodiedbench_root` 把仓库根加入 `sys.path`，不修改第三方源码。

`ai2thor==2.1.0` 必须使用上面固定的 Flask/Werkzeug/urllib3 版本。新版 Flask server 可以启动 Unity，但会在 `Initialize` 响应处持续等待。

## Xvfb Display

确认系统提供 Xvfb 和 display 检查工具：

```bash
command -v Xvfb
command -v xdpyinfo
```

直接使用项目脚本启动 Xvfb、设置 `DISPLAY=:1` 并运行 smoke：

```bash
bash scripts/run_eb_alfred_xvfb.sh
```

等价的手动命令：

```bash
Xvfb :1 -screen 0 1024x768x24 \
  -ac +extension GLX +render -noreset -nolisten tcp &

export DISPLAY=:1
export LIBGL_ALWAYS_SOFTWARE=1

conda run --no-capture-output -n omniagent-eb \
  omniroboagent run --config configs/runs/eb_alfred_smoke.yaml
```

Xvfb 使用 Mesa llvmpipe 软件渲染。当前 `base[0]` 实测完成 14 个环境 step，总耗时约 39 秒。

RunConfig 中的 `display: 1` 用于设置 EB-ALFRED module 的 X display，运行进程仍需要对应的 `DISPLAY=:1` 环境变量。项目脚本会同时处理两者的默认配置。

## Model Service

先启动 AgentConfig 对应的 model service。当前 `OpenAICompatibleLLMBackend` 不绑定具体 serving stack；服务需要满足配置所需的 OpenAI-compatible endpoints、multimodal input 和 structured output 能力。仓库 [`SERVER.md`](https://github.com/choucaicai/OmniRoboAgent/blob/master/SERVER.md) 是当前 verified vLLM example，不是 EB-ALFRED 或 OmniRoboAgent 的固定依赖。检查：

```bash
omniroboagent health --agent-config configs/agents/eb_alfred.yaml
```

## Smoke Evaluation

```bash
conda activate omniagent-eb
omniroboagent run --config configs/runs/eb_alfred_smoke.yaml
```

如果当前 shell 没有提前设置 `DISPLAY`，使用上一节的 `run_eb_alfred_xvfb.sh`。

当前 smoke 配置选择 `base[0]`。要增加 episode：

```yaml
environment:
  init_args:
    eval_set: base
    selected_indexes: [0, 1, 2, 3, 4]
```

设置 `selected_indexes: []` 会运行该 eval set 的全部 50 个 episode。

## Closed-Loop Difference

EmbodiedBench baseline 允许一次模型调用返回 action list 并连续执行。OmniRoboAgent 第一版只取本轮一个 skill：

```text
observe
 -> planner selects one language skill
 -> LanguageSkillBackend passes it through
 -> EBAlfEnv.step(skill)
 -> EnvironmentVerifier reads ground truth
 -> re-observe and replan
```

这确保动作失败后不会继续执行旧计划。

## Metrics

`summary.json` 包含：

- `success_rate`
- `mean_progress`
- `mean_steps`
- `invalid_actions`
- `replans`
- `latency_seconds`
- `termination_reasons`

每个 episode 还保存完整 `trace.jsonl` 和 `result.json`，可与 EmbodiedBench 原生 evaluator 的 `task_success`、`task_progress`、`num_steps` 和 invalid-action 指标对齐。

当前只验证了 OmniRoboAgent adapter 的输出，尚未在相同 episode 上完成 EmbodiedBench 原生 evaluator 数值对齐。`replans` 是框架统计的 invalid-action replan 次数，不是 EmbodiedBench 原生字段。

## Verified Smoke Result

2026-07-12 在 `Xvfb :1`、Mesa llvmpipe、`Qwen3.5-9B` 上运行 `base[0]`：

```text
episodes: 1
success_rate: 0.0
mean_progress: 0.3333333333333333
mean_steps: 14
invalid_actions: 10
replans: 10
latency_seconds: 38.64
termination_reason: environment_done
```

前四个真实动作 `find a Ladle`、`pick up the Ladle`、`find a Faucet`、`turn on the Faucet` 均成功。随后模型重复选择 `pick up the Ladle`，触发环境 invalid-action limit。该结果证明评估闭环已经运行完成，但不代表当前 Planner 策略成功完成任务。

## Troubleshooting

### Unity waits during `Initialize`

先检查依赖版本：

```bash
conda run -n omniagent-eb python -c \
  "import importlib.metadata as m; print(m.version('Flask')); print(m.version('Werkzeug')); print(m.version('ai2thor'))"
```

已验证组合为 Flask `1.1.2`、Werkzeug `1.0.1`、ai2thor `2.1.0`。新版 Flask/Werkzeug 可能让 Unity 启动后持续等待 Initialize 响应。

### Display is unavailable

```bash
DISPLAY=:1 xdpyinfo >/dev/null && echo ready
```

失败时使用 `scripts/run_eb_alfred_xvfb.sh`，或确认 `DISPLAY_ID` 与 RunConfig 的 `display` 一致。

### Planner content is empty

Qwen thinking 模型可能把输出预算用于 reasoning。确认 AgentConfig 包含：

```yaml
extra_body:
  chat_template_kwargs:
    enable_thinking: false
```

仍失败时检查 `max_tokens`、model service 的 structured output 支持和 episode trace 中保存的原始 response。
