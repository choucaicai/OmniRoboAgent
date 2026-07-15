# RoboCasa365 Evaluation And Agent-VLA Case

Status: `IN_PROGRESS`

## Goal

以 evaluation 为主线接入 RoboCasa365，形成一个高层 Agent 规划 skill、VLA 执行连续 action chunk、RoboCasa 返回权威任务成功信号的完整 case。

第一阶段先运行固定的 `1 task x 1 episode` smoke，再用同一组 5 个 task 验证 `pretrain` / `target` split 和 GR00T remote/local 两种执行方式；随后在 `composite_seen` / `composite_unseen` 上验证高层 Agent 分解任务并调用 atomic GR00T skill。Evaluator 的配置和输出需要能够扩展到每个任务 50 次 rollout 的正式评测协议。

## Confirmed Decisions

- RoboCasa 官方仓库作为固定 commit 的 submodule 放在 `benchmarks/RoboCasa/`，不复制第三方源码到本项目 package。
- 本机开发复用 `/home/zzz/vla_code/robocasa/robocasa/models/assets`，通过本地软链连接到 submodule 的 `robocasa/models/assets`；软链和 23 GB assets 不提交。
- 用户文档必须要求其他用户按照 RoboCasa 官方 Installation 执行 `setup_macros` 和 `download_kitchen_assets`，本机软链只作为可选开发方式。
- 使用一个具体的 `RoboCasa365Evaluator`。第一版不新增通用 Evaluator base class 或 benchmark registry。
- Evaluator 同时接受官方 `task_set` 和 `split`：`task_set` 使用 RoboCasa `TASK_SET_REGISTRY`，`split` 只接受 `pretrain` 或 `target`。
- `task_names`、`max_tasks`、`episodes_per_task`、`episode_indices` 和 `seed` 用于固定 smoke 和复现实验，不改变官方 task set 定义。
- 第一轮 smoke 使用配置解析后的第一个任务和固定 reset seed；实际 task name、episode ordinal 和 seed 必须写入结果。当前 ordinal 不是官方 dataset scenario id。
- split 验证显式固定 `atomic_seen` 的同一组 5 个 task、`episode_index=0` 和 `seed=0`，避免把 registry 顺序差异误认为 split 差异。
- 同一个 Evaluator 支持 GR00T remote server、OpenPI remote server 和本地 in-process policy。AgentConfig 通过最小 `SkillBackendRegistry` 的稳定名称选择实现，也保留 `class_path` 作为自定义 fallback；Evaluator 内不建立 transport 分支。
- `SkillBackendRegistry` 首批内置 `groot_remote`、`openpi_remote` 和 `local`，允许代码显式注册其他 backend，但不做自动扫描、entry-point discovery 或 plugin manager。
- 项目提供 GR00T 和 OpenPI 的独立 server 启动入口，但 Evaluator 不负责启动、停止或监控 GPU model server，只负责 healthcheck 和客户端生命周期。
- RoboCasa simulator、GR00T server、OpenPI server 可以使用独立 Conda 环境；所有环境使用同一份 OmniRoboAgent checkout 的 editable install，不复制项目源码。
- 高层 Agent 每次产生一个 skill 和具体 subtask。VLA 可以连续执行多个 action chunks，Pipeline 根据配置的检查间隔决定继续当前 skill 或重新规划。
- composite task 保持为 Environment reset 和 benchmark success 的对象；LLM Planner 从配置提供的 atomic macro skill catalog 中选择 `skill`、带对象语义的 `subtask` 和 execution status，可信本地映射补充 `skill_id`，GR00T backend 不把 composite task name 当成 atomic skill。
- atomic 路径继续要求 `skill == task_name`。只有 Planner 显式提供合法非负 `skill_id` 时，GR00T request 才允许 skill 与 benchmark task name 不同。
- 每个 action chunk 后都进入 verifier。benchmark 的 `success` 是 task success 的 ground truth，Planner 不能自行宣告 benchmark 成功。
- 第一版保持同步、单环境执行；多进程、多 GPU 调度和完整 365-task 正式跑分不属于首个 smoke。

