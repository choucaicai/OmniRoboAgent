# GitHub Pages Documentation

Status: DONE

## Goal

将 `docs/` 作为无需构建的 Markdown 文档站入口，并支持通过 GitHub Pages 浏览和搜索现有教程。

## Template Decision

- 使用 Docsify `4.13.1`，由浏览器直接渲染现有 Markdown。
- 不使用 Jekyll，避免为每个 Markdown 文件增加 front matter 和 layout。
- 不使用 MkDocs 或 VitePress，避免引入额外 build dependency 和生成目录。

## Scope

- 添加 Docsify HTML 入口、侧边栏、搜索和站点样式。
- 使用 GitHub Pages 原生 branch `/docs` 发布方式，不引入 build workflow。
- 修复发布后无法访问的跨目录相对链接。
- 记录本地预览和 GitHub Pages 启用步骤。

## Tasks

- [x] 创建 `docs/index.html`、`_sidebar.md`、`.nojekyll` 和样式。
- [x] 记录 GitHub Pages branch `/docs` 配置。
- [x] 更新教程首页、根 README 和跨目录链接。
- [x] 验证静态资源、Markdown 路由和响应式布局。

## Acceptance

- 本地 HTTP server 可以加载入口和全部教程 Markdown。
- 侧边栏导航和全文搜索配置存在。
- GitHub Pages 可以直接从 branch `/docs` 发布。
- GitHub Pages 中的仓库源码链接不依赖 artifact 外文件。

Change record: [`../changes/2026-07-12-github-pages-docs.md`](../changes/2026-07-12-github-pages-docs.md)
