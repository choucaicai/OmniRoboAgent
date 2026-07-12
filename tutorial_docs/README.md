# Tutorials

OmniRoboAgent 的安装、配置、接口和 benchmark 使用文档。在线站点支持侧边栏导航和全文搜索，内容直接来自本目录 Markdown。

| Document | Content |
| --- | --- |
| [Quickstart](quickstart.md) | 安装、healthcheck、首次运行和输出文件 |
| [Configuration](configuration.md) | `AgentConfig`、`RunConfig` 和 `class_path` |
| [Interfaces](interfaces.md) | Core contracts、默认实现和数据边界 |
| [EB-ALFRED](eb_alfred.md) | 环境安装、display、smoke evaluation 和指标 |
| [Custom Components](custom_components.md) | 自定义 Planner、Verifier、SkillBackend、Environment 和 Pipeline |

这些文档描述当前实现。计划但尚未实现的能力仍以 [`impl_docs/plans/`](https://github.com/choucaicai/OmniRoboAgent/tree/master/impl_docs/plans) 为准。

当前可直接运行的是同步单环境 Runtime 和 EB-ALFRED language-skill 闭环。OpenPI client 已实现并经过 fake client 测试，但真实 policy server smoke、RoboCasa、async runtime、ROS2 和真机 integration 尚未完成。

## Local Preview

从项目根目录启动静态 server：

```bash
python -m http.server 8000 --directory tutorial_docs
```

然后访问 `http://127.0.0.1:8000`。Docsify 在浏览器中直接加载 Markdown，不需要单独 build。

## GitHub Pages

仓库包含 `.github/workflows/tutorial-docs-pages.yml`，会将 `tutorial_docs/` 作为完整 Pages artifact 发布。首次使用时，在 GitHub 仓库 `Settings -> Pages -> Build and deployment -> Source` 中选择 `GitHub Actions`，然后手动运行 workflow 或 push 本目录修改。
