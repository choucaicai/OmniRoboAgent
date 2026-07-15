# RoboCasa365 Evaluation Implementation

Date: 2026-07-15
Related plan: `impl_docs/plans/0006-robocasa365-evaluation.md`

## Changed

- 添加固定到 `9a3a78680443734786c9784ab661413edb87067b` 的 RoboCasa submodule，以及拒绝覆盖现有内容的 assets 软链脚本。
- 实现 `RoboCasaEnvironment`、`RoboCasa365Evaluator` 和 `SkillExecutionPipeline`，覆盖 task/split reset、action chunk、权威 success signal、结果聚合和可复现 metadata。
- 实现最小 `SkillBackendRegistry`，内置 `groot_remote`、`openpi_remote` 和 `local`，并保留自定义 `class_path` fallback。
- 实现 GR00T ZeroMQ remote backend/server、GR00T in-process adapter、OpenPI WebSocket RoboCasa schema backend/server，以及三组 AgentConfig/RunConfig。
- 固定 OpenPI client 到兼容 NumPy 2 的 `robocasa-benchmark/openpi@5a6beda9ff99da30b4e1b59320f6a32971d7c397`。
- 对 camera/state/action schema、timeout、controller range、episode memory reset 和 chunk/replan budget 增加严格校验及 unit tests。
- 在 `atomic_seen` 的同一组 5 个 task 上完成 GR00T remote/local 的 `pretrain` / `target` matrix，共 20 个真实 simulator episode。
- 为 `robosuite.__file__` 增加缺失检查，修复最终 mypy 验证发现的 `Path(str | None)` 类型错误。

## Files

- `.gitmodules`
- `benchmarks/RoboCasa`
- `scripts/link_robocasa_assets.sh`
- `scripts/serve_robocasa_groot.py`
- `scripts/serve_robocasa_openpi.py`
- `configs/agents/robocasa365_*.yaml`
- `configs/runs/robocasa365_*.yaml`
- `src/omniroboagent/backends/skills/`
- `src/omniroboagent/environments/benchmarks/robocasa/`
- `src/omniroboagent/evals/benchmarks/robocasa/`
- `src/omniroboagent/pipelines/skill_execution.py`
- `tests/unit/test_config_and_openpi.py`
- `tests/unit/test_groot_backend.py`
- `tests/unit/test_robocasa_evaluation.py`
- `tests/unit/test_skill_backend_registry.py`
- `README.md`
- `docs/`
- `rules/README.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/TODO.md`
- `impl_docs/plans/0006-robocasa365-evaluation.md`

## Verification

- `conda run -n omniagent python -m pytest -q`：57 passed。
- `conda run -n omniagent python -m pytest -q tests/unit/test_robocasa_evaluation.py tests/unit/test_groot_backend.py tests/unit/test_skill_backend_registry.py tests/unit/test_config_and_openpi.py`：38 passed。
- `conda run -n omniagent python -m ruff check src tests scripts`：通过。
- `conda run -n omniagent python -m ruff format --check src tests scripts`：63 files already formatted。
- `conda run -n omniagent python -m mypy src`：53 source files 无类型错误。
- `conda run -n omniagent uv lock --check`：依赖解析通过。
- GR00T server 使用 `CUDA_VISIBLE_DEVICES=1 conda run -n groot --no-capture-output python scripts/serve_robocasa_groot.py --groot-root /home/zzz/vla_code/robocasa/Isaac-GR00T --model-path /home/zzz/vla_code/robocasa/Isaac-GR00T/runnings/trained_vla/groot_atomic_intern_moe_v1/checkpoint-240000 --host 127.0.0.1 --port 5555 --device cuda:0` 启动；两个 remote split 复用同一进程，评测完成后已停止。
- 四组 evaluator 使用 `CUDA_VISIBLE_DEVICES=0 MUJOCO_GL=egl OMNIROBOAGENT_ROBOCASA_ROOT=/home/zzz/vla_code/robocasa PYTHONPATH=/home/zzz/vla_code/OmniRoboAgent/src:/home/zzz/vla_code/robocasa/Isaac-GR00T conda run -n groot --no-capture-output python -m omniroboagent run --config <run-config>`；local 额外设置 `OMNIROBOAGENT_GROOT_MODEL_PATH`。本次 `<run-config>` 保存在被 ignore 的 `runs/robocasa365_groot_split5_configs/`。
- GR00T remote healthcheck 连接 `127.0.0.1:5555`，确认 `checkpoint-240000`、action horizon 16、GR00T base commit `9d7d7a9` 和本地 custom policy source metadata。
- GR00T remote：`pretrain` 3/5 success、1546 environment steps、99 action chunks；`target` 2/5 success、1554 environment steps、99 action chunks。
- GR00T local：`pretrain` 2/5 success、1642 environment steps、105 action chunks；`target` 3/5 success、1419 environment steps、91 action chunks。
- 四组真实评测均为 5 episodes、5 result traces、0 exceptions、0 invalid actions；remote/local 的 task、episode、seed、RoboCasa commit `9a3a786` 和 robosuite commit `aaa8b9b` 完全一致。
- 本地运行 artifacts 位于 `runs/robocasa365_groot_{remote,local}_{pretrain,target}_5tasks/`，由 `/runs/` ignore 规则排除。
- 检查 43 个受影响文档中的本地 Markdown links、三个 AgentConfig/RunConfig 的实例化、assets 脚本两次幂等执行、submodule gitlink 和 `git diff --check`：通过。全仓扫描另会命中 `impl_docs/reference/rai-framework-analysis.md` 对未 checkout 外部 `rai/` source 的历史链接，该 reference 不属于本次修改。

## Remaining Work

- 本机没有可用 OpenPI checkpoint；真实 OpenPI policy smoke 尚未运行。
- 当前 GR00T checkpoint 依赖未提交的 `gr00t.model_moe_v1` 和 `data_config_mem_groot.py`；公开 base commit 不能独立复现模型加载。
- `episode_index` 当前表示 reset seed offset，不是官方 dataset scenario index；scenario sampling 和 aggregation 仍需与 RoboCasa 官方 evaluator 对齐。
- diffusion policy 未固定推理 RNG；相同 simulator seed 不保证 remote/local 的 action、chunk 或 success 完全一致。