## Open Questions

- OpenPI 使用 `pi0_robocasa_pretrain_human300`、port `8000`，但本机尚无可用 checkpoint，真实 smoke 待完成。
- 当前 composite matrix 是每组 `5 tasks x 1 episode` 的 infrastructure evaluation；是否执行每任务 50 rollouts，以及如何与官方 scenario sampling 对齐，尚未确认。

GR00T remote/local 验证已固定 `groot_atomic_intern_moe_v1/checkpoint-240000`、`gr00t.model_moe_v1.policy.Gr00tPolicy`、`panda_omron`、`new_embodiment` 和 remote port `5555`。5-task split matrix 共完成 20 个 episode，未出现 exception 或 invalid action。

Composite Agent matrix 固定 `Qwen3.5-9B`、11 个 macro skills、`episode_index=0` 和 `seed=0`，在 `composite_seen` / `composite_unseen`、`pretrain` / `target`、GR00T remote/local 上共完成 40 个 episode。8 组均为 0 exception；local `KettleBoiling / pretrain` 成功 1 次，另外 33 个 episode 由 authoritative environment horizon 终止，6 个因连续 Planner output mismatch 达到 retry limit。

该 GR00T checkpoint 依赖本机 Isaac-GR00T checkout 中未提交的 `model_moe_v1` / `data_config_mem_groot.py` 扩展；upstream base commit `9d7d7a9` 不足以单独复现。框架 server 不依赖本机 `robot.py` patch，但正式共享结果前仍需固定可获取的 policy source。

## Architecture

```text
RunConfig
  -> RoboCasa365Evaluator
       -> resolve task_set + split + smoke overrides
       -> for each task / episode
            -> SyncRuntime
                 -> SkillExecutionPipeline
                      -> Agent Planner: skill + skill_id + subtask
                      -> selected SkillBackend
                           -> GR00T remote client
                           -> OpenPI remote client
                           -> local in-process policy
                      -> RoboCasaEnvironment.execute(action chunk)
                      -> EnvironmentVerifier(authoritative success)
       -> episodes.jsonl / summary.json / resolved_config.json
```

### Ownership

| Component | Planned location | Responsibility |
| --- | --- | --- |
| RoboCasa submodule | `benchmarks/RoboCasa/` | 官方 task、simulator、assets schema 和 registry |
| `RoboCasaEnvironment` | `src/omniroboagent/environments/benchmarks/robocasa/` | task reset、observation、action chunk 执行、success 和 simulator close |
| `RoboCasa365Evaluator` | `src/omniroboagent/evals/benchmarks/robocasa/` | task/episode 遍历、官方参数解析、结果保存和指标聚合 |
| `SubtaskSkillPlanner` | `src/omniroboagent/agent_core/planners/subtask_skill.py` | composite task 的 macro skill、subtask、execution status 和可信 skill ID 映射 |
| `SkillExecutionPipeline` | `src/omniroboagent/pipelines/` | active skill 生命周期、chunk 执行、检查间隔、replan 和终止语义 |
| GR00T remote backend | `src/omniroboagent/backends/skills/` | GR00T client、schema 转换、healthcheck、timeout 和 close |
| OpenPI remote backend | `src/omniroboagent/backends/skills/openpi.py` | 复用并补齐现有 OpenPI WebSocket client 的 RoboCasa schema 验证 |
| Local policy backend | `src/omniroboagent/backends/skills/` | 通过配置加载 in-process policy 并返回 action chunk |
| Skill backend registry | `src/omniroboagent/backends/skills/registry.py` | 将稳定配置名称映射到 backend class，并保留 `class_path` fallback |
| Server entrypoints | `scripts/` | 分别加载 GR00T/OpenPI checkpoint 并启动兼容服务，不由 Runtime 管理 |

`RoboCasaEnvironment` 不 import GR00T 或 OpenPI。三个 policy backend 不 import Evaluator。`SyncRuntime` 不增加 RoboCasa、RPC 或模型类型分支。

