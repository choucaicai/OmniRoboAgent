# Composable Agent Base

Date: 2026-07-15
Related plan: `impl_docs/plans/0008-composable-agent-base.md`

## Changed

- `BaseAgent` constructor 统一持有 Planner、Verifier、Memory 和 SkillBackend。
- `BaseAgent` 提供共享 memory update、healthcheck 和幂等 close lifecycle。
- `DefaultAgent` 简化为三个决策方法的纯委托实现。
- 增加继承式 Agent contract、component health 和重复 close 测试。
- 保持现有 AgentConfig、公开 class path 和 Pipeline/Runtime ownership 不变。

## Files

- `src/omniroboagent/agent_core/agents/base.py`
- `src/omniroboagent/agent_core/agents/default.py`
- `tests/unit/test_agent_base.py`
- `docs/interfaces.md`
- `docs/custom_components.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/plans/0008-composable-agent-base.md`
- `impl_docs/TODO.md`

## Verification

- `conda run -n omniagent pytest -q tests/unit/test_agent_base.py tests/unit/test_core_runtime.py tests/unit/test_config_and_openpi.py tests/unit/test_skill_backend_registry.py`：45 passed。
- `conda run -n omniagent ruff check src/omniroboagent/agent_core/agents tests/unit/test_agent_base.py`：通过。
- `conda run -n omniagent mypy src/omniroboagent/agent_core/agents tests/unit/test_agent_base.py`：4 个 source files 无问题。
- 本地 Markdown link checker：检查 7 个本次文档文件，所有相对链接存在。
- 本次 owned-file `git diff --check`：通过。

## Remaining Work

- TieredMemory contract 和显式 recall input 由 0009 plan 与后续 TODO 实施。
