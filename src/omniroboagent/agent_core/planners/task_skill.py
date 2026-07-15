from collections.abc import Mapping
from typing import Any

from omniroboagent.agent_core.planners.base import Planner
from omniroboagent.exceptions import PlannerOutputError


class TaskSkillPlanner(Planner):
    """Use the current benchmark task as the policy skill."""

    def plan(self, inputs: dict[str, Any]) -> dict[str, Any]:
        task = inputs.get("task")
        task_name = task.get("name") if isinstance(task, Mapping) else task
        if not isinstance(task_name, str) or not task_name:
            raise PlannerOutputError("TaskSkillPlanner requires a task name")

        observation = inputs.get("observation")
        instruction = None
        if isinstance(observation, Mapping):
            instruction = observation.get("annotation.human.task_description")
        subtask = (
            instruction if isinstance(instruction, str) and instruction else task_name
        )
        return {
            "skill": task_name,
            "subtask": subtask,
            "grounded_arguments": {"task_name": task_name},
            "expected_outcome": f"Complete the benchmark task: {subtask}",
        }
