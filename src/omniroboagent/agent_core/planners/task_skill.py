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
        active_skill = inputs.get("active_skill")
        return {
            "skill": task_name,
            "subtask": subtask,
            "execution_status": (
                "continue_subtask" if active_skill == task_name else "new_subtask"
            ),
        }