## Evaluation Contract

建议的 Evaluator 配置字段：

| Field | Meaning |
| --- | --- |
| `task_set` | RoboCasa `TASK_SET_REGISTRY` key，例如 `atomic_seen` |
| `split` | 官方场景/物体 split：`pretrain` 或 `target` |
| `task_names` | 可选显式任务列表；设置后仍需验证任务属于 registry |
| `max_tasks` | 可选任务数上限；smoke 使用 `1` |
| `episodes_per_task` | 每任务 rollout 数；smoke 使用 `1`，正式协议使用 `50` |
| `episode_indices` | 可选唯一非负 ordinal，当前作为 reset seed offset |
| `seed` | environment reset 的基准 seed |
| `output_dir` | episode traces、resolved config 和 summary 根目录 |

首个 smoke RunConfig 目标形态：

```yaml
benchmark:
  class_path: omniroboagent.evals.benchmarks.robocasa.RoboCasa365Evaluator
  init_args:
    task_set: atomic_seen
    split: target
    max_tasks: 1
    episodes_per_task: 1
    episode_indices: [0]
    seed: 0
    output_dir: runs/robocasa365_smoke
```

AgentConfig 通过 `skill_backend.name` 切换三种内置执行模式，也可以继续使用 `skill_backend.class_path`。Evaluator、Environment、Pipeline 和 Runtime 配置保持一致，确保三个 backend 使用相同 task、split、reset seed 和 metric 口径。

第一阶段不实现 video recorder；需要视频时必须另行增加不改变 success metric 的 recorder contract。

## Runtime Semantics

- 一次 Runtime `step` 对应一次 VLA action chunk，不等同于一个 simulator low-level step。
- Environment 在 action chunk 内逐步执行，并在 task success、environment termination、配置的 `execute_steps` 或 chunk 结束时停止。
- Environment result 至少返回 `observation`、`task_success`、`done`、`executed_steps` 和可序列化的 `env_info` 摘要；Verifier 将 `done` 转成 `environment_done`。
- Pipeline 在每个 chunk 后调用 Verifier，并累计 `action_chunks`、`environment_steps`、active skill chunk 数和 planner replans。
- Planner 检查间隔和每个 skill 的最大 chunk budget 由 Pipeline 配置，不由 Evaluator 或 VLA server 决定。
- 远程和本地 backend 接收相同逻辑输入：当前 observation、skill、subtask、planner output 和必要历史摘要；各 backend 内部完成模型特定字段映射。
- action shape、dtype、范围和 chunk 长度由对应 backend 与 `RoboCasaEnvironment` 在使用点严格校验。

## Output Contract

每次 evaluation 至少保存：

- task/evaluation 参数、component class 与 Pipeline/Runtime 限制摘要、RoboCasa commit、OmniRoboAgent commit、Python 和关键 package 版本；当前不逐字复制原始 AgentConfig/RunConfig YAML；
- policy mode、checkpoint/config identity、server metadata 或本地模型 metadata；
- `task_set`、`split`、resolved task names、episode ordinals 和 reset seeds；
- 每个 episode 的 success、termination reason、action chunks、environment steps、planner calls、replans、invalid actions 和 latency；
- 每任务 success rate、总体 macro-average success rate、失败数和异常数；
- 不包含大数组和敏感配置的 JSONL trace。

正式结果必须区分 evaluation infrastructure smoke 和 policy quality。只要完整闭环、指标和 artifact 正确生成，smoke 的 task success 可以为 `false`。

## Scope

- 固定 RoboCasa submodule 和本地 assets 软链流程。
- RoboCasa continuous-control Environment adapter。
- 具体 `RoboCasa365Evaluator` 和官方 task set/split 参数。
- Agent + skill-conditioned VLA 的 chunk-level Pipeline。
- OpenAI-compatible LLM subtask planner、可配置 atomic skill catalog，以及 composite task 到 atomic GR00T skill 的 request contract。
- GR00T remote、OpenPI remote 和 local in-process SkillBackend。
- GR00T/OpenPI server 启动入口、healthcheck 和 metadata。
- 单任务单 episode smoke config、unit/integration tests、结果 artifacts 和用户文档。

