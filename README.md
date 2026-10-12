# OmniRoboAgent

OmniRoboAgent 是面向具身 Agent 的模块化构建、运行与评估框架。

```text
Observe -> Plan -> Act -> Verify -> Update or Stop
```

当前实现包含同步 Runtime、独立 episode observability artifacts、组合式 BaseAgent、显式 skill-execution graph state、独立 SubtaskVerifier、K 帧与关键事件 TieredMemory、OpenAI-compatible LLM、SkillBackend registry、EB-ALFRED，以及 RoboCasa365 的 atomic/composite Agent、GR00T/OpenPI/local VLA evaluation 路径。

## Clone

`benchmarks/` 保存 benchmark 及环境相关包，`third_party/` 保存通用第三方依赖；外部项目使用
Git submodule 管理。主仓库只保存上游 URL 和固定 commit，不重复上传第三方源码。

首次 clone 时同时拉取 submodule：

```bash
git clone --recurse-submodules https://github.com/choucaicai/OmniRoboAgent.git
cd OmniRoboAgent
```

如果已经 clone 了主仓库，再初始化 submodule：

```bash
git submodule update --init --recursive
```

拉取主仓库更新后，使用同一命令让 submodule 回到主仓库记录的 commit。不要在第三方 submodule 中提交本项目代码。

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

## 化学仿真平台：为智能体提供化学实验 Demo

这是本项目自研的化学实验仿真模块，当前目标是生成一个完整、可观察的酸碱滴定
demo，展示机械臂动作、实验状态变化与 Agent 闭环，而不是建立新的 benchmark。
它使用独立 Isaac Sim 4.5 worker，并通过 gRPC 接入 OmniRoboAgent。

演示任务是抓取 NaOH 试剂瓶、逐次向含 HCl 和酚酞的烧杯加液，观察变粉红后停止，
放回试剂瓶并记录实验结果。当前化学引擎计算酸碱中和、近似 pH 和指示剂显色；
机械臂使用逆运动学和脚本插值。暂不投入流体模拟、精确接触或策略训练。

```text
Isaac Sim 实验台 RGB / 可用动作
                ↓
LanguageSkillPlanner → LanguageSkillBackend
                ↓
ChemistryBenchEnvironment → gRPC worker → 机械臂 / 化学状态
                ↓
新图像与执行反馈 → EnvironmentVerifier → 继续或结束
```

### 模块与运行方式

- `benchmarks/chemistry-bench-sim`：自有实验场景、化学状态引擎、机械臂动作和录像 worker。
- `benchmarks/chemistry-bench-proto`：worker 与客户端共用的 gRPC 协议。
- `ChemistryBenchEnvironment`：把 RGB、动作列表和反馈接入现有 `DirectPipeline`；
  pH、体积等内部状态仅用于判定结果，不作为模型输入。
- `configs/agents/chemistry_bench_titration.yaml` 和
  `configs/runs/chemistry_bench_titration.yaml`：模型闭环配置。

`chemistry_bench` 是沿用的包名和配置标识，不代表此 demo 是标准化 benchmark。
Agent 与 Isaac Sim worker 分开安装，在项目根目录执行：

```bash
UV_PROJECT_ENVIRONMENT=.venv-chemistry_bench uv sync --extra chemistry_bench --group dev

/absolute/path/to/isaac-sim-4.5.0/python.sh -m pip install \
  ./benchmarks/chemistry-bench-proto ./benchmarks/chemistry-bench-sim

CHEMISTRY_BENCH_SIM_GPU=0 CHEMISTRY_BENCH_FRANKA_USD=/absolute/path/to/franka.usd \
  /absolute/path/to/isaac-sim-4.5.0/python.sh \
  -m chemistry_bench_sim.worker --port 50051 --record-dir runs/chemistry_bench_demo
```

worker 保持运行，在另一个终端生成脚本 demo（不需要模型服务）：

```bash
.venv-chemistry_bench/bin/python scripts/smoke_chemistry_bench.py \
  --address 127.0.0.1:50051 --output runs/chemistry_bench_scripted
```

需要模型闭环时，先在 AgentConfig 中设置可用的多模态 `base_url` / `model`，再执行：

```bash
.venv-chemistry_bench/bin/omniroboagent run \
  --config configs/runs/chemistry_bench_titration.yaml
```

### Demo 验证范围

已验证带机械臂运动的脚本演示：5 步完成滴定与记录，连续录像 416 帧、20 FPS、
20.8 秒。更早的静态机械臂版本也通过 Qwen3.5-9B 的 13 步模型闭环；相机与运动
更新后尚未重验模型闭环。当前没有化学平台的系统 benchmark 成绩。

