# Docsify Sidebar Routing Fix

Date: 2026-07-16
Related plan: `impl_docs/plans/0011-user-doc-information-architecture.md`

## Changed

- 将 `docs/_sidebar.md` 的全局导航 target 从相对路径改为 route-root 路径。
- 保留 `docs/index.html` 的 `relativePath: true`，使 Agent Core 和 component 页面内部的同目录、上级目录链接继续按当前文档位置解析。
- 修复从 `/agent_core/` 页面点击侧栏后生成 `/agent_core/agent_core/verifier` 等重复 route 的问题。
- 修复进入 404 route 后继续点击侧栏仍基于错误路径拼接、无法恢复的问题。

## Files

- `docs/_sidebar.md`
- `impl_docs/TODO.md`
- `impl_docs/changes/2026-07-16-docsify-sidebar-routing.md`

## Verification

- 修复前使用本地 Chromium 从 `#/agent_core/README` 检查侧栏 `Verifier`，复现其 `href=#/agent_core/agent_core/verifier`。
- 修复后使用 Playwright + system Chromium 实际点击侧栏：`Verifier` 进入 `#/agent_core/verifier`，`Runtime` 进入 `#/components/runtime`，页面均无 `404 - Not found`。
- 手动进入旧错误 route `#/agent_core/agent_core/verifier` 后点击侧栏“快速开始”，成功恢复到 `#/quickstart`。
- 检查全部 sidebar targets 对应的 Markdown 文件存在，并检查 scoped `git diff --check`。
- 未运行 Python unit tests；本次只修改 Docsify Markdown navigation 和文档状态，不修改 Python 行为。

## Remaining Work

- GitHub Pages 在 push 后需要等待部署完成；浏览器若缓存旧 `_sidebar.md`，需要刷新页面后再验证。
