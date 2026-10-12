# RoboSynChallenge 评测结果

2026-10-12 完成十项任务 × 每任务 100 回合：**412/1000 成功，41.2%**；
588 个正常失败，零回合执行或 observability 异常。

| Task | 成功 / 回合 | 成功率 |
| --- | ---: | ---: |
| click_bell | 54 / 100 | 54% |
| drawer_open_place | 4 / 100 | 4% |
| handle_basket | 18 / 100 | 18% |
| item_assembly | 60 / 100 | 60% |
| items_handover | 4 / 100 | 4% |
| manipulate_pipette | 56 / 100 | 56% |
| mixer_operating | 66 / 100 | 66% |
| sample_loading | 1 / 100 | 1% |
| table_rearrangement | 98 / 100 | 98% |
| water_pouring | 51 / 100 | 51% |

## 协议和源码身份

使用 `DefaultAgent`、Qwen3.5-9B 视觉 `SubtaskSkillPlanner` / `SubtaskVerifier`、
`TieredMemory`、`SkillExecutionPipeline`，以及各任务公开 ACT checkpoint 的
`RoboSynPolicyBackend`。ACT 不接收语言条件，没有策略训练或专家控制动作。
每个原生动作后读取环境反馈并进入验证；视觉语义检查间隔 64 个 chunks，
成功信号为 `is_task_success() and not truncated`。

设置为 `random`、显式未过滤 seeds 0–99；reset 协议为
`warmup_get_obs_get_info_v2`。主办方原生 evaluator 使用专家可行性筛选，因此
这组成绩是本框架评测结果，不是论文成绩的精确复现。smoke、baseline 和其他
reset 协议的结果不计入这 1000 回合。

上游固定为 RoboSynChallenge `8818c82df5fa2522809b8105e7018950dcc9a9a8`、
EmbodiChain `89c14da8d0221dc4ee2a4a3e0ba1078b16d447bd`。各 ACT 权重 revision
见 `configs/runs/robosynchallenge_act_random_manifest.json`，运行时记录文件 SHA256。

历史评测在基于 OmniRoboAgent commit
`78686193e3fa41231677e064a84d46c6b62cd807` 的工作区，加上本次 RoboSyn 新增源码
完成；该基底 commit 本身不包含 adapter。原运行记录了 dirty 状态、新增源码
SHA256、配置和权重身份。本 PR 改为基于最新 `origin/master` 的 `c01a6bd` 集成，
仅做 CPU 验证，**未在该新基底重跑 1000 回合**，不能把历史成绩标为该分支的新
GPU 测试结果。安装和运行方式见 [接入文档](robosynchallenge.md)。

新基底上的 CPU 验证：RoboSyn 37 项测试通过，完整测试集 182 passed / 1 skipped，
Ruff 和相关 mypy 检查通过。迁移的 RoboSyn 源码、配置、测试和 runtime lock
共 13 个文件与历史工作区 SHA256 一致；该校验不替代新基底的 GPU 矩阵运行。

## 审计和产物

历史输出目录为 `runs/robosynchallenge/act-visual-random-reset-v2/`；模型、缓存及
生成的运行目录不随 PR 提交。保留原产物时，可核对：

- 每任务 seeds 0–99 唯一且完整；1000 次原生成功信号与统计一致。
- 根 `summary.json`、逐任务 `metadata.json` / `episodes.jsonl` 记录统计与身份。
- 每回合的 `episode.json`、`trace.jsonl`、`agent_trace.jsonl`、`episode.mp4` 和
  `artifact_manifest.json` 均存在、非空，无 observability errors。
- 录像每 Runtime step 一帧，帧数为 Runtime steps + 1；reverify 可以不执行原生
  动作，因此录像帧数不必等于原生动作数 + 1。
- 中断尝试保留诊断文件，只取完成的最终尝试；六个未产生最终结果的尝试不计入
  1000 个有效回合及成功率。
- `gpu_allocation.json`、`provenance.json` 和 `completion-audit.json` 保存调度、
  源码身份、全量核对及缓存续跑证据；续跑前后主要回合文件联合 SHA256 相同。

## 已知退出故障

`item_assembly` 最后一个回合保存成功后，在 native garbage collection 阶段
SIGSEGV，子进程返回 `-11`；具体原生析构对象未定位。该任务的 100 回合及
artifacts 全部通过审计。原日志和 `summary-before-teardown-resume.json` 保留，
原退出故障没有改写成 0，也未计作策略失败。

所有队列自然结束后，同参数严格缓存 `--resume` 跳过全部 rollout，验证和
聚合已有结果后退出 0；该次缓存验证十项任务均退出 0、`complete=true`，统计和
有效回合文件保持不变。这是后续缓存验证的退出结果，**不表示原生清理故障已经
修复**。
