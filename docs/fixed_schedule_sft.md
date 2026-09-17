# RoboTwin full-plan 调度数据

## 完整计划与显式进度

新版不再要求 Qwen 暗中记住每段预算。每条 episode 的第一次模型调用接收完整任务、available skills 和初始 head/left/right 三视角，一次输出全部子任务；每项包含 `subtask_index`、`skill`、`instruction`、`success_condition` 和 `chunk_budget`。Runtime 缓存这份模型输出。为对齐 Omni 原版的调用形态，每个子任务开始前仍调用一次多模态 Planner；它接收相同完整计划、显式进度、近期历史和当前三视角，只输出当前该执行的一项。Runtime 不会静默按索引切换。

每个 action chunk 后的 verifier 输入均包含同一份 `execution_plan`，以及 `completed_subtask_count`、`completed_subtask_indices`、`current_subtask_index`、`current_chunk`、`current_chunk_budget` 和 `total_subtasks`。模型按显式计数输出 `in_progress` 或 `completed`。该完成状态只负责计划切换，不等同于环境成功。

构造命令：

```bash
PYTHONPATH=src taskset -c 0-3 .venv/bin/python \
  scripts/build_fixed_schedule_sft.py \
  --source ../clawvla/runs/data/robotwin_omni_task_skill_subtask_2486_20260827 \
  --output runs/data/omni_full_plan_select_schedule_sft_2486_20260913
```

`--trust-reused-images` 只允许指向已有 `audit.json` 状态为 `PASS` 的图片目录；它跳过构造期间重复解码，最终数据仍由 `audit_full_plan_schedule_sft.py` 检查全部引用。

这组数据让 Qwen 学习三件事：从初始观察生成完整计划；每次结合最新观察和历史
选择当前唯一计划项；根据当前子任务已经执行的 chunk 数，在固定最长次数处输出
`completed` 并切换到下一段。
这里的 `completed` 只表示预定执行次数结束，不代表视觉验证成功，也不能代替
环境的最终成功判断。

## 最长预算

源数据为
`../clawvla/runs/data/robotwin_omni_task_skill_subtask_2486_20260827`，包含
50 类任务、2486 条 episode、11 类 skill 和 7645 条合并子任务。

每个原始子任务先计算 `ceil(segment_frames / 32)`。随后按照“任务名 + skill
序列”划分计划分支，对同一分支、同一子任务位置取全部 episode 的最大值。
`dump_bin_bigbin`、`place_bread_basket` 和 `put_bottles_dustbin` 存在多种
计划分支，分别计算，不能混用。最终共有 54 套固定最长 schedule。

例如：

```text
dump_bin_bigbin handover 分支：min [3,5,3] -> fixed max [4,7,3]
shake_bottle：                  min [3,1,4,1] -> fixed max [4,2,6,1]
open_microwave：                min [3,11] -> fixed max [3,44]
```

完整映射保存在 `schedule_catalog.json`。Runtime 内部仍持有该列表以展开 teacher
轨迹，但它不进入 Qwen 消息。

## Qwen 实际输入

Planner 和 Verifier 的样本由真实的
`SyncRuntime -> SkillExecutionPipeline -> DefaultAgent` 回放产生。Qwen 可以看到：

- 当前任务和子任务；
- 当前 plan 中的子任务编号与子任务总数；
- 当前子任务已经执行的 `chunks_executed`；
- 三相机当前图像、历史事件和工作记忆；
- 可选 skill 列表及可观察的完成目标。

Qwen 可以看到由它在首轮计划中生成的 `chunk_budget`，随后每次 Planner 选择和
Verifier 调用都会接收同一计划及当前进度。它看不到 episode 编号和 seed。
Planner 每个子任务调用一次，Verifier 每执行一个 chunk 调用一次。

## 图片与额外 chunk

三相机顺序为 head、left、right。专家范围内使用：

```text
min(segment_start + chunks_executed * 32, segment_end_exclusive - 1)
```

当某条较短轨迹被扩展到同分支最大预算时，超出其专家帧数的额外 chunk 保持在
当前子任务末帧，不会偷看下一条子任务。图片来自既有专家 HDF5，并沿用已核对的
RGB 修复。全量数据通过符号链接复用上一版 69939 张已审计图片，避免重复
编码和占用磁盘；模型收到的图片路径仍全部可读。

这些图片不是 π0.5 在额外 chunk 下重新执行得到的画面。固定最长预算是否会破坏
动作需要通过真实 RoboTwin 对照实验验证；目前 `shake_bottle` 和
`shake_bottle_horizontally` 的单例对照均在最大预算下成功。

## 生成与输出

最终数据：

| 内容 | 数量 |
| --- | ---: |
| episode | 2486 |
| 训练 / 验证 episode | 2236 / 250 |
| 计划分支 | 54 |
| 首轮完整计划样本 | 2486 |
| 逐子任务 Planner 选择样本 | 7645 |
| Verifier 样本 | 24897 |
| 总样本 | 35028 |
| 唯一图片 | 69939 |

主要文件：

| 文件 | 用途 |
| --- | --- |
| `train.jsonl` / `val.jsonl` | 可训练的 ShareGPT 多模态数据 |
| `schedule_catalog.json` | 54 套计划分支的原始最小值和固定最大值 |
| `requests.jsonl` | Omni 在 LLM backend 边界产生的完整请求和标准答案 |
| `episodes.jsonl` | 每条 episode 的原始预算、固定预算、执行记录和来源哈希 |
| `images.jsonl` / `images/` | 图片来源索引与复用图片目录 |
| `summary.json` / `audit.json` | 数量统计和独立全量审计结果 |

独立审计命令：

```bash
.venv/bin/python scripts/audit_full_plan_schedule_sft.py \
  --dataset runs/data/omni_full_plan_select_schedule_sft_2486_20260913
```

审计逐条重算 35028 个标签，检查完整 plan 顺序、每段 Planner 选择、最大预算映射、
进度连续性、训练/验证隔离和所有图片引用，并确认模型消息不包含 episode 编号或
seed。当前结果为 `PASS`。

## 训练与最终模型

正式调度器从 `Qwen3.5-9B` 基座创建 rank-64 LoRA。训练使用 FlashAttention 2、
DeepSpeed ZeRO-3，视觉塔与多模态投影器不冻结，验证间隔为 2000 step。配置与
启动入口：

```text
configs/sft/omni_full_plan_select_qwen35_9b_3gpu.yaml
scripts/launch_omni_full_plan_select_qwen35_9b_3gpu.sh
```

RoboTwin 正式评测使用 `checkpoint-3500`。checkpoint 身份和 adapter SHA-256
记录在 [`checkpoints/manifest.json`](../checkpoints/manifest.json)，权重本身不进入
Git。
