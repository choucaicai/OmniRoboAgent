# Skill Execution State Graph Implementation

Date: 2026-07-15
Related plan: `impl_docs/plans/0007-skill-execution-state-graph.md`

## Changed

- 将 Planner proposal 调整为 skill/subtask、grounded arguments 和 expected outcome，不再由 Planner 判断 completion。
- 新增独立 `SubtaskVerifier`，输出 structured execution status、reason、confidence 和 evidence，并保留 benchmark authoritative task success。
- 将 `SkillExecutionPipeline` 改为 Pipeline-owned explicit graph state 和 deterministic transitions。
- 实现 retry current、replan、fallback、abort、attempt/chunk/uncertain budgets、no-progress 和 repeated/A-B-A loop detection。
- 增加 execution/attempt identity、transition fields、verifier evidence summary 和 completed/failed ledgers。
- 将 RoboCasa atomic/composite configs 迁移到 `SubtaskVerifier`；composite 每 8 chunks 执行一次视觉语义检查。
- 保持 Runtime lifecycle ownership、`DirectPipeline` 行为和旧 `planner_check_interval_chunks` constructor compatibility。

## Files

- `src/omniroboagent/agent_core/agents/default.py`
- `src/omniroboagent/agent_core/planners/subtask_skill.py`
- `src/omniroboagent/agent_core/planners/task_skill.py`
- `src/omniroboagent/agent_core/verifiers/`
- `src/omniroboagent/pipelines/skill_execution.py`
- `src/omniroboagent/evals/benchmarks/robocasa/evaluator.py`
- `configs/agents/robocasa365_*.yaml`
- `configs/runs/robocasa365_*_smoke.yaml`
- `tests/unit/`
- `README.md`
- `docs/`
- `impl_docs/`

## Verification

- `conda run -n omniagent pytest -q`：96 passed。
- `conda run -n omniagent ruff check src tests`：通过。
- `conda run -n omniagent mypy`：57 个 source files 无问题。
- 全部 `configs/**/*.yaml` 使用 `yaml.safe_load()` 解析通过。
- 本地 Markdown link checker：检查 9 个本次用户/实现文档文件，所有相对链接存在。
- 本次 owned-file `git diff --check`：通过。
- `git diff --cached --check`：通过；用户已有 `src/omniroboagent/agent_core/planners/base.py` 修改未暂存、未提交。
- `conda run -n omniagent ruff check .` 会扫描 `benchmarks/EmbodiedBench` 和 `benchmarks/RoboCasa` 上游 submodule，并命中其既有 lint 问题；未修改第三方 checkout。
- 未运行迁移后的真实 Qwen/GR00T/OpenPI smoke：本机服务和 checkpoint 不属于 unit validation 范围。

## Remaining Work

- 使用真实 Qwen + GR00T remote/local checkpoint 运行迁移后的 RoboCasa composite smoke，核对 verifier latency、evidence quality 和 recovery trace。
- Agent 基类组合重构和 TieredMemory 分别由 0008、0009 plan 跟踪，本次未实施。
