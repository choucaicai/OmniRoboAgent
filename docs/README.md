# OmniRoboAgent Documentation

OmniRoboAgent 的安装、配置、接口和 benchmark 使用文档。

| Document | Content |
| --- | --- |
| [Quickstart](quickstart.md) | 安装、healthcheck、首次运行和输出文件 |
| [Configuration](configuration.md) | `AgentConfig`、`RunConfig` 和 `class_path` |
| [Interfaces](interfaces.md) | Core contracts、默认实现和数据边界 |
| [Custom Components](custom_components.md) | 自定义 Planner、Verifier、SkillBackend、Environment 和 Pipeline |

## Benchmarks

### EB-ALFRED

[EB-ALFRED Evaluation](eb_alfred.md) 说明 EmbodiedBench/AI2-THOR 环境安装、Xvfb、smoke evaluation、输出指标和已验证结果。

### RoboCasa365

[RoboCasa365 Evaluation](robocasa365.md) 说明官方 assets、atomic/composite Agent、GR00T remote/local、OpenPI remote、真实 subtask 和 evaluation 结果。

## Future Roadmap

- Real OpenPI policy server validation
- Async runtime
- ROS2 and real-robot integration
