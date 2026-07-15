# Package Architecture Implementation

Date: 2026-07-12
Related plan: `impl_docs/plans/0003-package-architecture.md`

## Changed

- 将 Agent Core、Planner、Verifier 和 Memory 迁移到 `agents/`。
- 将 Pipeline、Runtime 和 Environment 分别迁移到 `pipelines/`、`runtimes/` 和 `environments/`。
- 将 `LLMBackend` 和 `SkillBackend` contract 迁移到对应 backend package 的 `base.py`。
- 删除集中式 `contracts.py` 和被 package 替代的平铺模块。
- 将 EmbodiedBench adapter 迁移到 `integrations/benchmarks/embodiedbench/`。
- 更新源码 imports、公开 API、YAML `class_path`、unit tests 和用户文档。
- 保持 Runtime、Pipeline、Verifier、action payload 和 benchmark 运行行为不变。

## Files

- `src/omniroboagent/`
- `configs/agents/eb_alfred.yaml`
- `configs/runs/eb_alfred_smoke.yaml`
- `tests/unit/`
- `docs/configuration.md`
- `docs/custom_components.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/TODO.md`
- `impl_docs/plans/0003-package-architecture.md`

## Verification

- `conda run -n omniagent python -m pytest -q`：24 tests passed。
- `conda run -n omniagent mypy`：33 source files 无类型错误。
- `conda run -n omniagent ruff check src tests`：通过。
- `conda run -n omniagent ruff format --check src tests`：37 files already formatted。
- 使用当前 AgentConfig 和 RunConfig 实例化 `DefaultAgent`、`DirectPipeline` 和 `SyncRuntime`：通过。
- 导入各 package public API 和迁移后的 EmbodiedBench adapter：通过。
- `uv` 未执行：当前 shell 中命令不可用，使用项目指定的 `omniagent` Conda 环境验证。

## Remaining Work

- 在真实 OpenPI server 和连续控制 Environment 上完成待办验证。
- `ros2` 和 `human_interface` 仅保留 planned ownership，出现实际实现时再创建目录。
