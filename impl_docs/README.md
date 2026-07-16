# Documentation

本目录维护 OmniRoboAgent 的架构、计划、任务状态和实际变更记录。

用户安装、配置和接口教程位于根目录 `docs/`。

## Directory Structure

```text
impl_docs/
├── README.md
├── TODO.md
├── architecture/
│   └── overview.md
├── reference/
│   └── rai-framework-analysis.md
├── plans/
│   ├── README.md
│   ├── 0001-eb-alfred-first-loop.md
│   ├── 0002-documentation-sync.md
│   ├── 0003-package-architecture.md
│   ├── 0004-agent-core-subpackages.md
│   ├── 0005-eval-environment-ownership.md
│   ├── 0006-robocasa365-evaluation.md
│   ├── 0007-skill-execution-state-graph.md
│   ├── 0008-composable-agent-base.md
│   ├── 0009-tiered-agent-memory.md
│   └── 0010-key-event-memory.md
└── changes/
    ├── README.md
    ├── 2026-07-11-conda-environment.md
    ├── 2026-07-11-documentation-foundation.md
    ├── 2026-07-11-modular-architecture-decisions.md
    ├── 2026-07-11-rai-framework-reference.md
    ├── 2026-07-12-language-skill-backend.md
    ├── 2026-07-12-first-vertical-slice.md
    ├── 2026-07-12-xvfb-eb-alfred-smoke.md
    ├── 2026-07-12-documentation-sync.md
    ├── 2026-07-12-package-architecture-implementation.md
    ├── 2026-07-13-agent-core-subpackages.md
    ├── 2026-07-14-eval-environment-ownership.md
    ├── 2026-07-15-robocasa365-evaluation-plan.md
    ├── 2026-07-15-robocasa365-evaluation-implementation.md
    ├── 2026-07-15-robocasa365-composite-evaluation.md
    ├── 2026-07-15-skill-execution-state-graph-design.md
    ├── 2026-07-15-skill-agent-memory-implementation-plan.md
    ├── 2026-07-15-skill-execution-state-graph-implementation.md
    ├── 2026-07-15-composable-agent-base.md
    ├── 2026-07-15-tiered-agent-memory.md
    ├── 2026-07-15-memory-context-integration.md
    ├── 2026-07-15-tiered-memory-robocasa-smoke.md
    └── 2026-07-16-key-event-memory.md
```

## Responsibilities

- `TODO.md`：项目总任务清单，只维护任务状态和对应文档链接。
- `architecture/`：描述稳定的系统边界、接口、数据流和依赖方向。
- `reference/`：记录第三方框架和外部系统的源码分析，作为设计参考，不代表本项目当前实现。
- `plans/`：记录尚未完成或正在执行的修改方案、任务拆分和验收条件。
- `changes/`：记录已经完成的实际修改、验证结果和遗留问题。

## Maintenance Workflow

1. 新需求先检查 `TODO.md` 是否已有对应事项。
2. 非简单修改先在 `plans/` 新建计划，并在 `TODO.md` 添加链接。
3. 开始实施时，将任务状态改为 `IN_PROGRESS`。
4. 完成代码和验证后，将状态改为 `DONE`。
5. 在 `changes/` 新建记录，写明实际修改和验证命令。
6. 若实现改变系统边界或接口，同时更新 `architecture/`。

## Status Values

- `TODO`：尚未开始。
- `IN_PROGRESS`：正在实施，同一阶段应尽量只有一个主要任务处于该状态。
- `BLOCKED`：存在明确阻塞，需要在任务后写明原因。
- `DONE`：实现、验证和变更记录均已完成。
