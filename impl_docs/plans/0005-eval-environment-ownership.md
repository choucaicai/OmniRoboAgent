# Evaluation And Environment Ownership

Status: `DONE`

## Goal

将 benchmark evaluation、benchmark environment 和外部交互 integration 分离到职责明确的 packages，同时保持 EB-ALFRED 运行行为不变。

## Confirmed Decisions

- `evals/benchmarks/embodiedbench/` 保存 `EBAlfredBenchmark` 等评测 runner 和指标聚合实现。
- `environments/benchmarks/embodiedbench/` 保存 `EBAlfredEnvironment` 等 benchmark environment adapter。
- `integrations/` 仅用于 ROS2 和 human text I/O 等外部交互接口。
- `evals` 可以依赖 Agent、Pipeline、Runtime 和 Environment；核心执行 packages 不反向依赖 `evals`。
- 不保留旧 `omniroboagent.integrations.benchmarks.*` 兼容路径。
- 本次只调整 ownership、imports 和公开路径，不修改 EB-ALFRED 环境或评测语义。

## Open Questions

- 无。

## Scope

- 将 `EBAlfredEnvironment` 迁移到 `environments/benchmarks/embodiedbench/`。
- 将 `EBAlfredBenchmark` 迁移到 `evals/benchmarks/embodiedbench/`。
- 更新源码导出、RunConfig `class_path`、测试、项目规则和文档。
- 从 `integrations/` 删除 benchmark ownership，仅保留 ROS2 和 human interface 的 planned 边界。

## Out of Scope

- 实现 ROS2 或 human text I/O。
- 新增统一 Benchmark 基类、registry 或 evaluator protocol。
- 修改 EB-ALFRED 指标、任务选择或 episode 执行行为。
- 保留旧 import 或配置路径的兼容层。

## Tasks

1. 创建 environment 和 evaluation 的目标 packages。
2. 拆分 `EBAlfredEnvironment` 与 `EBAlfredBenchmark` 实现并更新 imports。
3. 更新 YAML `class_path` 和 unit tests。
4. 更新项目规则、架构文档和用户文档。
5. 运行 unit tests、Ruff、mypy、配置实例化和 stale-path 检查。

## Acceptance Criteria

- `EBAlfredEnvironment` 的公开路径为 `omniroboagent.environments.benchmarks.embodiedbench.EBAlfredEnvironment`。
- `EBAlfredBenchmark` 的公开路径为 `omniroboagent.evals.benchmarks.embodiedbench.EBAlfredBenchmark`。
- 有效代码、配置和当前文档不再引用 `omniroboagent.integrations.benchmarks`。
- `integrations/` 的当前 ownership 只描述 ROS2 和 human text I/O。
- 现有 unit tests、Ruff 和 mypy 全部通过。

## Risks

- dotted `class_path` 变化会破坏仍使用旧路径的外部配置。
- 拆分 evaluator 与 environment 时可能引入循环 import。
- architecture rules 若未同步，会继续把 benchmark adapter 错误归入 `integrations/`。

## Change Record

- `impl_docs/changes/2026-07-14-eval-environment-ownership.md`
