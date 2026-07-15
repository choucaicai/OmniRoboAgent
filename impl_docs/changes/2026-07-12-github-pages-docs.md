# GitHub Pages Documentation

Date: 2026-07-12
Related plan: `impl_docs/plans/0005-github-pages-docs.md`

## Changed

- 选用 Docsify `4.13.1`，直接在浏览器中渲染现有 Markdown，无需 build step。
- 将用户文档目录从 `tutorial_docs/` 重命名为 GitHub Pages 原生支持的 `docs/`。
- 添加文档入口、侧边栏、全文搜索、响应式样式和 `.nojekyll`。
- 将跨目录链接改为 GitHub repository links，确保只发布 `docs/` 时仍可访问。
- 更新 README 和工程文档路径，记录 `master /docs` 发布方式。
- 面向读者的文档首页只保留使用导航和 Future Roadmap，不展示站点部署说明或内部实现状态。

## Files

- `docs/index.html`
- `docs/styles.css`
- `docs/_sidebar.md`
- `docs/.nojekyll`
- `docs/*.md`
- `README.md`
- `impl_docs/README.md`
- `impl_docs/TODO.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/plans/0005-github-pages-docs.md`

## Verification

```bash
python -m http.server 4173 --bind 127.0.0.1 --directory docs
chromium --headless --window-size=1440,1000 --screenshot=... http://127.0.0.1:4173/
chromium --headless --window-size=390,844 --screenshot=... http://127.0.0.1:4173/
chromium --headless --dump-dom http://127.0.0.1:4173/
```

验证结果：Docsify CDN assets 返回 HTTP 200；首页、全部 Markdown 和样式可读取；浏览器 DOM 包含侧边栏、搜索框和渲染后的教程内容；桌面与移动截图无溢出、遮挡或空白页面。

## Remaining Work

- 在 GitHub `Settings -> Pages` 中选择 `Deploy from a branch`、`master` 和 `/docs` 后首次发布。
