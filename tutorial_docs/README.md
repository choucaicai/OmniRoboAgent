# Tutorials

| Document | Content |
| --- | --- |
| [Quickstart](quickstart.md) | 安装、healthcheck、首次运行和输出文件 |
| [Configuration](configuration.md) | `AgentConfig`、`RunConfig` 和 `class_path` |
| [Interfaces](interfaces.md) | Core contracts、默认实现和数据边界 |
| [EB-ALFRED](eb_alfred.md) | 环境安装、display、smoke evaluation 和指标 |
| [Custom Components](custom_components.md) | 自定义 Planner、Verifier、SkillBackend、Environment 和 Pipeline |

这些文档描述当前实现。计划但尚未实现的能力仍以 `docs/plans/` 为准。

当前可直接运行的是同步单环境 Runtime 和 EB-ALFRED language-skill 闭环。OpenPI client 已实现并经过 fake client 测试，但真实 policy server smoke、RoboCasa、async runtime、ROS2 和真机 integration 尚未完成。
