# RoboCasa365 Evaluation

OmniRoboAgent 通过一个 `RoboCasa365Evaluator` 运行 Agent + VLA 闭环。Evaluator 负责 task/episode 遍历与指标，`RoboCasaEnvironment` 负责 simulator，policy backend 由 registry 配置选择。

当前固定 RoboCasa submodule commit：

```text
9a3a78680443734786c9784ab661413edb87067b
```

该 checkout 的 `TASK_SET_REGISTRY` 有 317 个唯一 task，其中 65 个 atomic task、252 个 composite task。“RoboCasa365”是 benchmark 名称，不能理解为当前 commit 注册了 365 个 Gym environment。

## Install RoboCasa And Assets

初始化 submodule：

```bash
git submodule update --init --recursive
```

为 simulator 创建独立 Python 3.11 Conda 环境，并按照 `benchmarks/RoboCasa/README.md` 的 Installation 安装该 commit 要求的 robosuite 与 RoboCasa。assets 必须按官方教程初始化：

```bash
conda activate robocasa
cd benchmarks/RoboCasa
python -m robocasa.scripts.setup_macros
python -m robocasa.scripts.download_kitchen_assets
cd ../..
```

不要提交下载的 assets。已经有另一份完整 assets 时，可以在本机创建软链：

```bash
bash scripts/link_robocasa_assets.sh \
  /path/to/robocasa/robocasa/models/assets
```

第二个参数可以覆盖默认目标 `benchmarks/RoboCasa/robocasa/models/assets`。脚本不会替换已有文件或指向其他位置的链接。

将 OmniRoboAgent 和所需 client 安装到 simulator 环境：

```bash
conda activate robocasa
uv pip install --python "$CONDA_PREFIX/bin/python" --editable '.[groot-client]'
uv pip install --python "$CONDA_PREFIX/bin/python" --editable '.[openpi]'
```

GR00T、OpenPI 和 RoboCasa 的模型依赖可能冲突。remote 模式应将 GPU model server 与 simulator 放在不同 Conda 环境；OmniRoboAgent checkout 只需分别 editable install，不要复制源码。

## Backend Registry

`skill_backend.name` 选择可执行 backend，Evaluator 不包含 transport 分支：

| Name | Backend | Transport |
| --- | --- | --- |
| `groot_remote` | GR00T RoboCasa policy | ZeroMQ + `torch.save` |
| `openpi_remote` | OpenPI RoboCasa policy | WebSocket + msgpack |
| `local` | 已实例化的 in-process policy | Python call |

例如：

```yaml
skill_backend:
  name: openpi_remote
  init_args:
    host: localhost
    port: 8000
    timeout_seconds: 120
```

`name` 与 `class_path` 互斥。其他 backend 可以直接使用 `class_path + init_args`；框架不做自动 plugin discovery。

## GR00T Remote

server 使用 RoboCasa benchmark 的 `Isaac-GR00T` fork。已验证 checkout 以 `9d7d7a9eb7ad30bd8ce30448d9ab53a918b45b10` 为 base，但本次 checkpoint 依赖本机未提交的 `gr00t.model_moe_v1` 和 `data_config_mem_groot.py` 扩展；该 base commit 本身不包含这两个 module。其他用户必须提供与 checkpoint 匹配且可 import 的 policy/data config，不能只 checkout 该 commit。server 脚本自己注册 `reset_episode_memory`，不要求修改 upstream `gr00t/eval/robot.py`。

```bash
conda activate <groot-env>
python scripts/serve_robocasa_groot.py \
  --groot-root /path/to/Isaac-GR00T \
  --model-path /path/to/checkpoint-240000 \
  --policy-class-path gr00t.model_moe_v1.policy.Gr00tPolicy \
  --data-config panda_omron \
  --embodiment-tag new_embodiment \
  --memory-queue-size 0 \
  --device cuda:0 \
  --port 5555
```

