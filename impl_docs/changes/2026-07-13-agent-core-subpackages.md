# Agent Core Subpackages

Date: 2026-07-13
Related plan: `impl_docs/plans/0004-agent-core-subpackages.md`

## Changed

- 将原 `agents/` 重组为独立的 `agent_core/` ownership package。
- 新增 `agents/`、`planners/`、`verifiers/` 和 `memories/` 子 package，分别保存对应 contract 与具体实现。
- 将 `BaseAgent` 与 `DefaultAgent`、`Planner` 与 `LanguageSkillPlanner`、`Verifier` 与 `EnvironmentVerifier`、`Memory` 与当前两种实现拆分到各自模块。
- 统一通过 `omniroboagent.agent_core` 导出当前 Agent Core 组件，不保留旧 `omniroboagent.agents` 路径。
- 更新内部 imports、AgentConfig `class_path`、测试、架构文档和用户文档，保持闭环运行行为不变。
- 修正 `docs/interfaces.md` 中已失效的集中式 `contracts.py` 描述。

## Files

- `src/omniroboagent/agent_core/`
- `src/omniroboagent/__init__.py`
- `src/omniroboagent/config.py`
- `src/omniroboagent/pipelines/`
- `src/omniroboagent/runtimes/`
- `src/omniroboagent/integrations/benchmarks/embodiedbench/eb_alfred.py`
- `configs/agents/eb_alfred.yaml`
- `tests/unit/`
- `docs/configuration.md`
- `docs/custom_components.md`
- `docs/interfaces.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/TODO.md`
- `impl_docs/plans/0004-agent-core-subpackages.md`

## Verification

- `conda run --no-capture-output -n omniagent python -m py_compile ...`：新 `agent_core` 模块全部通过语法检查。
- `conda run --no-capture-output -n omniagent python -m pytest -q`：24 tests passed。
- `conda run --no-capture-output -n omniagent ruff check src tests`：通过。
- `conda run --no-capture-output -n omniagent ruff format --check src tests`：45 files already formatted。
- `conda run --no-capture-output -n omniagent mypy`：41 source files 无类型错误。
- 使用 `configs/agents/eb_alfred.yaml` 构造 `DefaultAgent`，并导入 `omniroboagent.agent_core` 的全部公开组件：通过。
- 扫描源码、测试、配置和有效文档中的旧 `omniroboagent.agents` 路径：仅计划中的迁移说明命中。
- 检查本次受影响文档中的本地 Markdown links：全部目标文件存在。
- `git diff --check`：通过。

## Remaining Work

- 外部自定义配置若仍使用 `omniroboagent.agents.*`，需要迁移到 `omniroboagent.agent_core.*`。
- 本次未运行真实 vLLM、OpenPI server 或 EB-ALFRED simulator；package 重组未改变这些 integration 的运行语义。
