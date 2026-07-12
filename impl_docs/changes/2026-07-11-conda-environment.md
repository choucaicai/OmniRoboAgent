# Conda Environment

Date: 2026-07-11
Related plan: `impl_docs/plans/0001-eb-alfred-first-loop.md`

## Changed

- 创建 Conda 环境 `omniagent`。
- 将项目 Python 版本确定为 3.11。
- 暂未安装 OmniRoboAgent 项目依赖。

## Environment

- Path: `/home/zzz/anaconda3/envs/omniagent`
- Python: `3.11.15`
- pip: `26.1.2`

## Verification

```bash
conda run -n omniagent python --version
conda run -n omniagent python -c 'import sys; print(sys.executable); print(sys.version_info[:3])'
conda run -n omniagent pip --version
```

验证结果：Python 和 pip 均来自 `/home/zzz/anaconda3/envs/omniagent`，Python 主次版本为 `3.11`。

## Remaining Work

- 确认 Python package 管理工具。
- 创建 `pyproject.toml` 后安装项目开发依赖。

