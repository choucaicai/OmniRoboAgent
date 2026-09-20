# SpatialMemory Backend 环境安装

`SpatialMemory` 是 OmniRoboAgent 的可选空间记忆组件。它支持两种模式：

- 对完整场景 PLY 只执行一次 SpatialLM 定位；
- 从 RGB-D 关键帧增量融合 voxel point map，并在地图更新后调用 SpatialLM。

两种模式都通过同一个进程内 `SpatialLMBackend` 返回
`walls`、`doors`、`windows` 和 `objects`。详细配置、RGB-D 输入协议和
`recall()` 契约见
[SpatialMemory 空间记忆组件](spatialmemory_memory.md)。

## 当前仓库结构

以下命令都从 OmniRoboAgent 仓库根目录执行。与旧版打包目录不同，当前仓库没有
外层 `OmniRoboAgent_Spatiallm/`；模型与示例均位于 `SpatialLM/` 内：

```text
OmniRoboAgent/
├── SpatialLM/                                  # SpatialLM 源码和依赖锁
│   ├── models/
│   │   └── SpatialLM1.1-Qwen-0.5B/            # 本地模型目录；权重需另行下载
│   ├── examples/spatiallm_demo/                # 示例脚本、输入说明和参考结果
│   ├── spatiallm/
│   ├── code_template.txt
│   ├── poetry.lock
│   └── pyproject.toml
├── src/omniroboagent/backends/spatial/         # SpatialLMBackend 适配层
├── src/omniroboagent/agent_core/memories/      # SpatialMemory/CompositeMemory
└── docs/components/spatialmemory_backend.md
```

仓库只保留模型目录占位文件，不提交 checkpoint。demo 的展示说明、运行脚本和参考
结果保存在 `SpatialLM/examples/spatiallm_demo/`；如果当前 checkout 不包含示例 PLY，
可按下文从官方 Testset 下载。

## 环境要求

SpatialLM 当前锁定并验证的基础组合为：

- Linux x86_64 和 NVIDIA GPU；
- Python 3.11；
- CUDA 12.4；
- PyTorch 2.4.1 + CUDA 12.4；
- Conda 或 Miniconda；
- C/C++ 编译工具；`flash-attn` 安装时会编译 CUDA 扩展。

基础 OmniRoboAgent 不要求这些 GPU 依赖。只有启用本地
`SpatialLMBackend` 时才需要创建下面的独立环境。

Ubuntu 可先安装常用编译和运行库：

```bash
sudo apt-get update
sudo apt-get install -y build-essential git libgl1 libglib2.0-0 libgomp1
```

## 创建环境

```bash
conda create -n omni-spatial python=3.11 -y
conda activate omni-spatial

conda install -y \
  nvidia/label/cuda-12.4.0::cuda-toolkit \
  conda-forge::sparsehash \
  conda-forge::uv

python -m pip install --upgrade pip setuptools wheel
python -m pip install "poetry==2.4.3"
```

让 CUDA 扩展使用当前 Conda 环境中的 toolkit：

```bash
export CUDA_HOME="$CONDA_PREFIX"
export PATH="$CUDA_HOME/bin:$PATH"
which python
which nvcc
nvcc --version
```

`nvcc --version` 应显示 CUDA 12.4。重新打开终端后，需要重新激活环境并设置
`CUDA_HOME` 和 `PATH`。

## 安装 SpatialLM 和 OmniRoboAgent

先使用 `SpatialLM/poetry.lock` 安装 SpatialLM 及 Sonata GPU 依赖：

```bash
cd SpatialLM
export POETRY_VIRTUALENVS_CREATE=false
poetry check --lock
poetry install --only main --no-interaction
MAX_JOBS=4 poetry run poe install-sonata
cd ..
```

然后把 OmniRoboAgent 和开发检查依赖安装到同一个环境：

```bash
uv pip install \
  --python "$CONDA_PREFIX/bin/python" \
  --editable . \
  --group dev
python -m pip check
```

不要使用旧版文档中的 `--editable ./OmniRoboAgent`；当前工作目录本身就是
OmniRoboAgent 仓库根目录。

### 同一环境安装 EB-ALFRED 时保留 SpatialLM 的 Torch

如果还要在当前环境安装 `omniroboagent[eb-alfred]`，需要注意根目录
`pyproject.toml` 中的 EB-ALFRED extra 固定了 `torch==2.4.0` 和
`torchvision==0.19.0`，并通过 `pytorch-cpu` index 安装；这会覆盖 SpatialLM 锁定的
CUDA 版本。最终运行 SpatialLM 时必须保留下面这组版本：

- `torch==2.4.1+cu124`
- `torchvision==0.19.1+cu124`
- `torchaudio==2.4.1+cu124`

同一环境中应先安装 EB-ALFRED 依赖，再执行上面的 SpatialLM 安装步骤。如果
EB-ALFRED 是后安装的，需要重新执行：

```bash
cd SpatialLM
export POETRY_VIRTUALENVS_CREATE=false
poetry install --only main --no-interaction
MAX_JOBS=4 poetry run poe install-sonata
cd ..
```

