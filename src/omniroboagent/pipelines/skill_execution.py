from typing import Any

from omniroboagent.agent_core.agents.base import BaseAgent
from omniroboagent.environments.base import Environment
from omniroboagent.exceptions import PlannerOutputError
from omniroboagent.pipelines.direct import DirectPipeline


class SkillExecutionPipeline(DirectPipeline):
    """Execute a selected skill over one or more policy action chunks."""

    def __init__(
        self,
        action_execution_mode: str = "full",
        execute_steps: int | None = None,
        planner_check_interval_chunks: int = 1,
        max_chunks_per_skill: int | None = None,
    ) -> None:
        super().__init__(action_execution_mode, execute_steps)
        if planner_check_interval_chunks <= 0:
            raise ValueError("planner_check_interval_chunks must be positive")
        if max_chunks_per_skill is not None and max_chunks_per_skill <= 0:
            raise ValueError("max_chunks_per_skill must be positive")
        self.planner_check_interval_chunks = planner_check_interval_chunks
        self.max_chunks_per_skill = max_chunks_per_skill

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
        active_skill = state.get("active_skill")
        active_chunks = int(state.get("active_skill_chunks", 0))
        chunks_since_plan = int(state.get("chunks_since_plan", 0))
        budget_exhausted = (
            self.max_chunks_per_skill is not None
            and active_chunks >= self.max_chunks_per_skill
        )
        planner_called = (
            active_skill is None
            or chunks_since_plan >= self.planner_check_interval_chunks
            or budget_exhausted
        )
        replanned = False

        try:
            if planner_called:
                planner_output = agent.plan(
                    {
                        "task": state["task"],
                        "observation": observation,
                        "step": state["step"],
                        "history": state.get("history", []),
                        "available_skills": available_skills,
                        "active_skill": active_skill,
                        "active_subtask": state.get("active_subtask"),
                    }
                )
                proposed_skill = self._extract_skill(planner_output, available_skills)
                status = (
                    planner_output.get("execution_status", "new_subtask")
                    if isinstance(planner_output, dict)
                    else "new_subtask"
                )
                if budget_exhausted and status == "continue_subtask":
                    status = "replan_subtask"
                    if isinstance(planner_output, dict):
                        planner_output = {
                            **planner_output,
                            "execution_status": status,
                        }
                if status == "continue_subtask" and active_skill is not None:
                    skill = active_skill
                    subtask = state.get("active_subtask", active_skill)
                    reset_active_chunks = False
                else:
                    skill = proposed_skill
                    subtask = (
                        planner_output.get("subtask", skill)
                        if isinstance(planner_output, dict)
                        else skill
                    )
                    replanned = active_skill is not None and (
                        skill != active_skill
                        or subtask != state.get("active_subtask")
                        or status == "replan_subtask"
                    )
                    reset_active_chunks = True
                state["active_skill"] = skill
                state["active_subtask"] = subtask
                state["active_planner_output"] = planner_output
                if reset_active_chunks:
                    state["active_skill_chunks"] = 0
                state["chunks_since_plan"] = 0
                state["planner_calls"] = int(state.get("planner_calls", 0)) + 1
            else:
                skill = active_skill
                subtask = state.get("active_subtask", active_skill)
                planner_output = state.get(
                    "active_planner_output", {"skill": skill, "subtask": subtask}
                )

            action = agent.predict_action(
                {
                    "skill": skill,
                    "subtask": subtask,
                    "planner_output": planner_output,
                    "observation": observation,
                    "task": state["task"],
                    "step": state["step"],
                    "session_id": state.get("session_id"),
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
            subtask = None
            action = None
            environment_result = {
                "observation": observation,
                "done": False,
                "task_success": False,
                "task_progress": state.get("task_progress", 0.0),
                "last_action_success": False,
                "executed_steps": 0,
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
                "state": state,
            }
        )
        decision = self._decision(verification)
        event = {
            "planner_output": planner_output,
            "planner_called": planner_called,
            "replanned": replanned,
            "skill": skill,
            "subtask": subtask,
            "action": action,
            "environment_result": environment_result,
            "verification": verification,
            "decision": decision,
        }
        agent.update(state, event)

        state["observation"] = environment_result.get("observation", observation)
        state["task_progress"] = verification.get("task_progress", 0.0)
        state["action_chunks"] = int(state.get("action_chunks", 0)) + int(
            action is not None
        )
        state["environment_steps"] = int(state.get("environment_steps", 0)) + int(
            environment_result.get("executed_steps", 0)
        )
        state["active_skill_chunks"] = int(state.get("active_skill_chunks", 0)) + int(
            action is not None
        )
        state["chunks_since_plan"] = int(state.get("chunks_since_plan", 0)) + int(
            action is not None
        )
        state.setdefault("history", []).append(
            {
                "step": state["step"],
                "skill": skill,
                "subtask": subtask,
                "planner_called": planner_called,
                "decision": decision,
                "last_action_success": verification.get("last_action_success"),
                "task_progress": verification.get("task_progress"),
                "executed_steps": environment_result.get("executed_steps", 0),
                "env_feedback": verification.get("env_feedback", ""),
            }
        )

        if decision in {"retry", "success", "failure"}:
            state.pop("active_skill", None)
            state.pop("active_subtask", None)
            state.pop("active_planner_output", None)
            state["active_skill_chunks"] = 0
            state["chunks_since_plan"] = 0

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