GR00T 原生 wire format 使用 unrestricted `torch.load` 反序列化。server 默认只 bind `127.0.0.1`；只连接可信 endpoint，跨机器时使用受控内网或 SSH tunnel，禁止直接暴露公网。`--api-token` 在反序列化之后才由上游 server 校验，不能作为防止恶意 payload 的安全边界。

另一个终端运行固定 `atomic_seen / pretrain / CloseBlenderLid / seed=0` smoke：

```bash
conda activate robocasa
omniroboagent health \
  --agent-config configs/agents/robocasa365_groot_remote.yaml
omniroboagent run \
  --config configs/runs/robocasa365_groot_remote_smoke.yaml
```

Atomic 配置中，`model_moe_v1` 要求 planner skill 是 concrete RoboCasa task name，例如 `CloseBlenderLid`。缺少显式 `skill_id` 时，backend 会保持 `skill == task` 的严格校验。当前 checkpoint 的 action head 自己预测内部 soft skill 表示；外部 task name 用于 policy 输入与诊断，不表示框架把 gold skill id 直接路由到 action head。

## Composite Agent With Atomic GR00T Skills

Composite 配置保留 RoboCasa composite task 作为 Environment reset 和 success metric 的对象，由 `Qwen3.5-9B` 选择 atomic macro skill 和具体 subtask：

```text
composite task
  -> SubtaskSkillPlanner
  -> macro skill + trusted local skill_id + grounded subtask proposal
  -> atomic GR00T checkpoint
  -> SubtaskVerifier compares before/after evidence
  -> deterministic transition/recovery
  -> RoboCasa authoritative success
```

Planner structured output 包含 `skill`、`subtask`、`grounded_arguments` 和 `expected_outcome`；`skill_id` 由 AgentConfig 的可信本地映射补充，不接受模型生成的 ID。Planner 不判断 subtask 是否完成。当前 catalog 为：

| Skill | ID |
| --- | ---: |
| `Close_Door` | 1 |
| `Open_Door` | 2 |
| `Close_Lid` | 3 |
| `Open_Lid` | 4 |
| `Insertion` | 5 |
| `Navigation` | 6 |
| `Pick_Place` | 7 |
| `Press_Button` | 8 |
| `Slide_Rack` | 9 |
| `Turn_Lever` | 10 |
| `Twist_Knob` | 11 |

先按 [SERVER.md](../SERVER.md) 启动 `Qwen3.5-9B` OpenAI-compatible endpoint。Remote GR00T server 启动后运行：

```bash
conda activate robocasa
omniroboagent health \
  --agent-config configs/agents/robocasa365_groot_composite_remote.yaml
omniroboagent run \
  --config configs/runs/robocasa365_groot_composite_remote_smoke.yaml
```

该 smoke 固定 `composite_seen / pretrain / DeliverStraw / episode_index=0 / seed=0`。RunConfig 通过 `RoboCasaEnvironment.available_skills` 暴露 macro catalog；GR00T request 同时保留 composite `task`、atomic `skill`、显式 `skill_id` 和 concrete task description。

### Planner Output And Real Subtask Examples

`Qwen3.5-9B` 每次只生成一个当前子任务。模型 structured output 不包含 `skill_id`：

```json
{
  "reasoning": "short decision reason",
  "skill": "Pick_Place",
  "subtask": "Pick the kettle from the counter and place it on a stove burner",
  "grounded_arguments": {
    "object": "kettle",
    "source": "counter",
    "target": "stove burner"
  },
  "expected_outcome": "the kettle is resting on a stove burner"
}
```

`SubtaskSkillPlanner` 校验 proposal 后，从 AgentConfig 补充可信 ID。传给 Pipeline 的主要字段为：

```json
{
  "skill": "Pick_Place",
  "skill_id": 7,
  "subtask": "Pick the kettle from the counter and place it on a stove burner",
  "grounded_arguments": {
    "object": "kettle",
    "source": "counter",
    "target": "stove burner"
  },
  "expected_outcome": "the kettle is resting on a stove burner"
}
```

