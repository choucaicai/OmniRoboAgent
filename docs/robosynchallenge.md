# OmniRoboAgent 运行 RoboSynChallenge 官方任务

[RoboSynChallenge](https://github.com/EDEM-AI/RoboSynChallenge) 是第三方 benchmark。
本项目通过适配模块让 OmniRoboAgent 在其官方任务和 EmbodiChain/DexSim 环境中
运行，支持本地 ACT/DP 推理、单任务 smoke 和带断点续跑的多任务评测；仿真依赖
不进入 core。这条评测路径与本项目的 [化学实验固定滴定 demo](chemistry_bench.md) 独立。

已完成的历史 ACT 模型闭环评测为十项 RoboSynChallenge 官方任务 × 100 回合，
成功率 41.2%；该成绩不属于化学实验仿真平台。
成绩口径、源码版本及已知限制见 [完整结果](robosynchallenge-results.md)。
本 PR 基于最新 master 的集成仅做 CPU 验证，未重新执行 1000 回合 GPU 评测。

## 准备源码和运行环境

以下命令均从本项目根目录运行。上游源码由仓库内 submodule 固定：

```bash
git submodule update --init --recursive benchmarks/RoboSynChallenge third_party/EmbodiChain
```

`benchmarks/RoboSynChallenge` 链接
[EDEM-AI/RoboSynChallenge](https://github.com/EDEM-AI/RoboSynChallenge)，固定
`8818c82df5fa2522809b8105e7018950dcc9a9a8`；通用仿真 SDK `third_party/EmbodiChain` 链接
[DexForce/EmbodiChain](https://github.com/DexForce/EmbodiChain)，固定
`89c14da8d0221dc4ee2a4a3e0ba1078b16d447bd`。不再需要仓库外同级 checkout。
`benchmarks/robosyn-runtime` 仍是本项目自有的隔离依赖锁目录。

使用可用的 Conda Python 3.11，创建独立 `.venv-robosyn`：

```bash
GIT_LFS_SKIP_SMUDGE=1 UV_PROJECT_ENVIRONMENT="$PWD/.venv-robosyn" \
  uv sync --locked --project benchmarks/robosyn-runtime --python 3.11 \
  --allow-insecure-host pyp.open3dv.site:2345
```

`GIT_LFS_SKIP_SMUDGE` 只用于安装期间跳过 LeRobot 的测试图片，不跳过模型权重。
DexSim 0.4.3 使用上游指定的 HTTP 包源，lock 保留文件哈希；EmbodiChain 对应
`v0.2.4.post1`。运行环境固定 NumPy 1.x、PyArrow 21 和 pandas 2.x，以满足
仿真器和 LeRobot 数据模块的实际导入要求。需要 NVIDIA GPU 和兼容驱动。

## 下载策略权重

隔离环境已安装 Hugging Face 的 `hf` 命令。单任务示例：

```bash
.venv-robosyn/bin/hf download RoboSynChallenge/ACT_sim_click_bell \
  --revision 677e65fbb15974024ff840893496197ef7db26d4 \
  --local-dir ../models/robosyn/ACT_sim_click_bell
```

完整 ACT 矩阵的路径和 revision 固定在
`configs/runs/robosynchallenge_act_random_manifest.json`。按清单下载全部十项：

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

每个 checkpoint 约 197 MiB，至少保留 `config.json`、`train_config.json` 和
`model.safetensors`。模型、仿真资产及运行产物均不提交 Git。DP 可通过
`--policy dp --checkpoint <checkpoint-directory>` 使用对应的公开权重；本页成绩
只覆盖 ACT，SmolVLA 未接入当前 SkillBackend。

## 资产缓存和模型服务

首次获取资产前设置较短的缓存目录，并在 smoke、矩阵及续跑之间复用：

```bash
export EMBODICHAIN_DATA_ROOT="$(mktemp -d /tmp/rsc.XXXXXX)"
```

上游按任务配置获取和解压资源；已有缓存可按原 `download/`、`extract/` 布局
复制到短目录，保持资源字节不变。DexSim 内部材质标识有 255 字节限制，过长的
资产绝对路径可能触发原生断言。不要在每次 `--resume` 时重新生成缓存目录；
跨 shell 运行时重新设置为此前使用的目录。

模型闭环使用 `configs/agents/robosynchallenge_act_visual.yaml`。请预先启动支持
图像输入和 JSON schema 输出的 OpenAI-compatible 服务，并将 Planner、Verifier
两处 `base_url` / `model` 改为实际地址和模型 ID。默认示例为
`http://127.0.0.1:28000` / `Qwen3.5-9B`；服务由用户管理，runner 只使用客户端。

```bash
curl --fail http://127.0.0.1:28000/v1/models
```

ACT 本身没有语言输入。视觉 Planner 提出 task skill/subtask，ACT 产生本地动作；
每次执行后进入 Verifier，配置每 64 个 action chunks 做一次视觉语义检查，最终
成功优先依据原生 `is_task_success() and not truncated`。
SkillBackend 输出 `{"actions": [T, D]}`；adapter 校验并执行原生关节位置动作，
夹爪归一化由上游 controller 定义。当前十项公开模型均使用 14 维 CobotMagic 动作。

## 单任务 smoke

使用一项任务、一个 seed 验证真实模型闭环和录像：

```bash
env -u CUDA_VISIBLE_DEVICES CUDA_DEVICE_ORDER=PCI_BUS_ID \
  EMBODICHAIN_SIM_EXIT_PROCESS=0 PYTHONPATH=src \
  .venv-robosyn/bin/python scripts/eval_robosynchallenge.py \
  --robosyn-root benchmarks/RoboSynChallenge --embodichain-root third_party/EmbodiChain \
  --task click_bell --setting random --policy act --seeds 0 \
  --checkpoint ../models/robosyn/ACT_sim_click_bell \
  --checkpoint-revision 677e65fbb15974024ff840893496197ef7db26d4 \
  --agent-config configs/agents/robosynchallenge_act_visual.yaml \
  --output runs/robosynchallenge/smoke --gpu 0 --device cuda:0 --record-video
```

在单任务命令中省略 `--agent-config` 会运行 `TaskSkillPlanner`、`EnvironmentVerifier` 和相同学习型
策略的 baseline；它不调用视觉 Planner/Verifier，也不使用专家控制器。

## 完整矩阵与续跑

清单定义十项任务、`random` 设置和显式 seeds 0–99，共 1000 episodes：

```bash
env -u CUDA_VISIBLE_DEVICES CUDA_DEVICE_ORDER=PCI_BUS_ID \
  EMBODICHAIN_SIM_EXIT_PROCESS=0 PYTHONPATH=src \
  .venv-robosyn/bin/python scripts/eval_robosynchallenge.py \
  --robosyn-root benchmarks/RoboSynChallenge --embodichain-root third_party/EmbodiChain \
  --matrix-manifest configs/runs/robosynchallenge_act_random_manifest.json \
  --output runs/robosynchallenge/act-visual-random \
  --gpu 0 --device cuda:0 --record-video
```

首次运行选择新的输出目录；续跑使用相同配置、缓存和输出，并追加 `--resume`。
有效成功和正常失败均跳过，只重试缺失或异常回合；异常保存当前结果后停止该
任务，其余任务继续。元数据不一致会明确拒绝续跑。reset 标记为
`warmup_get_obs_get_info_v2`：在已有 reset warmup 后调用 `get_obs()` → `get_info()`，
这项状态修正不额外增加动作或物理步；缺少该标记的旧结果不能混入。

多卡可追加 `--matrix-gpus 0 1`：默认固定分组，每卡独立顺序运行单环境子进程。
追加 `--matrix-scheduling dynamic` 后，完成已分配任务的 GPU 可领取后续任务；
分配原子保存到 `gpu_allocation.json`，续跑保留已有分配。调度不拆分 seeds，
也不改变相机、物理步、动作、模型或 Verifier 周期。请保留已用 GPU ID。

DexSim 的 Vulkan GPU index 不随 `CUDA_VISIBLE_DEVICES` 重映射。保持 CUDA 完整
可见和 `CUDA_DEVICE_ORDER=PCI_BUS_ID`，让 `--gpu N` 与 `--device cuda:N` 一致；
否则可能出现 semaphore import 错误和原生 abort。

输出包括根 `summary.json`、逐任务 `metadata.json` / `episodes.jsonl`、逐回合
`episode.json` / trace / 录像。metadata 记录完整 seeds、源码 commit、checkpoint
revision/SHA256、任务配置和组件身份。根 summary 每 10 秒聚合部分结果；任务
失败不影响覆盖完整性，缺失/异常或子进程退出错误会令 `complete=false`。

## 原生退出限制

历史运行中，`item_assembly` 全部 100 回合保存后在 native GC 阶段 SIGSEGV
退出 `-11`。回合结果有效，但该清理问题尚未修复。应保留原日志和退出 summary；
不要修改返回码或将清理故障当作策略失败。

若全部有效回合已经落盘，可在原队列自然退出后、保存原 summary 快照，再按
相同参数严格 `--resume`。缓存续跑验证配置、跳过全部 rollout、重新聚合并正常
退出，不加载策略、创建仿真器或依赖在线模型服务；这不证明 native GC 已修复。
正常运行设置 `EMBODICHAIN_SIM_EXIT_PROCESS=0`，让父进程保留实际退出状态。
