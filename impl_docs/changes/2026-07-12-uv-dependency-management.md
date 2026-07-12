# uv Dependency Management

Date: 2026-07-12
Related plan: `impl_docs/plans/0004-uv-dependency-management.md`

## Changed

- 使用 `uv + pyproject.toml + uv.lock` 管理 runtime、dev 和 optional dependencies。
- 基础依赖安装到 `omniagent`，EB-ALFRED 依赖只安装到独立 `omniagent-eb`。
- 增加 `dev` dependency group、`openpi` 和 `eb-alfred` extras，以及 PyTorch CPU index。
- 将 OpenPI client 固定 commit 改为 source archive URL，避免下载无关 Git submodules。
- 更新 README、教程、项目规则和任务状态中的安装命令。

## Files

- `pyproject.toml`
- `uv.lock`
- `README.md`
- `src/omniroboagent/backends/skills/openpi.py`
- `docs/quickstart.md`
- `docs/interfaces.md`
- `docs/eb_alfred.md`
- `rules/README.md`
- `impl_docs/TODO.md`
- `impl_docs/plans/0004-uv-dependency-management.md`

## Verification

```bash
uv lock --check
conda run -n omniagent uv pip install --python /home/zzz/anaconda3/envs/omniagent/bin/python --editable . --group dev
conda run -n omniagent uv pip install --python /home/zzz/anaconda3/envs/omniagent-eb/bin/python --editable '.[eb-alfred]'
conda run -n omniagent python -m pytest
conda run -n omniagent ruff check src tests
conda run -n omniagent ruff format --check src tests
conda run -n omniagent mypy
conda run -n omniagent-eb python -c 'from omniroboagent.integrations.embodiedbench import EBAlfredEnvironment, EBAlfredBenchmark'
```

验证结果：lockfile 解析 66 个 packages；`omniagent` 解析 21 个 packages；`omniagent-eb` 解析 43 个 packages；24 tests、Ruff、format 和 mypy 全部通过；EB-ALFRED adapter classes 可导入。

## Remaining Work

- 其他 benchmark 仅在实际接入时创建各自独立 Conda 环境和 optional dependency group。
