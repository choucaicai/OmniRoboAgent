# Evaluation And Environment Ownership

Date: 2026-07-14
Related plan: `impl_docs/plans/0005-eval-environment-ownership.md`

## Changed

- 将 `EBAlfredEnvironment` 迁移到 `environments/benchmarks/embodiedbench/`，独立负责 simulator interaction 和结果转换。
- 将 `EBAlfredBenchmark` 迁移到 `evals/benchmarks/embodiedbench/`，独立负责任务遍历、episode 结果保存和指标聚合。
- 删除 `integrations/benchmarks/` ownership 和旧公开路径，不增加兼容 wrapper。
- 将 `integrations/` 限定为 planned ROS2 与 human text I/O 外部交互接口。
- 更新 RunConfig、unit tests、项目规则、架构文档和用户文档中的公开路径与依赖方向。
- 保持 EB-ALFRED task selection、environment execution、trace、summary 和 metric 语义不变。

## Files

- `src/omniroboagent/environments/benchmarks/embodiedbench/`
- `src/omniroboagent/evals/benchmarks/embodiedbench/`
- `src/omniroboagent/integrations/__init__.py`
- `configs/runs/eb_alfred_smoke.yaml`
- `tests/unit/test_eb_alfred_integration.py`
- `rules/README.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/TODO.md`
- `impl_docs/plans/0005-eval-environment-ownership.md`
- `docs/configuration.md`
- `docs/README.md`
- `README.md`

## Verification

- `conda run --no-capture-output -n omniagent python -m py_compile ...`：新的 environment 和 evaluation 模块通过语法检查。
- `conda run --no-capture-output -n omniagent python -m pytest -q tests/unit/test_eb_alfred_integration.py`：3 tests passed。
- `conda run --no-capture-output -n omniagent python -m pytest -q`：24 tests passed。
- `conda run --no-capture-output -n omniagent ruff check src tests`：通过。
- `conda run --no-capture-output -n omniagent ruff format --check src tests`：49 files already formatted。
- `conda run --no-capture-output -n omniagent mypy`：46 source files 无类型错误。
- 导入两个新 public paths，并检查 `configs/runs/eb_alfred_smoke.yaml` 中对应 `class_path`：通过。
- 扫描当前源码、测试、配置、用户文档、架构文档和项目规则中的旧 `integrations/benchmarks` 路径：无命中。
- 检查本次受影响文档中的本地 Markdown links：全部目标文件存在。
- `git diff --check`：通过。

## Remaining Work

- 外部配置若仍使用 `omniroboagent.integrations.benchmarks.*`，需要迁移到新的 environment/evaluation 路径。
- ROS2 与 human text I/O 仍是 planned ownership，本次未创建占位实现。
- 本次未运行真实 vLLM、OpenPI server 或 EB-ALFRED simulator；此前已验证的运行语义未改动。