不要在此后再次安装或同步 `eb-alfred` extra，否则可能再次把 CUDA Torch 降级。运行
SpatialLM 前检查最终生效版本：

```bash
python - <<'PY'
import torch
import torchaudio
import torchvision

assert torch.__version__ == "2.4.1+cu124", torch.__version__
assert torchvision.__version__ == "0.19.1+cu124", torchvision.__version__
assert torchaudio.__version__ == "2.4.1+cu124", torchaudio.__version__
assert torch.version.cuda == "12.4", torch.version.cuda
assert torch.cuda.is_available(), "PyTorch 没有检测到 CUDA GPU"
print(torch.__version__, torchvision.__version__, torchaudio.__version__)
PY
```

由于当前 `eb-alfred` extra 的声明版本与 SpatialLM 不一致，`pip check` 可能报告 Torch
版本约束冲突；判断 SpatialLM 是否可运行时，以这里的 CUDA 版本检查和真实 demo 为准。

## 下载模型权重

模型 checkpoint 不在 Git 仓库中。安装完成后，从仓库根目录下载到当前约定路径：

```bash
hf download manycore-research/SpatialLM1.1-Qwen-0.5B \
  --local-dir SpatialLM/models/SpatialLM1.1-Qwen-0.5B
```

配置中的 `model_path` 应指向：

```text
SpatialLM/models/SpatialLM1.1-Qwen-0.5B
```

如果 Hugging Face 要求认证，先执行 `hf auth login`。模型权重遵循上游模型许可，
不要提交到本仓库。

## 验证安装

先做不加载 checkpoint 的导入和单元测试：

```bash
python - <<'PY'
from pathlib import Path

import torch
from spatiallm import SpatialLMInference
from omniroboagent.agent_core.memories.spatial import SpatialMemory
from omniroboagent.backends.spatial import SpatialLMBackend

model_path = Path("SpatialLM/models/SpatialLM1.1-Qwen-0.5B")
assert (model_path / "config.json").is_file(), model_path
assert torch.cuda.is_available(), "PyTorch 没有检测到 CUDA GPU"

print("torch:", torch.__version__)
print("torch CUDA runtime:", torch.version.cuda)
print("GPU:", torch.cuda.get_device_name(0))
print("imports: ok", SpatialLMInference, SpatialLMBackend, SpatialMemory)
PY

PYTHONPATH=src python -m pytest -q tests/unit/test_spatial_memory.py
python -m unittest discover -s SpatialLM/tests -p 'test_*.py' -v
```

### 真实 demo 与参考结果

原有 demo 的展示说明和已验证结果继续保留在
[`SpatialLM/examples/spatiallm_demo/README.md`](../../SpatialLM/examples/spatiallm_demo/README.md)。
它展示下面的链路，不依赖机器人、Planner 服务或上游点云模块：

```text
PLY point cloud
  -> SpatialLMBackend.infer_points()
  -> observation["spatial_context"]
  -> TieredMemory.update()
  -> TieredMemory.recall()
```

当前目录包含示例 PLY 时，可从仓库根目录直接运行，并使用新的输出目录避免覆盖参考
结果：

```bash
python SpatialLM/examples/spatiallm_demo/run_demo.py \
  --input SpatialLM/examples/spatiallm_demo/input/scene0000_00.ply \
  --model-path SpatialLM/models/SpatialLM1.1-Qwen-0.5B \
  --output-dir SpatialLM/examples/spatiallm_demo/output/deployment-smoke
```

参考结果仍可在没有 GPU 时直接查看：

- [结果摘要](../../SpatialLM/examples/spatiallm_demo/output/scene0000_00_seed42/summary.md)
- [结构化空间输出](../../SpatialLM/examples/spatiallm_demo/output/scene0000_00_seed42/spatial_context.json)
- [Memory recall 输出](../../SpatialLM/examples/spatiallm_demo/output/scene0000_00_seed42/memory_recall.json)
- [俯视叠加图](../../SpatialLM/examples/spatiallm_demo/output/scene0000_00_seed42/top_down.png)

参考运行记录为 `6 walls / 1 door / 1 window / 8 objects`，总耗时约
`6.42 s`。这是特定已验证环境中的复现证据，不是所有 GPU 上必须得到的固定输出。

### 示例 PLY 缺失时

如果 `SpatialLM/examples/spatiallm_demo/input/scene0000_00.ply` 不存在，可从
SpatialLM Testset 下载一份 PLY：

```bash
hf download manycore-research/SpatialLM-Testset \
  pcd/scene0000_00.ply \
  --repo-type dataset \
  --local-dir SpatialLM
```

下载结果位于 `SpatialLM/pcd/scene0000_00.ply`。可以通过 `--input` 将它传给上面的
demo，也可以通过 OmniRoboAgent 的全局场景模式执行一次真实定位：

```bash
python - <<'PY'
from omniroboagent.agent_core.memories.spatial import SpatialMemory
from omniroboagent.backends.spatial import SpatialLMBackend

memory = SpatialMemory(
    global_scene_ply="SpatialLM/pcd/scene0000_00.ply",
    spatial_backend=SpatialLMBackend(
        model_path="SpatialLM/models/SpatialLM1.1-Qwen-0.5B",
        default_wall_thickness=0.12,
        output_precision=6,
    ),
)

try:
    spatial = memory.recall({})["spatial"]
    print({name: len(items) for name, items in spatial.items()})
finally:
    memory.close()
PY
```

