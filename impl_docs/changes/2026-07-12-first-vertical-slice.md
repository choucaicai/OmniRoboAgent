# First Vertical Slice

Date: 2026-07-12
Related plan: `impl_docs/plans/0001-eb-alfred-first-loop.md`

## Changed

- 实现全部最小 Core contracts、组合式 `DefaultAgent`、`DirectPipeline` 和 `SyncRuntime`。
- 实现 working memory、JSONL memory、trace serialization、分类错误和资源关闭。
- 实现 AgentConfig、RunConfig、递归 `class_path + init_args` 加载和 CLI。
- 实现支持文本、单图和多图的 `OpenAICompatibleLLMBackend`。
- 实现单 skill `LanguageSkillPlanner`，兼容直接 skill、action id 和 EmbodiedBench baseline 首个 action。
- 实现基于官方 OpenPI client protocol 的 `OpenPIWebSocketPolicyBackend`。
- 实现 full/receding-horizon action execution 配置。
- 实现 `EBAlfredEnvironment`、episode runner、trace、results 和 summary。
- 添加 EB-ALFRED smoke AgentConfig 和 RunConfig。
- 创建 `tutorial_docs/` 使用文档和接口文档。
- 创建并安装 `omniagent-eb`，下载 EB-ALFRED dataset 和 AI2-THOR binary。

## Files

- `README.md`
- `pyproject.toml`
- `configs/`
- `src/omniroboagent/`
- `tests/unit/`
- `tutorial_docs/`
- `impl_docs/architecture/overview.md`
- `impl_docs/plans/0001-eb-alfred-first-loop.md`
- `impl_docs/TODO.md`
- `impl_docs/README.md`

## Verification

- `conda run -n omniagent python -m pytest`：24 个 unit tests 全部通过。
- `conda run -n omniagent ruff check src tests`：通过。
- `conda run -n omniagent ruff format --check src tests`：通过。
- `conda run -n omniagent mypy`：通过。
- `omniroboagent health --agent-config configs/agents/eb_alfred.yaml`：确认 `Qwen3.5-9B` endpoint healthy。
- 使用真实 vLLM、单张测试图和两个 language skills 调用 `LanguageSkillPlanner`：正确返回 `find a Mug`。
- 在 `omniagent` 中安装并导入官方 `openpi_client.WebsocketClientPolicy`：通过。
- `omniagent-eb` 中导入 `EBAlfEnv`：通过。
- 构造真实 Unity `EBAlfredEnvironment(selected_indexes=[0])`：成功，识别 1 个 episode 和 162 个 skills。
- 固定兼容的 Flask/Werkzeug/Jinja2/MarkupSafe/itsdangerous/urllib3 版本后，`Xvfb :1` 下真实 `reset()` 成功，observation shape 为 `(300, 300, 3)`。
- `configs/runs/eb_alfred_smoke.yaml` 在 `base[0]` 完成 14 个真实环境 step，生成 `summary.json`、`episodes.jsonl`、`result.json` 和 16 条 trace event。

## Remaining Work

- 用户确认正式评测 subset 和 episode 列表后运行正式评测。
- 在相同 episode 上与 EmbodiedBench 原生 evaluator 对齐指标。
- 使用真实 OpenPI policy server 做协议 smoke；当前使用官方 client commit 和 fake server contract 测试。
