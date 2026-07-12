# Xvfb EB-ALFRED Smoke Evaluation

Date: 2026-07-12
Related plan: `impl_docs/plans/0001-eb-alfred-first-loop.md`

## Changed

- 增加 `scripts/run_eb_alfred_xvfb.sh`，自动复用或启动 Xvfb，并设置 EB-ALFRED 所需环境变量。
- 将 smoke resolution 对齐为 EB-ALFRED 实测的 `300 x 300`。
- 固定 `ai2thor==2.1.0` 兼容的 Flask/Werkzeug 依赖组合，解决 Unity `Initialize` 持续等待。
- `LanguageSkillPlanner` 支持动态 skill enum、action id 前缀、纯数字 action id 和 `reasoning_content` fallback。
- Qwen 配置通过 `extra_body.chat_template_kwargs.enable_thinking: false` 关闭 thinking。
- 更新 EB-ALFRED 安装、Xvfb 运行、接口配置和 smoke 结果文档。

## Files

- `scripts/run_eb_alfred_xvfb.sh`
- `configs/agents/eb_alfred.yaml`
- `configs/runs/eb_alfred_smoke.yaml`
- `src/omniroboagent/planners.py`
- `tests/unit/test_llm_and_planner.py`
- `tutorial_docs/eb_alfred.md`
- `tutorial_docs/quickstart.md`
- `tutorial_docs/interfaces.md`
- `impl_docs/plans/0001-eb-alfred-first-loop.md`
- `impl_docs/TODO.md`

## Verification

- `EBAlfEnv.reset()` 实测返回 `(300, 300, 3)` RGB observation 和 208 个动态 skills。
- `DISPLAY=:1 LIBGL_ALWAYS_SOFTWARE=1 conda run --no-capture-output -n omniagent-eb omniroboagent run --config configs/runs/eb_alfred_smoke.yaml`：完成真实 `base[0]` episode。
- 结果为 14 steps、10 invalid actions、10 replans、progress `0.3333`、latency `38.64s`，终止原因为 `environment_done`。
- 生成 `runs/eb_alfred_smoke/summary.json`、`episodes.jsonl`、`result.json` 和 16 条 trace event。
- `bash -n scripts/run_eb_alfred_xvfb.sh`：通过。
- `conda run -n omniagent python -m pytest`：24 个 tests 全部通过。
- `conda run -n omniagent ruff check src tests`：通过。
- `conda run -n omniagent ruff format --check src tests`：27 个文件格式正确。
- `conda run -n omniagent mypy`：22 个 source files 无类型错误。

## Remaining Work

- 当前 Planner 在成功执行 `find a Ladle`、`pick up the Ladle`、`find a Faucet`、`turn on the Faucet` 后重复选择 `pick up the Ladle`，未完成任务。
- 用户确认正式 subset 和 episode 列表后运行正式评测。
- 在相同 episodes 上与 EmbodiedBench 原生 evaluator 对齐指标。
- 使用真实 OpenPI policy server 完成协议 smoke。
