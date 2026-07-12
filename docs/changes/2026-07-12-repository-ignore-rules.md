# Repository Ignore Rules

Date: 2026-07-12
Related plan: N/A

## Changed

- 保留 `.mypy_cache/`、`.pytest_cache/` 和 `.ruff_cache/` 的现有忽略规则。
- 增加 `reference_repo/`，避免提交本地参考仓库。
- 同步更新 `docs/TODO.md` 状态。

## Files

- `.gitignore`
- `docs/TODO.md`
- `docs/changes/2026-07-12-repository-ignore-rules.md`

## Verification

```bash
git check-ignore -v .mypy_cache .pytest_cache .ruff_cache reference_repo
```

验证结果：四个目录均由 `.gitignore` 对应规则忽略。

## Remaining Work

- 无。
