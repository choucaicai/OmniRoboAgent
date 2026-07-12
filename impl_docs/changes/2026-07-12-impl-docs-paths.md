# Impl Docs Path References

Date: 2026-07-12
Related plan: N/A

## Changed

- 将项目自有 Markdown 中指向原 `docs/` 目录的路径更新为 `impl_docs/`。
- 保留 benchmark 子模块自身的 `docs/images/` 资源路径和文档术语中的 `docs/image preprocessors`。

## Files

- `AGENTS.md`
- `README.md`
- `rules/README.md`
- `tutorial_docs/`
- `impl_docs/`

## Verification

```bash
rg -n --glob '*.md' '(^|[^[:alnum:]_])docs/' .
```

验证结果：除本记录中的说明与命令外，仅保留 benchmark 子模块资源路径和 RAI 文档术语。

```bash
git diff --check
```

验证结果：通过，无 whitespace error。

## Remaining Work

- 无。