`reasoning` 只写入 trace，不直接传给 VLA。GR00T 接收 composite task name、macro skill、skill ID，以及写入 `annotation.human.task_description` 的 concrete subtask。

Planner 只在没有 active execution 或 recovery replan 时调用。Composite `SubtaskVerifier` 每 8 个 action chunks 使用 action 前后相机 observation 检查 `expected_outcome`，输出：

```text
in_progress / completed / failed / uncertain
reason / confidence / evidence
```

`SkillExecutionPipeline` 使用 `execution_id`/`attempt_id` 维护 active execution。`in_progress` 继续执行而不调用 Planner；`completed` 关闭 execution 并规划下一 subtask；`failed` 进入 retry/replan/fallback/abort；`uncertain` 先 reverify。`max_chunks_per_skill=27` 是 hard execution budget。

以下是 state-graph 迁移前 40-episode matrix 中 `Qwen3.5-9B` 的实际输出，不是手写示例；这些结果用于历史对照，不代表迁移后的 verifier 已完成真实 checkpoint smoke：

| Composite task | Step | Skill | Generated subtask |
| --- | ---: | --- | --- |
| `DeliverStraw` | 1 | `Open_Door` | `Open the drawer in front to retrieve the straw` |
| `DeliverStraw` | 2 | `Pick_Place` | `Pick up the straw from the open drawer` |
| `DeliverStraw` | 3 | `Pick_Place` | `Move to the dining counter and place the straw into the glass cup` |
| `KettleBoiling` | 1 | `Navigation` | `Move to the kettle on the counter` |
| `KettleBoiling` | 2 | `Pick_Place` | `Pick the kettle from the counter and place it on a stove burner` |
| `KettleBoiling` | 3 | `Twist_Knob` | `Turn the stove knob to the on position` |
| `ArrangeBreadBasket` | 1 | `Open_Door` | `Open the cabinet door` |
| `ArrangeBreadBasket` | 2 | `Pick_Place` | `Pick up the bread from the cabinet and place it in the basket` |
| `ArrangeBreadBasket` | 3 | `Pick_Place` | `Move the basket to the dining counter` |

`KettleBoiling` 的这组 sequence 是本次 matrix 中唯一由 RoboCasa 判定成功的 episode。

该历史 matrix 有以下已验证限制：

- 子任务可能合并多个物理阶段。例如 `Move to the dining counter and place the straw into the glass cup` 同时包含 Navigation 和 placement，却只使用 `Pick_Place`。
- `last_action_success=true` 只表示 action chunk 成功执行，不表示 subtask 已完成；旧 Planner contract 会过早切换或重复 subtask。
- 旧实现没有独立视觉 verifier，同一 placement subtask 可能被重复执行到 environment horizon。
- 旧 `continue_subtask` contract 依赖 wording 完全一致，模型改写措辞会产生 Planner retry；新实现已移除此依赖。

因此该历史 subtask trace 适合验证 Agent-to-VLA contract 和定位 Planner 问题，不应视为新 state graph 的质量结果。迁移后的真实 composite smoke 尚未运行。

## OpenPI Remote

server 与 client 都使用 `robocasa-benchmark/openpi` fork。`openpi` extra 固定 commit `5a6beda9ff99da30b4e1b59320f6a32971d7c397`；该 client 保持 WebSocket/msgpack protocol，并允许 clean RoboCasa 所需的 NumPy 2。

```bash
conda activate <openpi-env>
python scripts/serve_robocasa_openpi.py \
  --openpi-root /path/to/robocasa-benchmark/openpi \
  --config pi0_robocasa_pretrain_human300 \
  --checkpoint /path/to/openpi-checkpoint \
  --port 8000
```

```bash
conda activate robocasa
omniroboagent run \
  --config configs/runs/robocasa365_openpi_remote_smoke.yaml
```

