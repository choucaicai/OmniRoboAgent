# Package Architecture Design

Date: 2026-07-12
Related plan: `impl_docs/plans/0003-package-architecture.md`

## Changed

- 明确 Agent Core 及 Planner、Verifier、Memory 归属 `agents/`。
- 明确 `pipelines/`、`runtimes/`、`environments/` 和两个 backend package 的 ownership。
- 将 contract 从集中式 `contracts.py` 调整为目标 package 内的 `base.py`。
- 将 integrations 目标结构划分为 `benchmarks/`、`ros2/` 和 `human_interface/`。
- 明确 `ros2` 负责系统连接，`human_interface` 负责人与 Agent 的输入、确认、反馈和接管。
- 区分当前平铺实现与目标 package layout，避免将尚未迁移的 import path 描述成可运行状态。

## Files

- `impl_docs/architecture/overview.md`
- `impl_docs/TODO.md`
- `impl_docs/plans/0003-package-architecture.md`
- `impl_docs/changes/2026-07-12-package-architecture-design.md`

## Verification

- 人工核对目标目录与 package ownership、依赖方向和当前实现状态：通过。
- 未运行代码测试：本次只修改 Markdown 文档，不修改源码或配置。

## Remaining Work

- 按 `impl_docs/plans/0003-package-architecture.md` 迁移源码、imports、配置和测试。
- 决定旧 import path 和 dotted `class_path` 的兼容周期。
- 在出现实际需求时实现 `ros2` 和 `human_interface`，当前不创建占位模块。
