# Modular Architecture Decisions

Date: 2026-07-11
Related plan: `impl_docs/plans/0001-eb-alfred-first-loop.md`

## Changed

- 将 `BaseAgent` 明确为 Agent Core，`DefaultAgent` 通过组合使用 Planner、Verifier、Memory 和 SkillBackend。
- 将 Pipeline 从 Agent Core 中独立出来，由 RunConfig 选择并负责模块调用顺序和 Verifier decision 语义。
- Runtime 改为只维护 episode 生命周期、限制和普通 state 字典。
- 取消统一 Action 基类，SkillBackend 可以返回任意 action payload，由 Environment 执行和校验。
- 取消固定 `VerificationResult` 和 `AgentContext` 类，Verifier 和运行状态使用普通字典。
- Planner 输出保持开放，由当前 Pipeline 解释。
- 配置拆分为 AgentConfig 和 RunConfig，并允许通过 dotted `class_path` 加载自定义组件。
- 确认第一版使用 `pip + pyproject.toml`。
- 确认 OpenAI-compatible backend 支持文本和图像输入。
- 确认远程 policy 使用 OpenPI WebSocket 协议。
- 确认 vLLM 和 OpenPI server 由用户提前启动，框架只管理客户端生命周期。
- 确认 action chunk 支持完整执行和 receding-horizon 两种配置。
- 明确 benchmark 只通过 optional integration adapter 接入，不进入 core。

## Files

- `impl_docs/architecture/overview.md`
- `impl_docs/plans/0001-eb-alfred-first-loop.md`
- `impl_docs/TODO.md`
- `rules/README.md`
- `impl_docs/changes/2026-07-11-modular-architecture-decisions.md`

## Verification

- 检查架构、计划、TODO 和规则中的模块职责一致。
- 检查旧的固定 Action、VerificationResult 和 AgentContext 设计没有继续作为实施任务保留。
- 检查 Markdown 相对链接和尾随空白。
- 本次没有修改运行代码，因此不运行代码测试。

## Remaining Work

- 确认项目许可证。
- 确认首个模型、endpoint 和 EB-ALFRED episode 集合。
- 固定第一版兼容的 OpenPI 版本及协议测试入口。
- 按更新后的计划初始化 `pyproject.toml` 和 Python package。

