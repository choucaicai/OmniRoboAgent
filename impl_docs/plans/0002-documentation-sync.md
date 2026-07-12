# Implementation Documentation Sync

Status: `DONE`

## Goal

根据当前 `src/omniroboagent/`、配置文件和已验证的 EB-ALFRED smoke 结果，同步更新 `impl_docs/` 与 `docs/`，确保示例可以直接对应现有接口。

## Confirmed Decisions

- 本次只更新文档，不改变公共接口或运行行为。
- 以当前代码、实际配置、unit tests 和已落盘 smoke result 为事实来源。
- 历史 change records 和 RAI 源码分析只在存在事实错误时修改。

## Open Questions

- 无。

## Scope

- 修正架构文档中的组件职责、配置示例、目录结构和实现状态。
- 补齐 Quickstart、配置、接口、自定义组件和 EB-ALFRED 教程。
- 明确当前已实现能力、运行输出和未实现边界。
- 更新 `impl_docs/TODO.md`、文档索引和变更记录。

## Out of Scope

- 新增 backend、benchmark adapter 或 Runtime 功能。
- 运行正式 EB-ALFRED episode 集合。
- 修改第三方 clone 仓库。

## Tasks

1. 对照 contracts、CLI、Pipeline、Runtime、backend 和 integration 检查文档。
2. 修正不存在的类名、构造参数和配置层级。
3. 补充 CLI、healthcheck、资源生命周期、trace 和异常语义。
4. 明确真实 OpenPI server smoke、resolved config 保存和原生 evaluator 对齐仍未完成。
5. 校验 Markdown 本地链接、trailing whitespace 和配置加载。

## Acceptance Criteria

- 文档不引用不存在的 `LLMPlanner`、OpenPI `url` 参数或顶层 `action_execution` 配置。
- 教程中的 AgentConfig 和 RunConfig 能被当前 loader 解析。
- 当前能力和计划能力有明确区分。
- EB-ALFRED 安装、Xvfb、运行命令、结果路径和已知 smoke 结果完整。
- 所有本地 Markdown 链接有效。

## Risks

- 配置示例与构造参数漂移会导致教程不可执行。
- 将计划能力写成当前能力会掩盖真实验收缺口。

## Change Record

- `impl_docs/changes/2026-07-12-documentation-sync.md`