`OpenPIRoboCasaPolicyBackend` 按官方 evaluator 组装 3 路 224x224 image、16-D state 和 prompt，并把 server 的 `[T, 12]` action 转成 RoboCasa 的五个 action key。RunConfig 每个 chunk 只执行前 5 步，再重新观察和请求 policy。

本机没有可用的 OpenPI checkpoint，因此当前只完成 server/client/config、RoboCasa schema 和 fake protocol test；尚未声明真实 OpenPI policy smoke 成功。

## Local GR00T

local 模式在 simulator 进程内 lazy load GR00T。设置 checkpoint 和 import path：

```bash
export OMNIROBOAGENT_GROOT_MODEL_PATH=/path/to/checkpoint-240000
export PYTHONPATH=/path/to/Isaac-GR00T:${PYTHONPATH:-}

conda activate <combined-robocasa-groot-env>
omniroboagent run \
  --config configs/runs/robocasa365_groot_local_smoke.yaml

# Composite Agent + atomic GR00T
omniroboagent run \
  --config configs/runs/robocasa365_groot_composite_local_smoke.yaml
```

默认 simulator source 是 `benchmarks/RoboCasa`。若 combined 环境只兼容另一份相同 commit 的 RoboCasa checkout，可以显式覆盖：

```bash
export OMNIROBOAGENT_ROBOCASA_ROOT=/path/to/compatible/robocasa
```

当前 local smoke 因 GR00T 环境使用 `numpy==1.26.4`，而 clean submodule 要求 `numpy==2.2.5`，使用了同 commit 的兼容本地 checkout。local 模式还会让 simulator 与 policy 争用 GPU memory。

## Evaluation Configuration

Evaluator 的主要字段：

| Field | Meaning |
| --- | --- |
| `task_set` | `TASK_SET_REGISTRY` key，例如 `atomic_seen` |
| `split` | 独立的 simulator split：`pretrain` 或 `target` |
| `task_names` | 可选显式 task 列表，必须属于 `task_set` |
| `max_tasks` | 可选 task 数上限，smoke 为 `1` |
| `episodes_per_task` | 每 task rollout 数，正式默认 `50` |
| `episode_indices` | 唯一非负 ordinal；当前通过 `seed + index` 驱动 reset |
| `seed` | reset 基准 seed |
| `output_dir` | evaluation artifact 根目录 |

`episode_index` 当前不是 dataset scenario id。相同 task、split、index 和 seed 会产生相同 reset seed；正式报告前仍需与选定的 RoboCasa 原生 evaluator 对齐 scenario sampling。

`task_set` 决定 task name，`split` 改变 kitchen layout 和 object instance sampling，不会再次过滤 task name。比较两个 split 时应显式固定同一组 `task_names`；仅设置 `max_tasks` 会依赖当前 `TASK_SET_REGISTRY` 的顺序。

## Outputs

```text
runs/robocasa365_<mode>_smoke/
├── episodes.jsonl
├── resolved_config.json
├── summary.json
└── traces/
    └── robocasa-<split>-<task>-<index>/
        ├── result.json
        └── trace.jsonl
```

`resolved_config.json` 记录 task/split/seed、component class、Pipeline/Runtime 限制、RoboCasa/robosuite/OmniRoboAgent commit 与 dirty 状态、Python/package version 和 policy server health metadata。`summary.json` 包含 overall/per-task success rate、macro average、success/failure/exception、planner calls、replans、action chunks、environment steps、invalid actions、latency 和 termination reasons。

## Verified Atomic GR00T Evaluation

使用 `groot_atomic_intern_moe_v1/checkpoint-240000`，固定 `task_set=atomic_seen`、`episode_index=0`、`seed=0`，并在两个 split 中显式使用同一组 5 个 task：

- `CloseBlenderLid`
- `CloseFridge`
- `CloseToasterOvenDoor`
- `CoffeeSetupMug`
- `NavigateKitchen`