## Out of Scope

- VLA 训练、微调或 checkpoint 发布。
- 首阶段执行全部 365 tasks 或完整 50-rollout 正式跑分。
- async、多环境并行、worker scheduler 或跨节点资源管理。
- 自动启动和关闭远程 GPU model server。
- 修改 RoboCasa、GR00T 或 OpenPI 第三方 submodule/source。
- 在 Core 中建立统一 Action class、benchmark registry、自动 plugin discovery 或通用 Evaluator hierarchy。

## Tasks

1. [ ] 发布完整兼容矩阵：RoboCasa、robosuite 和 OpenPI client protocol 已固定；GR00T custom source、Python/CUDA environment 和 OpenPI checkpoint 仍待固定。
2. [x] 添加 `benchmarks/RoboCasa` submodule，并增加只操作本地文件的 assets link 脚本；脚本不删除或覆盖已有内容。
3. [x] 建立独立 RoboCasa 环境，验证 assets、headless render、官方 task reset 和 model action step。
4. [x] 实现 `RoboCasaEnvironment`，覆盖 task/split reset、固定 seed、observation、连续 action chunk、early success、termination 和 close。
5. [x] 实现 `RoboCasa365Evaluator`，解析 `task_set` / `split` / smoke overrides，逐 episode 调用 Runtime，并保存 resolved config、episode result 和 summary。
6. [x] 实现最小 `SkillExecutionPipeline`，维护 active skill、subtask、chunk budget、planner check interval、verify 和 replan。
7. [x] 定义并测试 RoboCasa policy input/action contract，明确 camera/state/language/skill 的 key、shape、dtype 和 batch 语义。
8. [x] 实现 GR00T remote SkillBackend 和独立 server entrypoint，验证 healthcheck、metadata、timeout、action chunk schema 和 client close。
9. [x] 实现 OpenPI RoboCasa schema backend 和 server entrypoint，保持官方 WebSocket protocol 兼容。
10. [x] 实现 local in-process SkillBackend 和 GR00T lazy adapter，不在 Core import GR00T/OpenPI。
11. [x] 实现最小 `SkillBackendRegistry` 和配置加载：内置三个稳定名称，支持显式注册其他 backend，并保留直接 `class_path`。
12. [x] 为三个 policy mode 分别提供 AgentConfig 和固定 `1 task x 1 episode` RunConfig。
13. [x] 补充 fake policy/environment unit tests，覆盖成功、invalid action chunk、server timeout、local exception、step limit 和资源释放。
14. [x] 完成 GR00T remote/local 单任务 smoke 和相同 5-task 的 pretrain/target matrix。
15. [ ] 确认正式 task-set scope，并与 RoboCasa 官方 evaluator 对齐随机 50-scenario manifest、reset/scenario identity、low-level episode horizon 和 success-rate aggregation。
16. [x] 更新 `README.md` 和 `docs/`：官方安装/assets、registry、三个 policy mode、server、smoke、输出和 troubleshooting。
17. [x] 更新 architecture、TODO 和 change record，并运行最终 pytest、Ruff、mypy、配置实例化、Markdown link 和 `git diff --check`。
18. [x] 实现可配置的 LLM subtask planner，输出 atomic macro `skill`、可信本地 `skill_id`、具体 `subtask` 和 execution status。
19. [x] 允许 `RoboCasaEnvironment` 通过 RunConfig 暴露 composite evaluation 使用的 atomic skill catalog，同时保持 atomic 默认行为。
20. [x] 扩展 GR00T local/remote request schema：显式 `skill_id` 时分别发送 composite `task` 和 atomic `skill`；缺少 `skill_id` 时保留严格 task-skill equality。
21. [x] 对 `DeliverStraw` 和 `ArrangeBreadBasket` 完成 local/remote one-action probe，确认无 task mapping、schema 或 action shape 错误。
22. [x] 在 `composite_seen` / `composite_unseen` 的同一组 5 个 task 上完成 `pretrain` / `target`、GR00T remote/local 评测并保存 artifacts。
23. [ ] 增加独立 subtask visual verifier，使用 current frame、有限 visual history 和 execution history 判断当前 subtask done/not-done，不让 Planner 同时承担规划和完成判定。
24. [ ] 收紧 composite decomposition 和 recovery contract：一个 subtask 对应一个 macro skill 和明确对象关系，Navigation 与 manipulation 分开；为 active execution 增加稳定 identity，避免只靠 wording equality；支持 skill timeout、retry 和 fallback。
25. [ ] 拆分错误和指标：分别记录 Planner schema/semantic error、policy inference/schema error、Environment execution error、contract retry 和 benchmark failure，不再用 `invalid_actions` 混合表达。
26. [ ] 在 policy 调用前验证 Planner skill、RunConfig `available_skills`、trusted skill ID mapping 和 request 中的 skill/ID 一致性。
27. [ ] 限制长 episode memory：InMemoryMemory 不保留完整图像/action event，按 episode 清理 working memory，并增加首帧、关键帧或可选 video artifact 用于诊断。
28. [ ] 为 Evaluator/Runtime 增加 resumable run manifest、已完成 episode skip、atomic artifact write 和 consistency check，避免启动时无条件清空已有 episode、trace、result、summary 或 resolved config。
29. [ ] 在 task 15 的官方 scenario 对齐后，执行 task set x split x policy 的每 task 50-rollout protocol；再增加可控 worker/GPU 并行、policy RNG 和置信区间统计。
30. [ ] 将正式 experiment manifest/RunConfig 纳入版本控制，并在结果中保存完整 resolved AgentConfig/RunConfig、Planner prompt/schema、skill map、camera 参数、source commit、checkpoint digest 和 dependency environment。
31. [ ] 明确 RoboCasa low-level horizon 与 Runtime action-chunk `max_steps` 的换算规则；对 full 和 receding-horizon mode 派生或校验不会提前截断的 budget。
32. [ ] 使用真实 OpenPI checkpoint 完成 server、RoboCasa simulator 和 receding-horizon action execution smoke，再在固定 scenario manifest 上与 GR00T 使用同一指标口径评测。

