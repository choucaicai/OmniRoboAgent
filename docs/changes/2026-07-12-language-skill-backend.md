# Language Skill Backend

Date: 2026-07-12
Related plan: `docs/plans/0001-eb-alfred-first-loop.md`

## Changed

- 创建最小 `omniroboagent` Python package 和 `pyproject.toml`。
- 定义不限制 action payload 类型的 `SkillBackend` contract。
- 实现 `LanguageSkillBackend`，原样返回 `inputs["skill"]`。
- 缺少 `skill` 字段时抛出包含输入要求的 `KeyError`。
- 增加对象身份保持和错误输入测试。
- 明确 EB-ALFRED 使用 Planner 选择 skill、backend 透明传递、Environment 执行的职责链。

## Files

- `pyproject.toml`
- `.gitignore`
- `src/omniroboagent/__init__.py`
- `src/omniroboagent/py.typed`
- `src/omniroboagent/contracts.py`
- `src/omniroboagent/backends/__init__.py`
- `src/omniroboagent/backends/skills/__init__.py`
- `src/omniroboagent/backends/skills/language.py`
- `tests/unit/test_language_skill_backend.py`
- `docs/architecture/overview.md`
- `docs/plans/0001-eb-alfred-first-loop.md`
- `docs/TODO.md`
- `docs/README.md`

## Verification

- `conda run -n omniagent python -m pip install -e '.[dev]'`：成功安装 editable package、pytest、Ruff 和 mypy。
- `conda run -n omniagent python -m pytest`：全部测试通过。
- `conda run -n omniagent ruff check src tests`：通过。
- `conda run -n omniagent ruff format --check src tests`：通过。
- `conda run -n omniagent mypy`：通过。

## Remaining Work

- 实现其他 core contracts、`DefaultAgent`、`DirectPipeline` 和 `SyncRuntime`。
- 增加 EB-ALFRED environment adapter 后验证真实 language skill 执行。