| Mode | Split | Success | Environment steps | Action chunks | Exceptions | Invalid actions |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| GR00T remote | `pretrain` | 3 / 5 | 1546 | 99 | 0 | 0 |
| GR00T remote | `target` | 2 / 5 | 1554 | 99 | 0 | 0 |
| GR00T local | `pretrain` | 2 / 5 | 1642 | 105 | 0 | 0 |
| GR00T local | `target` | 3 / 5 | 1419 | 91 | 0 | 0 |

四组评测使用相同的 RoboCasa commit `9a3a786`、robosuite commit `aaa8b9b`、task 顺序和 reset seed。remote 模式只加载一次 server 并复用于两个 split；local 模式在 simulator 进程内加载相同 checkpoint。`CloseFridge` 和 `NavigateKitchen` 在四组中均成功；`CloseBlenderLid` 和 `CoffeeSetupMug` 均运行到 episode horizon。

这些结果用于验证 split、transport 和闭环执行，不是正式 policy quality baseline。固定 seed 当前只固定 simulator reset；diffusion policy 未固定推理 RNG，因此 remote/local 的 success、chunk 和 step 数不要求逐次一致。OpenPI real-checkpoint smoke 仍待完成。

## Verified Composite Agent Evaluation

Composite matrix 使用相同 atomic checkpoint、`Qwen3.5-9B` Planner、`episode_index=0` 和 `seed=0`。每组固定 5 个 task、每 task 1 episode：

- `composite_seen`：`DeliverStraw`、`GetToastedBread`、`KettleBoiling`、`LoadDishwasher`、`PackIdenticalLunches`
- `composite_unseen`：`ArrangeBreadBasket`、`ArrangeTea`、`BreadSelection`、`CategorizeCondiments`、`CuttingToolSelection`

| Mode | Task set | Split | Success | Environment steps | Action chunks | Exceptions | Invalid/retry steps | Termination |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| GR00T remote | `composite_seen` | `pretrain` | 0 / 5 | 8500 | 533 | 0 | 6 | 5 environment done |
| GR00T remote | `composite_seen` | `target` | 0 / 5 | 8140 | 510 | 0 | 5 | 4 environment done, 1 retry limit |
| GR00T remote | `composite_unseen` | `pretrain` | 0 / 5 | 7600 | 477 | 0 | 1 | 5 environment done |
| GR00T remote | `composite_unseen` | `target` | 0 / 5 | 6228 | 391 | 0 | 7 | 4 environment done, 1 retry limit |
| GR00T local | `composite_seen` | `pretrain` | 1 / 5 | 7326 | 459 | 0 | 11 | 3 environment done, 1 retry limit, 1 success |
| GR00T local | `composite_seen` | `target` | 0 / 5 | 7052 | 442 | 0 | 6 | 4 environment done, 1 retry limit |
| GR00T local | `composite_unseen` | `pretrain` | 0 / 5 | 7172 | 450 | 0 | 4 | 4 environment done, 1 retry limit |
| GR00T local | `composite_unseen` | `target` | 0 / 5 | 6228 | 391 | 0 | 7 | 4 environment done, 1 retry limit |

唯一成功 episode 是 local `KettleBoiling / pretrain`，RoboCasa 在 506 environment steps、32 action chunks 时返回 success。40 个 episode 均未出现 simulator、server、request schema 或 action shape exception。

Composite 表中的 `invalid_actions` 属于旧 Planner contract，包含没有执行 Environment action 的 `continue_subtask` mismatch；不能解释为 VLA 输出了非法 action array。新 trace 改为记录 `previous_status`、`next_status`、`transition_reason`、verifier evidence 和 `recovery_action`。

该 matrix 运行时还没有独立视觉 verifier、视觉历史和新的 proposal contract，因此结果验证的是旧 Agent + atomic VLA case，不应单独归因于 GR00T checkpoint，也不是正式 50-rollout quality baseline。Remote/local 的 task 顺序、reset seed、RoboCasa commit `9a3a786` 和 robosuite commit `aaa8b9b` 已核对一致。

