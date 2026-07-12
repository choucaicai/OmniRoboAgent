# Benchmark Submodule And README

Date: 2026-07-12
Related plan: N/A

## Changed

- 为 `benchmarks/EmbodiedBench` 添加 `.gitmodules` URL 映射。
- 在根 README 说明 submodule 的 push 和 clone 行为。
- 在根 README 补充基础环境、EB-ALFRED、dataset、vLLM healthcheck 和 smoke evaluation 命令。
- 同步更新 `impl_docs/TODO.md` 状态。

## Files

- `.gitmodules`
- `README.md`
- `impl_docs/TODO.md`
- `impl_docs/changes/2026-07-12-benchmark-submodule-readme.md`

## Verification

```bash
git config -f .gitmodules --get-regexp '^submodule\..*\.(path|url)$'
git ls-files -s benchmarks/EmbodiedBench
git -C benchmarks/EmbodiedBench rev-parse HEAD
```

验证结果：submodule path 和 URL 可读取；主仓库以 mode `160000` 记录 `benchmarks/EmbodiedBench`，记录的 commit 与工作目录 HEAD 一致。

## Remaining Work

- 用户 push 前需要提交 `.gitmodules`、gitlink 和本次文档修改。
