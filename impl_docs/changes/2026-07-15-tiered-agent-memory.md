# Tiered Agent Memory

Date: 2026-07-15
Related plan: `impl_docs/plans/0009-tiered-agent-memory.md`

## Changed

- 扩展 Memory contract，增加 reset、recall 和 healthcheck lifecycle。
- 新增 `TieredMemory`，实现 bounded multi-camera working frames、structured event memory 和 bounded deterministic summary。
- event memory 可选 append-only JSONL，并排除 raw observation/action/model response。
- Runtime 在每个 session 开始时 reset Agent memory，长期 event memory 保留。
- RoboCasa composite AgentConfig 切换到 `TieredMemory`，默认 `K=4`。
- RoboCasa resolved config 记录 memory window、recent event limit 和 summary limit。

## Files

- `src/omniroboagent/agent_core/memories/`
- `src/omniroboagent/agent_core/agents/base.py`
- `src/omniroboagent/runtimes/sync.py`
- `src/omniroboagent/evals/benchmarks/robocasa/evaluator.py`
- `configs/agents/robocasa365_groot_composite_*.yaml`
- `tests/unit/test_tiered_memory.py`
- `tests/unit/test_agent_base.py`
- `tests/unit/test_core_runtime.py`
- `tests/unit/test_config_and_openpi.py`
- `docs/interfaces.md`
- `docs/configuration.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/plans/0009-tiered-agent-memory.md`
- `impl_docs/TODO.md`

## Verification

- `conda run -n omniagent pytest -q`：106 passed。
- `conda run -n omniagent ruff check ...`：本次 Memory/Agent/Runtime/Evaluator/tests 文件通过。
- `conda run -n omniagent mypy ...`：8 个本次相关 source files 无问题。
- 全部 checked-in YAML 解析通过。
- 本地 Markdown link checker：检查 7 个本次文档文件，所有相对链接存在。
- 本次 owned-file `git diff --check`：通过；repository-wide check 仍只命中用户已有 `src/omniroboagent/agent_core/planners/base.py` trailing whitespace。

## Remaining Work

- 将 `recall()` 结果通过显式 `memory_context` 接入 Planner/Verifier。
- 运行 RoboCasa composite real smoke，审计 K=4 的 RSS、latency 和效果。
