# OmniRoboAgent

OmniRoboAgent 是面向具身 Agent 的模块化构建、运行与评估框架。

```text
Observe -> Plan -> Act -> Verify -> Update or Stop
```

当前实现包含同步 Runtime、独立 episode observability artifacts、组合式 BaseAgent、显式 skill-execution graph state、独立 SubtaskVerifier、K 帧与关键事件 TieredMemory、OpenAI-compatible LLM、SkillBackend registry、EB-ALFRED，以及 RoboCasa365 的 atomic/composite Agent、GR00T/OpenPI/local VLA evaluation 路径。

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

若环境中没有 `uv`，可先执行 `conda install -c conda-forge uv`，或按 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/) 安装。

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

## SpatialMemory：为智能体提供空间上下文

`SpatialMemory` 是 OmniRoboAgent 的空间记忆组件。它把场景点云转换为结构化的
`walls`、`doors`、`windows` 和 `objects`，并通过
`memory_context["spatial"]` 提供给 Planner。智能体因此可以在选择下一步动作时参考
房间边界、通道、门窗和物体的空间位置，而不只依赖当前相机图像和历史文本。

```text
全局场景 PLY / 实时 RGB-D + 相机位姿
                    ↓
              SpatialMemory
                    ↓
       memory_context["spatial"]
                    ↓
          LanguageSkillPlanner
```

空间地图有两种互斥的来源：

- **全局场景 PLY**：输入米制、右手系、Z-up 的完整场景点云。SpatialLM 在
  `SpatialMemory` 初始化时定位一次，结果跨 session reset 缓存，适合已有 SLAM 地图
  或离线重建场景。
- **SLAM 实时构图**：上游持续提供对齐的 RGB-D、相机内参和米制绝对相机位姿；
  `SpatialMemory` 增量融合 voxel point map，并在关键帧更新后刷新空间布局。

`SpatialMemory` 保存和提供空间事实，不自行完成 SLAM 位姿估计、任务规划、导航或
动作执行。需要同时使用事件、摘要和视觉工作记忆时，可通过 `CompositeMemory` 将它
与 `InMemoryMemory` 或 `TieredMemory` 组合。

完整的两种模式、输入字段、坐标系、`recall()` 输出和 YAML 配置见
[SpatialMemory 空间记忆组件](docs/components/spatialmemory_memory.md)。在线 voxel 建图
本身不要求加载模型；如果需要通过 SpatialLM 从全局 PLY 或在线点云生成结构化空间
布局，则在独立 `omni-spatial` 环境中安装 backend，具体见
[SpatialMemory Backend 环境安装](docs/components/spatialmemory_backend.md)。SpatialLM
当前使用 Python 3.11、CUDA 12.4 和 PyTorch 2.4.1+cu124，模型权重不随 Git 仓库
分发。

可查看 [SpatialLM 空间定位 Demo](SpatialLM/examples/spatiallm_demo/README.md)。
该示例展示从场景 PLY 读取点云、运行 SpatialLM 空间定位、生成结构化墙体/门窗/物体
结果展示。

## Start

先准备 AgentConfig 所需的 model backend。当前内置 `OpenAICompatibleLLMBackend` 可以连接满足相应 endpoints 和 model capabilities 的本地 server、hosted API 或 gateway；其他协议可以实现自定义 `LLMBackend`。`configs/agents/eb_alfred.yaml` 中的 endpoint/model 是已验证 smoke example，不是项目级默认；[SERVER.md](SERVER.md) 只提供其中一种本地 serving 示例。配置完成后检查：

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
- [Agent Core](docs/agent_core/README.md)
- [Framework Components](docs/interfaces.md)
- [Observability](docs/components/observability.md)
- [SpatialMemory 空间记忆组件](docs/components/spatialmemory_memory.md)
- [SpatialMemory Backend 环境安装](docs/components/spatialmemory_backend.md)
- [自定义组件](docs/custom_components.md)
- [整体架构](impl_docs/architecture/overview.md)

### Benchmarks

- [EB-ALFRED 评测](docs/eb_alfred.md)
- [RoboCasa365 评测](docs/robocasa365.md)
- [Chemistry Bench Isaac Sim 化学台（固定任务真实闭环已验证）](docs/chemistry_bench.md)
