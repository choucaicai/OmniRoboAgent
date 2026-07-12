# Quickstart

## 1. Install

```bash
cd /home/zzz/vla_code/OmniRoboAgent
conda activate omniagent
uv pip install --python "$CONDA_PREFIX/bin/python" --editable . --group dev
```

依赖由 `uv + pyproject.toml + uv.lock` 管理。基础 `omniagent` 不安装 benchmark SDK；具体 benchmark 在测试时创建独立 Conda 环境。

## 2. Check vLLM

项目默认配置连接：

```text
http://127.0.0.1:8000/v1
model: Qwen3.5-9B
```

执行：

```bash
omniroboagent health --agent-config configs/agents/eb_alfred.yaml
```

成功结果包含：

```json
{
  "healthy": true,
  "planner": {
    "healthy": true,
    "model": "Qwen3.5-9B"
  },
  "skill_backend": {
    "healthy": true
  }
}
```

本地地址请求不使用系统 HTTP proxy，避免 `127.0.0.1` 被代理转发。

`base_url` 可以写为 `http://127.0.0.1:8000` 或带 `/v1` 的地址，backend 会统一规范为 `/v1`。vLLM 由用户启动和停止，OmniRoboAgent 只检查 `/v1/models` 并管理 HTTP client。

## 3. Run Tests

```bash
python -m pytest
ruff check src tests
ruff format --check src tests
mypy
```

默认测试不启动模型、AI2-THOR 或 OpenPI server。

## 4. Run EB-ALFRED

完成 [EB-ALFRED 环境安装](eb_alfred.md) 后执行：

```bash
bash scripts/run_eb_alfred_xvfb.sh
```

默认 smoke 配置运行：

- eval set：`base`
- episode：index `0`
- 每轮只执行一个 language skill
- 最大环境步骤：`30`
- 最大 invalid actions：`10`
- 输出目录：`runs/eb_alfred_smoke`

脚本默认使用 Conda 环境 `omniagent-eb` 和 `DISPLAY=:1`。若 display 不存在，它会启动 Xvfb；脚本退出时只清理自己启动的 Xvfb。可通过环境变量覆盖：

```bash
DISPLAY_ID=2 CONDA_ENV=omniagent-eb \
  bash scripts/run_eb_alfred_xvfb.sh configs/runs/eb_alfred_smoke.yaml
```

## 5. Outputs

```text
runs/eb_alfred_smoke/
├── episodes.jsonl
├── summary.json
└── traces/
    └── eb-alfred-base-0/
        ├── result.json
        └── trace.jsonl
```

每次使用相同 session id 重跑时会覆盖该 session 的 trace，不会把两次实验拼接到一起。

当前 `base[0]` 的已验证 smoke 结果是 `progress=0.3333`、14 steps，任务未成功完成。该结果用于验证闭环和记录路径，不是 Planner 效果基线。

输出当前不会自动保存 resolved YAML 和 package version。正式实验需要同时保留所用的 `configs/agents/*.yaml` 和 `configs/runs/*.yaml`。
