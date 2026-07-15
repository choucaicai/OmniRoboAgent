# RoboCasa365 Composite Agent Evaluation

Date: 2026-07-15
Related plan: `impl_docs/plans/0006-robocasa365-evaluation.md`

## Changed

- 添加 `SubtaskSkillPlanner`，通过 OpenAI-compatible multimodal structured output 选择 macro skill、concrete subtask 和 execution status，并从可信 AgentConfig 映射 `skill_id`。
- 允许 `RoboCasaEnvironment` 从 RunConfig 暴露 composite evaluation 的 atomic macro skill catalog，同时保持 atomic task 默认返回 `[task_name]`。
- 扩展 GR00T shared request builder：合法显式 `skill_id` 使用 composite `task`、atomic `skill` 和 concrete subtask；缺少 `skill_id` 时保留 atomic strict equality。
- 添加 GR00T composite remote/local AgentConfig 和单任务 smoke RunConfig。
- 对 `DeliverStraw`、`ArrangeBreadBasket` 完成 remote/local one-action probe，并完成 `composite_seen` / `composite_unseen`、`pretrain` / `target`、remote/local 的 40-episode matrix。
- 同步用户文档、architecture、plan 和 TODO；记录模型 JSON 与 Planner output 的字段边界、三个真实 subtask sequence、chunk budget status，以及已观察到的粒度和 retry 失败模式。
- 将用户文档中的已实现 benchmark 归入独立 `Benchmarks` 章节，并以 `EB-ALFRED`、`RoboCasa365` 作为子章节和侧边栏子项。
- 基于当前 source 和 40-episode artifacts，补充面向目标系统的优先级 roadmap：official evaluator、独立 subtask verifier、原子 decomposition、错误指标、skill-ID consistency、bounded memory、resume 和正式规模评测。
- 复核官方 50-scenario protocol、Evaluator/Runtime 和本地 artifacts，补充 experiment manifest、完整 resolved config、policy/source/environment identity、low-level horizon 与 action-chunk budget、全 artifact resume/atomic write 等缺口。

## Files

- `configs/agents/robocasa365_groot_composite_remote.yaml`
- `configs/agents/robocasa365_groot_composite_local.yaml`
- `configs/runs/robocasa365_groot_composite_remote_smoke.yaml`
- `configs/runs/robocasa365_groot_composite_local_smoke.yaml`
- `src/omniroboagent/agent_core/planners/subtask_skill.py`
- `src/omniroboagent/agent_core/planners/__init__.py`
- `src/omniroboagent/agent_core/__init__.py`
- `src/omniroboagent/backends/skills/groot.py`
- `src/omniroboagent/environments/benchmarks/robocasa/environment.py`
- `tests/unit/test_llm_and_planner.py`
- `tests/unit/test_groot_backend.py`
- `tests/unit/test_robocasa_evaluation.py`
- `README.md`
- `docs/README.md`
- `docs/_sidebar.md`
- `docs/robocasa365.md`
- `docs/configuration.md`
- `docs/interfaces.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/plans/0006-robocasa365-evaluation.md`
- `impl_docs/TODO.md`

## Verification

- `conda run -n omniagent python -m pytest -q`：73 passed。
- `conda run -n omniagent python -m pytest -q tests/unit/test_llm_and_planner.py tests/unit/test_groot_backend.py tests/unit/test_robocasa_evaluation.py`：31 passed。
- `conda run -n omniagent python -m ruff check src tests scripts`：通过。
- `conda run -n omniagent python -m ruff format --check src tests scripts`：通过。
- `conda run -n omniagent python -m mypy src`：54 source files 无类型错误。
- `conda run -n omniagent uv lock --check`：通过。
- 两个 composite AgentConfig、两个 tracked smoke RunConfig 和 8 个 ignored matrix RunConfig 均完成配置实例化；Qwen `Qwen3.5-9B` live structured-output probe 返回合法 macro skill、trusted skill ID、subtask 和 execution status。
- `DeliverStraw`、`ArrangeBreadBasket` 的 remote/local one-action probe 均执行 1 action chunk、16 environment steps，0 exception。
- 40-episode artifact audit 确认每组 5 条 `episodes.jsonl`、5 份完整 `trace.jsonl` / `result.json`，local/remote 的 task list、`episode_index=0`、`seed=0`、RoboCasa commit `9a3a786` 和 robosuite commit `aaa8b9b` 一致。
- 使用 `jq` 从 `DeliverStraw`、成功的 `KettleBoiling`、`ArrangeBreadBasket` 和 `ArrangeTea` trace 提取 planner-called step；文档中的 subtask wording、skill、skill ID 和 mismatch error 与 artifact 一致。