## Acceptance Criteria

- `benchmarks/RoboCasa` 固定到明确 commit；主仓库和 submodule 都不包含下载的 assets、dataset、checkpoint 或运行输出。
- 本机 assets link source 为 `/home/zzz/vla_code/robocasa/robocasa/models/assets`；脚本只为缺失 entry 创建 symlink，已有目录只补不覆盖的 child links，不删除或替换已有内容。
- 新用户文档不依赖本机路径，并明确执行 RoboCasa 官方 `setup_macros` 与 `download_kitchen_assets`。
- RunConfig 可以独立设置官方 `task_set` 和 `split`，非法 key、非法 split 和不属于 task set 的显式 task 会得到清晰错误。
- 一个 smoke config 可以稳定解析为同一 task、episode ordinal 和 reset seed，并将解析结果写入输出。
- 同一个 Evaluator 和 Environment 可以只替换 AgentConfig，在 GR00T remote、OpenPI remote 和 local 三种模式之间切换。
- `skill_backend.name` 可以选择三个内置 backend；未知名称报清晰错误，自定义 `class_path` 配置继续可用。
- 三种模式都能完成 healthcheck、一次 action chunk 推理、环境执行、Verifier、明确终止和资源释放。
- authoritative RoboCasa success signal 是唯一 benchmark success ground truth。
- action chunk 在 shape、dtype、范围或长度不合法时显式失败，不静默裁剪为看似有效的动作。
- summary 至少包含 per-task 和 overall success rate、episode 数、异常数、action chunks、environment steps、planner calls/replans、latency 和 termination reasons。
- 默认快速测试不加载 simulator 或模型；真实 RoboCasa/server smoke 使用单独 marker 或命令。
- 现有 EB-ALFRED config、tests 和公开 imports 不回归。
- composite Planner 只能选择配置中的 macro skill，必须返回对应 `skill_id` 和非空 `subtask`；非法或不一致输出在调用 VLA 前显式失败。
- composite local/remote 使用同一 task name、split、episode index、seed、Planner config 和 atomic GR00T checkpoint，分别生成当前 resolved metadata、episode trace 和 summary。

