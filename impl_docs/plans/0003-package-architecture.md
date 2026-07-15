# Package Architecture

Status: `DONE`

## Goal

将当前平铺的 core 模块重组为能够表达职责边界的 Python packages，同时保持现有闭环行为和依赖方向不变。

## Confirmed Decisions

- `agents/` 包含 `BaseAgent`、`DefaultAgent`、Planner、Verifier 和 Memory。
- `pipelines/`、`runtimes/`、`environments/`、`backends/` 保持独立 package。
- 各 contract 放回所属 package 的 `base.py`，不继续集中在 `contracts.py`。
- `integrations/` 按接入类型划分为 `benchmarks/`、`ros2/` 和 `human_interface/`。
- 当前只迁移已实现的 EmbodiedBench adapter；`ros2/` 和 `human_interface/` 只记录为 planned，不创建空实现。
- package 重组阶段不修改 Pipeline、Runtime、Verifier 或 action payload 的运行语义。

## Open Questions

- 无。当前项目仍处于 `v0.1`，直接迁移内部 import 和配置路径，不保留与目标 package 名冲突的平铺兼容模块。

## Scope

- 重组 `src/omniroboagent/` package 结构。
- 更新内部 import、公开导出、配置 `class_path`、测试和使用文档。
- 将 EmbodiedBench adapter 移到 `integrations/benchmarks/embodiedbench/`。
- 删除不再使用的平铺模块和集中式 `contracts.py`。

## Out of Scope

- 实现 ROS2、真机连接或 human interface。
- 新增 benchmark、Pipeline、Runtime、Planner、Verifier 或 Memory 能力。
- 改变现有数据 contract 和闭环行为。

## Tasks

1. 创建目标 packages 并移动现有 contract 和实现。
2. 定义各 package 的最小公开 API。
3. 更新源码、配置、测试和文档中的 import path。
4. 验证配置加载、unit tests、Ruff 和 mypy。
5. 更新 `impl_docs/TODO.md` 并添加实施变更记录。

## Acceptance Criteria

- 源码结构与 `impl_docs/architecture/overview.md` 的目标 package layout 一致。
- core package 不 import benchmark SDK、ROS2 或具体 integration 类型。
- 现有 EB-ALFRED 配置可以加载，unit tests 全部通过。
- package 重组不改变 Runtime、Pipeline 和 benchmark adapter 的可观察行为。
- `ros2` 和 `human_interface` 保持明确的未实现状态。

## Risks

- dotted `class_path` 变化可能破坏已有配置。
- 移动 contract 时可能产生循环 import。
- 同时调整结构和行为会扩大验证范围，因此实施时必须保持行为不变。

## Change Record

- `impl_docs/changes/2026-07-12-package-architecture-implementation.md`
