# RoboCasa365 Evaluation Plan

Date: 2026-07-15
Related plan: `impl_docs/plans/0006-robocasa365-evaluation.md`

## Changed

- 新增 RoboCasa365 evaluation-first Agent + VLA 设计，明确 Environment、Evaluator、Pipeline、三个 SkillBackend 模式和 server 的职责边界。
- 区分 RoboCasa 官方 `task_set` 与 `pretrain` / `target` split，并规划固定 `1 task x 1 episode` smoke。
- 确认 RoboCasa 使用 submodule，本机 assets 使用软链，公开文档要求按官方教程安装 assets。
- 将 RoboCasa365 实施拆分为可独立跟踪的 TODO milestones；实现状态保持 `TODO`。

## Files

- `impl_docs/plans/0006-robocasa365-evaluation.md`
- `impl_docs/TODO.md`
- `impl_docs/README.md`
- `impl_docs/changes/2026-07-15-robocasa365-evaluation-plan.md`

## Verification

- 阅读并核对 `rules/README.md`、`impl_docs/architecture/overview.md`、当前 EB-ALFRED Environment/Evaluator、Pipeline、Runtime 和 SkillBackend 实现。
- 对照 RoboCasa `v1.0-12-g9a3a786` 的官方 benchmarking、policy learning、installation 文档和 `TASK_SET_REGISTRY`。
- 确认本机 assets 位于 `/home/zzz/vla_code/robocasa/robocasa/models/assets`，约 23 GB；本次未创建或修改软链。
- 运行 `git diff --check` 和本地 Markdown link 检查。
- 未运行 pytest、Ruff、mypy、RoboCasa simulator 或 VLA server；本次仅修改实施计划和任务状态，不改变代码行为。

## Remaining Work

- 按 `impl_docs/plans/0006-robocasa365-evaluation.md` 实现 submodule、assets link、Environment、Evaluator、Pipeline、GR00T/OpenPI remote server/backend 和 local backend。
- 实施前固定三个 policy mode 的 checkpoint/config，以及首个真实 smoke 的 task 和 scenario。
- 完成真实 `1 task x 1 episode` smoke 后再更新 architecture、用户文档、TODO 状态和实现 change record。