正式目标还要求：

- Planner 和 subtask verifier 职责分离；Verifier decision 带 visual evidence，并能区分 not-done、failed 和 uncertain。
- 每个 active execution 使用稳定 identity；相同 identity 的 continue 不依赖模型逐字复现 subtask wording。
- summary 分开统计 Planner、policy、Environment 和 benchmark failure，任何 retry 都能追溯具体原因。
- working memory 峰值不随 action chunk 数线性保存原始图像/action；长跑中断后可从完整 episode 边界恢复。
- official scenario identity、simulator seed、policy seed、source commit、checkpoint digest 和 dependency environment 全部写入结果。
- 完整 resolved AgentConfig/RunConfig、Planner prompt/schema、skill map、camera 参数和正式 experiment manifest 可从结果定位并重建。
- Runtime action-chunk budget 与 RoboCasa low-level horizon 的换算固定，切换 full/receding-horizon 或 policy chunk length 不会改变 episode 截断语义。
- 每 task 50 rollouts 在单机或多 worker 下产生相同 task/scenario 集合和 aggregation 语义。

## Risks

- RoboCasa、robosuite、MuJoCo、GR00T 和 OpenPI 的依赖可能冲突；使用独立 Conda 环境和远程 server 隔离，不把全部 extra 安装进基础 `omniagent`。
- GR00T 与 OpenPI observation/action schema 不同；模型特定转换必须留在 backend，不能扩散到 Environment 或 Runtime。
- GR00T 原生协议在 token 校验前使用 unrestricted `torch.load`；server 默认只 bind localhost，不能暴露给不可信网络。
- 官方 50-rollout 协议与本地 dataset-state reset 可能使用不同 scenario 来源；正式跑分前必须与选定官方 evaluator 对齐。
- 本地 in-process 模式会让 simulator 和 policy 争用 GPU memory；首版保持单环境并记录显存和设备配置。
- assets 软链位于 submodule working tree，重新初始化 submodule 或运行官方下载脚本前必须检查目标状态。
- headless MuJoCo render、camera orientation 和 image resize 可能造成策略输入漂移，需要保存首帧和 schema 摘要用于核对。
- 高层 Planner 每 chunk 调用成本较高；通过显式 check interval 和 skill chunk budget 控制，但不能跳过每 chunk verifier。
- 当前 `SubtaskSkillPlanner` 没有独立视觉 verifier、视觉历史或 wording few-shot；matrix 结果只能代表当前 Agent + atomic VLA case。
- Planner output contract error 会作为无动作 retry step 计入 invalid/retry budget；解释 `invalid_actions` 时不能等同于 VLA action array 非法。
- `InMemoryMemory` 当前保存完整 step event，event 包含 observation 和 action array；长 episode memory 会随 chunk 数增长。
- `RoboCasa365Evaluator` 当前启动时清空 `episodes.jsonl`，没有 resume/skip/atomic manifest；不适合直接承担大规模长时间任务。
- 只固定 simulator reset seed 不能保证 diffusion policy 可复现；正式 local/remote 比较需要显式 policy RNG 和 checkpoint digest。
- 当前 matrix 临时 RunConfig 位于 ignored run artifacts，且 `resolved_config.json` 只保存部分构造参数；仅提交结果摘要不能原样重建实验。
- Runtime `max_steps` 统计 action chunks，RoboCasa horizon 统计 low-level steps；policy chunk length 或 receding-horizon `execute_steps` 改变时可能产生不同的提前截断边界。