| Mode | Task set | Split | Success | Environment steps | Action chunks | Planner calls | Replans | Invalid/retry | Exceptions | Latency seconds | Termination |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| remote | `composite_seen` | `pretrain` | 0 / 5 | 8500 | 533 | 76 | 32 | 6 | 0 | 704.95 | 5 environment done |
| remote | `composite_seen` | `target` | 0 / 5 | 8140 | 510 | 73 | 31 | 5 | 0 | 765.45 | 4 environment done, 1 retry limit |
| remote | `composite_unseen` | `pretrain` | 0 / 5 | 7600 | 477 | 68 | 22 | 1 | 0 | 689.58 | 5 environment done |
| remote | `composite_unseen` | `target` | 0 / 5 | 6228 | 391 | 56 | 20 | 7 | 0 | 568.82 | 4 environment done, 1 retry limit |
| local | `composite_seen` | `pretrain` | 1 / 5 | 7326 | 459 | 64 | 36 | 11 | 0 | 640.37 | 3 environment done, 1 retry limit, 1 success |
| local | `composite_seen` | `target` | 0 / 5 | 7052 | 442 | 62 | 30 | 6 | 0 | 668.45 | 4 environment done, 1 retry limit |
| local | `composite_unseen` | `pretrain` | 0 / 5 | 7172 | 450 | 64 | 25 | 4 | 0 | 637.28 | 4 environment done, 1 retry limit |
| local | `composite_unseen` | `target` | 0 / 5 | 6228 | 391 | 54 | 28 | 7 | 0 | 571.67 | 4 environment done, 1 retry limit |

- 唯一成功 episode 为 local `KettleBoiling / pretrain`，在 506 environment steps、32 action chunks 时由 RoboCasa 返回 success。
- 以下本地 relative-link checker 覆盖本次受影响文档，无缺失链接输出：

```bash
for f in README.md docs/README.md docs/_sidebar.md docs/configuration.md \
  docs/interfaces.md docs/robocasa365.md impl_docs/TODO.md \
  impl_docs/architecture/overview.md \
  impl_docs/plans/0006-robocasa365-evaluation.md \
  impl_docs/changes/2026-07-15-robocasa365-composite-evaluation.md; do
  while IFS= read -r target; do
    target="${target%%#*}"
    target="${target%%\?*}"
    case "$target" in
      ''|http://*|https://*|mailto:*|'#'*) continue ;;
    esac
    test -e "$(dirname "$f")/$target" || printf '%s -> %s\n' "$f" "$target"
  done < <(perl -ne 'while (/\[[^]]+\]\(([^)]+)\)/g) { print "$1\n" }' "$f")
done
```

- `git diff --check && git diff --cached --check`：通过。

## Remaining Work

- 本机仍无可用 OpenPI checkpoint，真实 OpenPI policy smoke 未运行。
- 当前 GR00T checkpoint 依赖未提交的 `gr00t.model_moe_v1` 和 `data_config_mem_groot.py`；公开 base commit 不能独立复现。
- `episode_index` 仍是 reset seed offset，不是官方 dataset scenario index；正式 50-rollout 结果需与 RoboCasa evaluator 对齐。
- 当前 `SubtaskSkillPlanner` 没有独立视觉 verifier、视觉历史和 wording few-shot；matrix 只代表当前 Agent + atomic VLA case。
- Planner output mismatch 作为无动作 retry step 计入 invalid/retry budget；`invalid_actions` 不能解释为非法 VLA action array。
- diffusion policy 未固定推理 RNG；相同 simulator seed 不要求 local/remote action 或 success 完全一致。
- 正式 task-set scope 和官方随机 50-scenario manifest 尚未确定；当前 `episode_index` 仍只是 reset seed offset。
- 12 组 atomic/composite matrix 的临时 RunConfig 尚未纳入版本控制，`resolved_config.json` 也只保存部分参数，其他机器不能据此原样重建实验。
- Runtime `max_steps` 按 action chunk 计数，RoboCasa horizon 按 low-level step 计数；正式协议前需固定两者换算和截断语义。