全局 PLY 与 demo 使用同一套读取方式：`SpatialLMBackend.infer_ply()` 调用 SpatialLM
的 `load_o3d_pcd()` 和 `get_points_and_colors()`，再将 NumPy points/colors 交给
`infer_points()`；OmniRoboAgent 不再维护另一套 PLY parser。

脚本正常退出且输出包含 `walls`、`doors`、`windows`、`objects` 四个集合，即说明
SpatialLM checkpoint、PLY 解析和 `SpatialMemory` 集成链路可用。模型生成包含采样，
不同 GPU 或依赖环境下的实体数量不要求逐位一致。

## 使用配置

安装完成后，不要把 backend 直接当作独立 Agent 使用。应由 `SpatialMemory` 持有并
复用 `SpatialLMBackend`；如需同时使用事件记忆，再通过 `CompositeMemory` 与
`TieredMemory` 组合。

以下内容统一维护在
[SpatialMemory 空间记忆组件](spatialmemory_memory.md)：

- 全局 PLY 单次定位配置；
- 在线 RGB-D voxel 建图配置；
- `CompositeMemory` 组合方式；
- 输入坐标系、深度和相机位姿约束；
- artifact、checkpoint、`recall()` 和当前能力边界。

SpatialLM 原始安装、推理和进程内接口还可参考
[`SpatialLM/README.md`](../../SpatialLM/README.md)
与
[`SpatialLM/INTEGRATION.md`](../../SpatialLM/INTEGRATION.md)。

## 常见问题

### `torch.cuda.is_available()` 为 `False`

```bash
which python
python -m pip show torch
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())"
```

确认当前 Python 属于 `omni-spatial`，PyTorch 是 CUDA 12.4 构建，并且
`nvidia-smi` 能正常识别 GPU。

### `nvcc`、CUDA headers 或 `CUDA_HOME` 找不到

```bash
conda activate omni-spatial
export CUDA_HOME="$CONDA_PREFIX"
export PATH="$CUDA_HOME/bin:$PATH"
which nvcc
nvcc --version
```

确认 `nvcc` 来自当前 Conda 环境后，再重新运行 `poetry run poe install-sonata`。

### `flash-attn` 编译失败或构建进程被杀死

先确认系统已安装编译工具，再降低并行度重试：

```bash
cd SpatialLM
MAX_JOBS=2 poetry run poe install-sonata
cd ..
```

### SpatialLM 与 Flask 的 Jinja2 版本冲突

在同一个 Python 环境中同时运行 SpatialLM 和 EB-ALFRED 时，旧版 Jinja2 可能导致
SpatialLM/Transformers 报错：

```text
AttributeError: module 'jinja2' has no attribute 'pass_eval_context'
ImportError: apply_chat_template requires jinja2>=3.1.0 to be installed
```

但如果只升级 Jinja2，旧版 Flask 又可能继续从 Jinja2 导入已移除的 `escape`：

```text
ImportError: cannot import name 'escape' from 'jinja2'
```

不要在 Jinja2 2.x 和 3.x 之间单独切换。需要在当前环境中将 Flask 及其相关依赖
一起调整为兼容组合：

```bash
python -m pip install --upgrade --force-reinstall \
  "Flask==2.0.3" \
  "Werkzeug==2.0.3" \
  "itsdangerous==2.0.1" \
  "Jinja2==3.1.6" \
  "MarkupSafe==3.0.3"
```

如果该环境还安装了 `omniroboagent[eb-alfred]`，应在安装 EB-ALFRED 和 SpatialLM
依赖后最后执行上面的命令；当前 `eb-alfred` optional dependency 仍声明旧版 Flask
依赖，因此 `pip check` 可能报告声明版本不一致，但运行时需要以上组合才能同时满足
Transformers 的 chat template 和 Flask 导入。可用下面的命令检查实际生效版本和两个
关键导入：

```bash
python - <<'PY'
from importlib.metadata import version

from flask import Flask
from jinja2 import pass_eval_context

for package in ("Flask", "Werkzeug", "itsdangerous", "Jinja2", "MarkupSafe"):
    print(f"{package}: {version(package)}")
print("imports: ok", Flask, pass_eval_context)
PY
```

### `ModuleNotFoundError: spatiallm` 或 `omniroboagent`

通常是没有激活正确环境，或 Poetry 创建了另一个 virtualenv。重新激活环境，确认
`POETRY_VIRTUALENVS_CREATE=false`，再重复安装步骤：

```bash
conda activate omni-spatial
python -m pip show spatiallm omniroboagent
```

### 找不到模型或 PLY

模型不会随 Git clone 自动出现；示例 PLY 是否存在取决于当前 checkout 或交付包。
检查配置使用的是仓库根目录下的实际路径，缺少文件时执行对应的 `hf download`
命令。生产环境可使用其他绝对路径，但不要把本机路径写入共享配置或文档。
