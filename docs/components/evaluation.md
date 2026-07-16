# Evaluation

Evaluation 层负责解析 task set、重复运行 episode、保存 resolved metadata 和聚合指标。Environment 只执行单个 episode 的 reset/action，不反向依赖 evaluator。

## Current Shape

当前没有全局 `Evaluator` base class。每个 benchmark runner 实现自己的 `run(agent, pipeline, runtime)`，并通过 RunConfig 的 `benchmark.class_path` 加载。

```yaml
benchmark:
  class_path: your_package.YourBenchmark
  init_args:
    output_dir: runs/example
```

CLI 会构造 Environment，并将它作为 `environment=` 注入 benchmark。若 RunConfig 没有 `benchmark`，则必须包含 `task`，CLI 直接调用一次 `runtime.run(...)`。

## Current Evaluators

| Evaluator | Responsibility |
| --- | --- |
| `EBAlfredBenchmark` | 遍历 selected episodes，保存 episode records 和 summary |
| `RoboCasa365Evaluator` | 解析 official task set/split、episode seed，保存 resolved config、per-task 和 aggregate metrics |

## Outputs

Benchmark output 通常包括：

```text
<output_dir>/
├── episodes.jsonl
├── summary.json
├── resolved_config.json    # evaluator 支持时
└── traces/
```

`resolved_config.json` 的覆盖范围由 evaluator 定义。当前 RoboCasa evaluator 会记录 task/split/seed、component classes、关键 limits、package versions、repository state 和 policy health；EB-ALFRED 仍需用户同时保留 AgentConfig 与 RunConfig。

不要把不同 benchmark 的 task schema 或 metrics 强行统一成一个固定结果类。需要跨 benchmark 比较时，应在上层明确指标映射和 aggregation 口径。

继续阅读 [Custom Components](../custom_components.md) 或具体 [Benchmarks](../README.md#benchmarks)。
