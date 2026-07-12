# OmniRoboAgent

OmniRoboAgent 是面向具身 Agent 的模块化构建、运行与评估框架。

```text
Observe -> Plan -> Act -> Verify -> Update or Stop
```

当前实现包含同步 Runtime、可替换 Agent 组件、OpenAI-compatible LLM、OpenPI WebSocket policy 和 EB-ALFRED integration。

## Clone

`benchmarks/` 下的第三方项目使用 Git submodule 管理。主仓库只保存 submodule 的 URL 和固定 commit，不会把第三方源码重复上传到主仓库。

首次 clone 时同时拉取 submodule：

```bash
git clone --recurse-submodules <OmniRoboAgent-repo-url>
cd OmniRoboAgent
```

如果已经 clone 了主仓库，再初始化 submodule：

```bash
git submodule update --init --recursive
```

拉取主仓库更新后，使用同一命令让 submodule 回到主仓库记录的 commit。不要直接在 `benchmarks/EmbodiedBench` 中提交本项目代码。

## Install

项目要求 Python 3.11。基础开发环境：

```bash
conda create -n omniagent python=3.11 -y
conda activate omniagent
python -m pip install -e '.[dev]'
```

可选的 OpenPI client：

```bash
python -m pip install -e '.[openpi]'
```

运行基础检查：

```bash
python -m pytest
ruff check src tests
ruff format --check src tests
mypy
```

## Install EB-ALFRED

EB-ALFRED 使用独立环境，避免旧版 simulator 依赖影响基础开发环境：

```bash
conda create -n omniagent-eb --clone omniagent -y

conda run -n omniagent-eb python -m pip install \
  torch==2.4.0 torchvision==0.19.0 \
  --index-url https://download.pytorch.org/whl/cpu

conda run -n omniagent-eb python -m pip install \
  numpy==1.26.4 scipy==1.13.1 gym==0.23.1 ai2thor==2.1.0 \
  hydra-core==1.3.2 omegaconf==2.3.0 revtok==0.0.3 \
  progressbar2==4.5.0 vocab==0.0.5 tqdm==4.67.1 \
  opencv-python-headless==4.10.0.84

conda run -n omniagent-eb python -m pip install \
  flask==1.1.2 werkzeug==1.0.1 itsdangerous==1.1.0 \
  jinja2==2.11.3 markupsafe==1.1.1 click==8.1.7 \
  requests==2.32.3 urllib3==1.26.20

conda run -n omniagent-eb python -m pip install \
  -e benchmarks/EmbodiedBench -e .
```

下载 EB-ALFRED dataset：

```bash
git clone https://huggingface.co/datasets/EmbodiedBench/EB-ALFRED \
  benchmarks/EmbodiedBench/embodiedbench/envs/eb_alfred/data/json_2.1.0
```

系统还需要 `Xvfb` 和 `xdpyinfo`。详细版本与故障排查见 [EB-ALFRED 评测](tutorial_docs/eb_alfred.md)。

## Start

先启动配置对应的 OpenAI-compatible vLLM server。默认 endpoint 是 `http://127.0.0.1:8000`，模型名是 `Qwen3.5-9B`；示例命令见 [SERVER.md](SERVER.md)。服务启动后检查：

```bash
conda activate omniagent-eb
omniroboagent health --agent-config configs/agents/eb_alfred.yaml
```

运行固定 `base[0]` episode 的 EB-ALFRED smoke evaluation：

```bash
bash scripts/run_eb_alfred_xvfb.sh
```

脚本默认使用 Conda 环境 `omniagent-eb` 和 `DISPLAY=:1`，必要时自动启动 Xvfb。输出写入 `runs/eb_alfred_smoke/`。指定其他配置或 display：

```bash
DISPLAY_ID=2 CONDA_ENV=omniagent-eb \
  bash scripts/run_eb_alfred_xvfb.sh configs/runs/eb_alfred_smoke.yaml
```

## Documentation

- [快速开始](tutorial_docs/quickstart.md)
- [配置说明](tutorial_docs/configuration.md)
- [接口文档](tutorial_docs/interfaces.md)
- [EB-ALFRED 评测](tutorial_docs/eb_alfred.md)
- [自定义组件](tutorial_docs/custom_components.md)
- [整体架构](docs/architecture/overview.md)
