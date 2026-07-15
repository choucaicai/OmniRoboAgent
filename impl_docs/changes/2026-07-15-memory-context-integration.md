# Memory Context Integration

Date: 2026-07-15
Related plan: `impl_docs/plans/0009-tiered-agent-memory.md`

## Changed

- `DirectPipeline` 和 `SkillExecutionPipeline` 在 plan/verify node 显式调用 `Agent.recall()`。
- Planner/Verifier input 新增独立 `memory_context`，不写入 Pipeline graph state 或 transition decision。
- `LanguageSkillPlanner` 和 `SubtaskSkillPlanner` 消费 bounded summary、recent events 和 visual working frames。
- visual `SubtaskVerifier` 同时接收 action 前后 observation 与过去 K 帧 evidence。
- `TieredMemory` 默认按当前 session 过滤 recall events，长期 event memory 仍保留。
- 增加 DirectPipeline、SkillExecutionPipeline、Planner、Verifier 和 session filtering tests。

## Files

- `src/omniroboagent/pipelines/direct.py`
- `src/omniroboagent/pipelines/skill_execution.py`
- `src/omniroboagent/agent_core/agents/base.py`
- `src/omniroboagent/agent_core/planners/language_skill.py`
- `src/omniroboagent/agent_core/planners/subtask_skill.py`
- `src/omniroboagent/agent_core/verifiers/subtask.py`
- `src/omniroboagent/agent_core/memories/tiered.py`
- `tests/unit/`
- `README.md`
- `docs/`
- `impl_docs/`

## Verification

- `conda run -n omniagent pytest -q`：108 passed。
- `conda run -n omniagent ruff check src tests`：通过。
- `conda run -n omniagent mypy`：58 个 source files 无问题。
- 本地 Markdown link checker：检查 9 个本次文档文件，所有相对链接存在。
- 本次 owned-file `git diff --check`：通过。

## Remaining Work

- 运行固定 RoboCasa `composite_seen` episode，记录成功率、progress、steps、latency、transition 和 verifier evidence。
- 根据 real smoke 调整 K、camera sampling 和 verifier interval。