完整安装、动作接口、成功条件、录像说明与验证记录见
[化学仿真平台 Demo](docs/chemistry_bench.md)。

## RoboSynChallenge：使用 OmniRoboAgent 运行官方任务

这部分使用第三方 [RoboSynChallenge](https://github.com/EDEM-AI/RoboSynChallenge)
的官方任务、EmbodiChain/DexSim 仿真环境及公开策略权重，验证 OmniRoboAgent 的
规划、执行、反馈与评测链路；不是在上面的化学仿真平台中运行。
本项目实现的是接入适配和评测 runner，不将官方 benchmark 或仿真 SDK 视为自研模块。

接入模块把官方机器人任务的 RGB、关节状态和原生动作转换为
OmniRoboAgent 的 Environment contract，使已有 Planner、SkillBackend、Verifier、
Memory 和 Pipeline 能在同一闭环中运行，并按固定 seeds 统计成功率。
它提供一个 benchmark 的十项任务；EmbodiChain 是仿真依赖，不是第二个 benchmark。

```text
RoboSynChallenge RGB / robot qpos
                ↓
    RoboSynChallengeEnvironment
                ↓
      Qwen Planner → ACT SkillBackend
                ↓
    EmbodiChain / DexSim 执行原生动作
                ↓
    原生成功信号 + Qwen Verifier
                ↓
     Memory / Pipeline → 继续或终止
```

### 模块组成与目录

- `RoboSynChallengeEnvironment`：读取 RGB/proprioception，不向策略提供 privileged
  task state；校验 `{"actions": [T, D]}`，当前模型使用 CobotMagic 14 维原生动作。
- `RoboSynPolicyBackend`：本地加载公开 ACT/DP 权重，只生成动作，不执行动作。
- `RoboSynChallengeEvaluator`：保存逐 seed 结果、配置/权重/源码身份、trace 和录像。
  矩阵 runner 支持独立任务子进程、多 GPU 队列、动态调度和严格断点续跑。
- `configs/agents/robosynchallenge_act_visual.yaml`：复用 `SubtaskSkillPlanner`、
  `SubtaskVerifier`、`TieredMemory` 和 `SkillExecutionPipeline`，不新增核心推理流程。
- `configs/runs/robosynchallenge_act_random_manifest.json`：固定十项 ACT checkpoint
  revision、`random` 设置和每任务 seeds 0–99，共 1000 回合。

官方任务源码在 `benchmarks/RoboSynChallenge`，通用仿真 SDK 在
`third_party/EmbodiChain`，两者均是固定版本的 submodule；
`benchmarks/robosyn-runtime` 是本项目自有的隔离依赖配置和 `uv.lock`。
模型下载到 `../models/robosyn/`，运行输出位于 `runs/robosynchallenge/`，不提交 Git。

### 安装、权重与服务

从项目根目录初始化两个上游依赖，使用 Python 3.11 安装独立运行环境：

```bash
git submodule update --init --recursive benchmarks/RoboSynChallenge third_party/EmbodiChain

GIT_LFS_SKIP_SMUDGE=1 UV_PROJECT_ENVIRONMENT="$PWD/.venv-robosyn" \
  uv sync --locked --project benchmarks/robosyn-runtime --python 3.11 \
  --allow-insecure-host pyp.open3dv.site:2345

export EMBODICHAIN_DATA_ROOT="$(mktemp -d /tmp/rsc.XXXXXX)"
```

运行需要 NVIDIA GPU 和兼容驱动。DexSim 0.4.3 使用上游指定的 HTTP 包源，锁文件
保留包哈希；`GIT_LFS_SKIP_SMUDGE` 只用于跳过 LeRobot 安装时的测试图片，不跳过
模型下载。短资产缓存避免引擎的 255 字节材质标识限制，后续运行和续跑复用该目录。

单任务可先下载 bell checkpoint：

```bash
.venv-robosyn/bin/hf download RoboSynChallenge/ACT_sim_click_bell \
  --revision 677e65fbb15974024ff840893496197ef7db26d4 \
  --local-dir ../models/robosyn/ACT_sim_click_bell
```

完整矩阵按清单下载十项模型，每项约 197 MiB：

```bash
.venv-robosyn/bin/python - <<'PY'
import json
from pathlib import Path
from huggingface_hub import snapshot_download

manifest = json.loads(
    Path("configs/runs/robosynchallenge_act_random_manifest.json").read_text()
)
for task in manifest["tasks"]:
    snapshot_download(
        repo_id=f"RoboSynChallenge/ACT_sim_{task['name']}",
        revision=task["checkpoint_revision"],
        local_dir=task["checkpoint_path"],
    )
PY
```

预先启动支持图像输入和 JSON schema 输出的 OpenAI-compatible 服务。AgentConfig
中 Planner、Verifier 两处 `base_url` / `model` 分别配置实际地址和模型 ID；示例为
`http://127.0.0.1:28000` / `Qwen3.5-9B`。框架不启动或关闭服务端。
每个原生动作后读取环境反馈并验证；配置每 64 个 action chunks 做一次视觉语义检查。
最终成功依据 `is_task_success() and not truncated`，不由模型自行宣告。

### 单任务与完整评测

先验证 `click_bell` seed 0 的真实模型闭环和录像：

```bash
env -u CUDA_VISIBLE_DEVICES CUDA_DEVICE_ORDER=PCI_BUS_ID \
  EMBODICHAIN_SIM_EXIT_PROCESS=0 PYTHONPATH=src \
  .venv-robosyn/bin/python scripts/eval_robosynchallenge.py \
  --robosyn-root benchmarks/RoboSynChallenge \
  --embodichain-root third_party/EmbodiChain \
  --task click_bell --setting random --policy act --seeds 0 \
  --checkpoint ../models/robosyn/ACT_sim_click_bell \
  --checkpoint-revision 677e65fbb15974024ff840893496197ef7db26d4 \
  --agent-config configs/agents/robosynchallenge_act_visual.yaml \
  --output runs/robosynchallenge/smoke --gpu 0 --device cuda:0 --record-video
```

完整矩阵使用相同模型服务和资产缓存：

```bash
env -u CUDA_VISIBLE_DEVICES CUDA_DEVICE_ORDER=PCI_BUS_ID \
  EMBODICHAIN_SIM_EXIT_PROCESS=0 PYTHONPATH=src \
  .venv-robosyn/bin/python scripts/eval_robosynchallenge.py \
  --robosyn-root benchmarks/RoboSynChallenge \
  --embodichain-root third_party/EmbodiChain \
  --matrix-manifest configs/runs/robosynchallenge_act_random_manifest.json \
  --output runs/robosynchallenge/act-visual-random \
  --gpu 0 --device cuda:0 --record-video
```

追加 `--matrix-gpus 0 1 --matrix-scheduling dynamic` 可使用两条同步队列，由空闲
GPU 领取后续任务；仍是每任务单环境，不拆分 seeds。首次运行使用新输出目录；
续跑保持配置、缓存、GPU 分配及输出不变，追加 `--resume` 跳过有效回合，仅重试
缺失或异常项。元数据改变或旧 reset 协议会被拒绝续跑。

DexSim 的 Vulkan GPU index 不随 `CUDA_VISIBLE_DEVICES` 重映射，需保持 CUDA
完整可见，让 `--gpu N` 与 `--device cuda:N` 一致。根 `summary.json` 汇总成绩、
覆盖率和错误；每回合保存 `episode.json`、trace、`agent_trace.jsonl`、录像和
`artifact_manifest.json`。在单任务命令中省略 `--agent-config` 可运行相同策略的直接 baseline；
该模式不调用视觉 Planner/Verifier，也不使用专家控制器。

### 验证结果与边界

历史 Qwen3.5-9B + ACT 评测完成十任务 × 100 回合：412/1000 成功（41.2%），
588 次正常失败，所有有效结果和录像/日志已核对。这是 OmniRoboAgent 在官方任务
环境中的成绩，不是化学仿真平台的成绩。采用显式未过滤 seeds，未按
主办方专家可行性筛选，因此不是论文成绩的精确复现。目录布局调整只重新验证
CPU 测试和依赖锁，未在新布局重跑 GPU 矩阵；历史源码身份见结果文档。

ACT 本身不接收语言条件；DP backend 已做单元验证，但没有完整真实矩阵成绩；
SmolVLA 未接入。曾有一次 native GC 退出崩溃发生在该任务的 100 回合保存后，原始证据
保留，缓存续跑退出正常不代表该清理问题已修复。无策略训练，也不改变官方物理参数。

完整接口、固定上游版本、安装故障排查和运行限制见
[RoboSynChallenge 接入文档](docs/robosynchallenge.md)；逐任务成绩、历史源码身份
和审计说明见 [完整评测结果](docs/robosynchallenge-results.md)。

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
- [化学仿真平台 Demo（固定滴定任务与录像）](docs/chemistry_bench.md)
- [自定义组件](docs/custom_components.md)
- [整体架构](impl_docs/architecture/overview.md)

### Benchmarks

- [EB-ALFRED 评测](docs/eb_alfred.md)
- [RoboCasa365 评测](docs/robocasa365.md)
- [RoboSynChallenge 接入与完整评测（1000 回合，41.2%）](docs/robosynchallenge.md)