## Remaining Work Toward The Target System

目标状态不是“能启动 simulator 并产生 action”，而是一个可复现、可比较、可诊断的 RoboCasa long-horizon Agent + VLA evaluation system：Agent 能稳定分解 composite task、判断 subtask 是否完成、失败后恢复；Evaluator 能按官方 scenario 运行并支持大规模可恢复 rollout；不同 policy transport 使用同一 metric 口径。

建议按以下优先级推进：

| Priority | Gap | Current limitation | Completion criterion |
| --- | --- | --- | --- |
| P0 | Official evaluation alignment | 正式 task-set scope 尚未固定；`episode_index` 只是 `seed` offset；没有官方随机 50-scenario manifest；Runtime limit 按 action chunk 计数而 RoboCasa horizon 按 low-level step 计数 | 明确正式 task sets，对齐官方 reset state、scenario identity、horizon 和 aggregation；相同 manifest 可跨机器、跨 worker 复现，并从 low-level horizon 派生或校验 chunk budget |
| P0 | Independent subtask verifier | `SubtaskVerifier` 与 state graph 已实现并进入 composite config，但迁移后的真实 checkpoint smoke 未运行 | 用固定 episode 验证 visual status/evidence、误判率、LLM latency 和 task-success priority |
| P0 | Atomic decomposition and recovery | retry/replan/fallback/abort 和 loop detection 已实现；Planner 仍可能提出混合 Navigation/manipulation 的 subtask | 一个 subtask 对应一个 macro skill 和明确对象关系；在真实 smoke 中验证 recovery 分支 |
| P0 | Error and metric taxonomy | Planner contract error 被统计到 `invalid_actions` | 分开记录 `planner_errors`、`policy_errors`、`environment_errors`、contract retries 和对应 termination reason |
| P0 | Skill contract consistency | GR00T backend 只校验 `skill_id` 类型，不验证 skill/catalog/ID 一致性 | 在调用 policy 前验证 Planner skill、RunConfig catalog 和 trusted ID mapping 一致 |
| P1 | Experiment reproducibility | 当前 checkpoint 依赖未发布的 `model_moe_v1` 和 data config；12 组 atomic/composite matrix 的临时 RunConfig 未纳入版本控制；`resolved_config.json` 只保存部分参数；policy RNG 未固定 | 固定可获取 source、environment lock、checkpoint digest 和 policy seed；提交 experiment manifest/RunConfig，并保存完整 resolved AgentConfig/RunConfig、Planner prompt/schema、skill map 和 camera 参数 |
| P1 | Bounded memory and diagnostics | `InMemoryMemory` 保留完整图像/action event，长 episode RSS 持续增长 | Memory 只保存摘要或 artifact reference；按 episode 清理，并可选保存首帧、关键帧或视频 |
| P1 | Resumable evaluation | Evaluator 和 Runtime 启动时会重建 `episodes.jsonl` / trace，长跑中断后不能原地续跑 | 支持 run manifest、跳过已完成 episode，并对 episode、trace/result、summary 和 resolved config 做 atomic write 与一致性检查 |
| P2 | Formal-scale evaluation | 当前只跑每组 5 tasks、每 task 1 episode，且串行单环境 | 完成 task set x split x policy 的正式 50-rollout protocol、置信区间和可控并行 worker/GPU 调度 |
| P2 | Additional policy validation | OpenPI 只有 client/server/schema 和 fake protocol test | 使用真实 OpenPI checkpoint 完成与 GR00T 相同 scenario 的 smoke 和 matrix |

其中 P0 是正式比较模型之前的前置条件。P1 决定实验是否可以被其他机器复现并稳定运行数小时；P2 才是扩大任务和 rollout 数量。Async runtime、ROS2、semantic/spatial memory 和真机 integration 属于更后面的平台目标，不应先于 evaluation correctness 实施。
