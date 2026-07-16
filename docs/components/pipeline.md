# Pipeline

Pipeline 定义一次 Runtime step 中的调用顺序、组件输入、Verifier interpretation 和状态转换。它独立于 Agent Core，也不管理 episode 外层 loop。

## Contract

```python
class Pipeline:
    def step(
        self,
        agent: BaseAgent,
        environment: Environment,
        state: dict[str, Any],
    ) -> dict[str, Any]: ...

    def is_terminal(
        self,
        output: dict[str, Any],
        state: dict[str, Any],
    ) -> bool: ...
```

## `DirectPipeline`

用于每步重新规划的简单闭环：

```text
recall -> plan -> predict action -> execute -> verify -> memory update
```

它读取 Environment 提供的 `available_skills`，并根据 `EnvironmentVerifier` fields 产生 continue、retry、success 或 failure。

## `SkillExecutionPipeline`

用于长程 skill execution。它在 Runtime state 中维护显式 graph state：

```text
active_execution
planner_output
action
environment_result
verification
transition
completed_executions
failed_executions
execution_history
```

典型转换：

```text
completed    -> close execution -> plan next
in_progress  -> keep execution -> act again
failed       -> retry / replan / fallback / abort
uncertain    -> reverify without a new action
task_success -> terminate
```

`max_chunks_per_skill`、attempt/uncertain budgets、no-progress detection、replan budget 和 repeated/A-B-A loop detection 都由 Pipeline 的 structured state 决定。一次 `step()` 最多执行一次 Environment action。

## Action Chunk

两种通用执行模式：

```yaml
pipeline:
  class_path: omniroboagent.pipelines.DirectPipeline
  init_args:
    action_execution_mode: full
```

```yaml
pipeline:
  class_path: omniroboagent.pipelines.DirectPipeline
  init_args:
    action_execution_mode: receding_horizon
    execute_steps: 4
```

`full` 传递 `execute_steps=None`，`receding_horizon` 要求正整数。具体 chunk 语义由 Environment adapter 实现。

下一节：[Runtime](runtime.md)。
