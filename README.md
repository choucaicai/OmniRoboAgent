# OmniRoboAgent

OmniRoboAgent 是面向具身 Agent 的模块化构建、运行与评估框架。

```text
Observe -> Plan -> Act -> Verify -> Update or Stop
```

当前实现包含同步 Runtime、组合式 BaseAgent、显式 skill-execution graph state、独立 SubtaskVerifier、K 帧 TieredMemory、OpenAI-compatible LLM、SkillBackend registry、EB-ALFRED，以及 RoboCasa365 的 atomic/composite Agent、GR00T/OpenPI/local VLA evaluation 路径。

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

拉取主仓库更新后，使用同一命令让 submodule 回到主仓库记录的 commit。不要直接在 `benchmarks/EmbodiedBench` 或 `benchmarks/RoboCasa` 中提交本项目代码。

## Install

项目要求 Python 3.11，使用 `uv + pyproject.toml + uv.lock` 管理依赖。基础开发只使用 `omniagent`，不要安装 benchmark 专用依赖：

```bash
# 已有 omniagent 时跳过 create
conda create -n omniagent python=3.11 -y
conda activate omniagent

# 已安装时只需确认路径
which uv

# 安装 OmniRoboAgent 和 dev dependency group 到当前 Conda 环境
uv pip install --python "$CONDA_PREFIX/bin/python" --editable . --group dev
```

当前机器已安装的 `uv` 路径是 `/home/zzz/anaconda3/envs/omniagent/bin/uv`。若新环境中没有 `uv`，可先执行 `conda install -c conda-forge uv`。

可选的 OpenPI client 也安装到 `omniagent`：

```bash
conda activate omniagent
uv pip install --python "$CONDA_PREFIX/bin/python" --editable '.[openpi]'
```

GR00T remote client 使用 ZeroMQ：

```bash
uv pip install --python "$CONDA_PREFIX/bin/python" --editable '.[groot-client]'
```

`uv.lock` 需要提交。修改依赖后更新并检查 lockfile：

```bash
uv lock
uv lock --check
```

运行基础检查：

```bash
conda activate omniagent
python -m pytest
ruff check src tests
ruff format --check src tests
mypy
```

## Install EB-ALFRED

只有实际测试 EB-ALFRED 时才创建 `omniagent-eb`。它与基础 `omniagent` 分开，避免旧版 simulator 依赖影响开发环境：

```bash
conda create -n omniagent-eb --clone omniagent -y
conda activate omniagent-eb
uv pip install --python "$CONDA_PREFIX/bin/python" --editable '.[eb-alfred]'
```

`eb-alfred` extra 固定 AI2-THOR、PyTorch CPU、Flask 等已验证版本，并通过 uv source 安装本地 `benchmarks/EmbodiedBench` submodule。其他 benchmark 需要测试时也应单独创建环境，不写入 `omniagent`。

下载 EB-ALFRED dataset：

```bash
git clone https://huggingface.co/datasets/EmbodiedBench/EB-ALFRED \
  benchmarks/EmbodiedBench/embodiedbench/envs/eb_alfred/data/json_2.1.0
```

系统还需要 `Xvfb` 和 `xdpyinfo`。详细版本与故障排查见 [EB-ALFRED 评测](docs/eb_alfred.md)。

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

RoboCasa365 使用独立 simulator/model 环境。官方 assets 安装、atomic/composite Agent、GR00T/OpenPI server、本地模型和 smoke 配置见 [RoboCasa365 评测](docs/robocasa365.md)。

## Documentation

### Guides

- [在线文档](https://choucaicai.github.io/OmniRoboAgent/)
- [快速开始](docs/quickstart.md)
- [配置说明](docs/configuration.md)
- [接口文档](docs/interfaces.md)
- [自定义组件](docs/custom_components.md)
- [整体架构](impl_docs/architecture/overview.md)

### Benchmarks

- [EB-ALFRED 评测](docs/eb_alfred.md)
- [RoboCasa365 评测](docs/robocasa365.md)
