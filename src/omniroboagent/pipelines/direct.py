from typing import Any

from omniroboagent.agent_core.agents.base import BaseAgent
from omniroboagent.environments.base import Environment
from omniroboagent.exceptions import PlannerOutputError
from omniroboagent.pipelines.base import Pipeline


class DirectPipeline(Pipeline):
    def __init__(
        self,
        action_execution_mode: str = "full",
        execute_steps: int | None = None,
    ) -> None:
        if action_execution_mode not in {"full", "receding_horizon"}:
            raise ValueError(
                "action_execution_mode must be 'full' or 'receding_horizon'"
            )
        if action_execution_mode == "receding_horizon" and (
            execute_steps is None or execute_steps <= 0
        ):
            raise ValueError("receding_horizon mode requires a positive execute_steps")
        self.action_execution_mode = action_execution_mode
        self.execute_steps = execute_steps

    def step(
        self,
        agent: BaseAgent,
        environment: Environment,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        observation = state["observation"]
        available_skills = (
            observation.get("available_skills", [])
            if isinstance(observation, dict)
            else []
        )
        planner_inputs = {
            "task": state["task"],
            "observation": observation,
            "step": state["step"],
            "history": state.get("history", []),
            "available_skills": available_skills,
            "memory_context": agent.recall(
                {
                    "phase": "plan",
                    "session_id": state.get("session_id"),
                    "task": state["task"],
                    "step": state["step"],
                }
            ),
        }

        try:
            planner_output = agent.plan(planner_inputs)
            skill = self._extract_skill(planner_output, available_skills)
            action = agent.predict_action(
                {
                    "skill": skill,
                    "planner_output": planner_output,
                    "observation": observation,
                    "task": state["task"],
                }
            )
            environment_result = environment.execute(
                action,
                execute_steps=(
                    self.execute_steps
                    if self.action_execution_mode == "receding_horizon"
                    else None
                ),
            )
        except PlannerOutputError as error:
            planner_output = {"error": str(error)}
            skill = None
            action = None
            environment_result = {
                "observation": observation,
                "done": False,
                "task_success": False,
                "task_progress": state.get("task_progress", 0.0),
                "last_action_success": False,
                "env_feedback": str(error),
                "planner_error": True,
            }

        verification = agent.verify(
            {
                "task": state["task"],
                "observation": observation,
                "planner_output": planner_output,
                "action": action,
                "environment_result": environment_result,
                "memory_context": agent.recall(
                    {
                        "phase": "verify",
                        "session_id": state.get("session_id"),
                        "task": state["task"],
                        "step": state["step"],
                    }
                ),
                "state": state,
            }
        )
        decision = self._decision(verification)
        event = {
            "planner_output": planner_output,
            "skill": skill,
            "action": action,
            "environment_result": environment_result,
            "verification": verification,
            "decision": decision,
        }
        agent.update(state, event)

        state["observation"] = environment_result.get("observation", observation)
        state["task_progress"] = verification.get("task_progress", 0.0)
        history = state.setdefault("history", [])
        history.append(
            {
                "step": state["step"],
                "skill": skill,
                "decision": decision,
                "last_action_success": verification.get("last_action_success"),
                "task_progress": verification.get("task_progress"),
                "env_feedback": verification.get("env_feedback", ""),
            }
        )

        return {
            **event,
            "invalid_action": not bool(verification.get("last_action_success", False)),
            "success": decision == "success",
            "termination_reason": (
                "task_success"
                if decision == "success"
                else "environment_done"
                if decision == "failure"
                else None
            ),
        }

    def is_terminal(self, output: dict[str, Any], state: dict[str, Any]) -> bool:
        return output.get("decision") in {"success", "failure"}

    @staticmethod
    def _extract_skill(planner_output: Any, available_skills: Any) -> Any:
        if isinstance(planner_output, dict):
            if "skill" not in planner_output:
                raise PlannerOutputError("Planner output dict is missing 'skill'")
            skill = planner_output["skill"]
        else:
            skill = planner_output

        if isinstance(available_skills, list) and available_skills:
            if skill not in available_skills:
                raise PlannerOutputError(
                    f"Planner selected an unavailable skill: {skill!r}"
                )
        return skill

    @staticmethod
    def _decision(verification: dict[str, Any]) -> str:
        if verification.get("task_success"):
            return "success"
        if verification.get("environment_done"):
            return "failure"
        if not verification.get("last_action_success", False):
            return "retry"
        return "continue"
