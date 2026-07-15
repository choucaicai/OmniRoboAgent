from collections.abc import Mapping
from typing import Any

from omniroboagent.agent_core.agents.base import BaseAgent
from omniroboagent.environments.base import Environment
from omniroboagent.exceptions import PlannerOutputError, VerifierOutputError
from omniroboagent.pipelines.direct import DirectPipeline

EXECUTION_STATUSES = {"in_progress", "completed", "failed", "uncertain"}


class SkillExecutionPipeline(DirectPipeline):
    """Execute one active skill through explicit deterministic graph state."""

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
        # Kept for existing RunConfig compatibility. Completion now belongs to Verifier.
        self.planner_check_interval_chunks = planner_check_interval_chunks
        self.max_chunks_per_skill = max_chunks_per_skill

    def step(
        self,
        agent: BaseAgent,
        environment: Environment,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        self._ensure_graph_state(state)
        observation = state["observation"]
        available_skills = (
            observation.get("available_skills", [])
            if isinstance(observation, dict)
            else []
        )
        active_execution = state["active_execution"]
        previous_status = (
            str(active_execution.get("status", "planned"))
            if isinstance(active_execution, dict)
            else "idle"
        )
        planner_called = False
        replanned = False
        action: Any = None
        planner_output: Any = state.get("planner_output")
        verification_observation = observation
        reverify_only = (
            isinstance(active_execution, dict)
            and active_execution.get("status") == "uncertain"
        )

        try:
            if active_execution is None:
                planner_called = True
                planner_output = agent.plan(
                    {
                        "task": state["task"],
                        "observation": observation,
                        "step": state["step"],
                        "history": state.get("history", []),
                        "available_skills": available_skills,
                        "completed_executions": state["completed_executions"],
                        "failed_executions": state["failed_executions"],
                    }
                )
                active_execution = self._start_execution(
                    state, planner_output, available_skills
                )
                state["active_execution"] = active_execution
                state["planner_calls"] = int(state.get("planner_calls", 0)) + 1
                reverify_only = False

            if reverify_only:
                environment_result = state.get("environment_result")
                if not isinstance(environment_result, dict):
                    raise VerifierOutputError(
                        "uncertain execution requires the previous environment_result"
                    )
                verification_observation = state.get(
                    "verification_observation", observation
                )
            else:
                action = agent.predict_action(
                    {
                        "skill": active_execution["skill"],
                        "skill_id": active_execution.get("skill_id"),
                        "subtask": active_execution["subtask"],
                        "grounded_arguments": active_execution["grounded_arguments"],
                        "expected_outcome": active_execution["expected_outcome"],
                        "execution_id": active_execution["execution_id"],
                        "attempt_id": active_execution["attempt_id"],
                        "planner_output": active_execution["planner_output"],
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
                if not isinstance(environment_result, dict):
                    raise TypeError("Environment.execute() must return a dict")
                active_execution["chunk_count"] += 1
                active_execution["attempt_chunk_count"] += 1
                active_execution["status"] = "executed"
                state["verification_observation"] = observation
        except PlannerOutputError as error:
            planner_output = {"error": str(error)}
            active_execution = None
            state["active_execution"] = None
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
                "observation": verification_observation,
                "planner_output": planner_output,
                "active_execution": active_execution,
                "action": action,
                "environment_result": environment_result,
                "state": state,
            }
        )
        if not isinstance(verification, dict):
            raise TypeError("Verifier.verify() must return a dict")
        execution_status = self._execution_status(verification)
        transition_reason = str(
            verification.get("reason")
            or verification.get("env_feedback")
            or execution_status
        )
        if (
            execution_status == "in_progress"
            and isinstance(active_execution, dict)
            and self.max_chunks_per_skill is not None
            and active_execution["chunk_count"] >= self.max_chunks_per_skill
        ):
            execution_status = "failed"
            transition_reason = "chunk budget exhausted"
            verification = {
                **verification,
                "execution_status": "failed",
                "reason": transition_reason,
                "evidence": [
                    *self._evidence_summary(verification),
                    f"chunk_count={active_execution['chunk_count']}",
                ],
            }

        execution_id = (
            active_execution.get("execution_id")
            if isinstance(active_execution, dict)
            else None
        )
        attempt_id = (
            active_execution.get("attempt_id")
            if isinstance(active_execution, dict)
            else None
        )
        recovery_action: str | None = None
        termination_reason: str | None = None
        success = False
        decision = "continue"

        if verification.get("task_success"):
            if isinstance(active_execution, dict):
                active_execution["status"] = "completed"
                self._record_execution(
                    state,
                    active_execution,
                    verification,
                    "task_success",
                    completed=True,
                )
            state["active_execution"] = None
            next_status = "task_success"
            decision = "success"
            success = True
            termination_reason = "task_success"
        elif verification.get("environment_done"):
            if isinstance(active_execution, dict):
                active_execution["status"] = "failed"
                active_execution["failure_count"] += 1
                self._record_execution(
                    state,
                    active_execution,
                    verification,
                    transition_reason,
                    completed=False,
                )
            state["active_execution"] = None
            next_status = "failed"
            decision = "failure"
            termination_reason = "environment_done"
        elif execution_status == "completed":
            if isinstance(active_execution, dict):
                active_execution["status"] = "completed"
                self._record_execution(
                    state,
                    active_execution,
                    verification,
                    transition_reason,
                    completed=True,
                )
            state["active_execution"] = None
            next_status = "plan"
        elif execution_status == "failed":
            if isinstance(active_execution, dict):
                active_execution["status"] = "failed"
                active_execution["failure_count"] += 1
                self._record_execution(
                    state,
                    active_execution,
                    verification,
                    transition_reason,
                    completed=False,
                )
            state["active_execution"] = None
            next_status = "plan"
            recovery_action = "replan"
            replanned = True
            decision = "retry"
        elif execution_status == "uncertain":
            if not isinstance(active_execution, dict):
                raise VerifierOutputError(
                    "uncertain verification requires an active execution"
                )
            active_execution["status"] = "uncertain"
            active_execution["uncertain_count"] += 1
            next_status = "uncertain"
        else:
            if not isinstance(active_execution, dict):
                raise VerifierOutputError(
                    "in_progress verification requires an active execution"
                )
            active_execution["status"] = "in_progress"
            next_status = "in_progress"

        if next_status != "uncertain":
            state.pop("verification_observation", None)
        transition = {
            "execution_id": execution_id,
            "attempt_id": attempt_id,
            "previous_status": previous_status,
            "next_status": next_status,
            "transition_reason": transition_reason,
            "recovery_action": recovery_action,
        }
        state["planner_output"] = planner_output
        state["action"] = action
        state["environment_result"] = environment_result
        state["verification"] = verification
        state["transition"] = transition
        state["observation"] = environment_result.get("observation", observation)
        state["task_progress"] = float(verification.get("task_progress", 0.0))
        state["action_chunks"] = int(state.get("action_chunks", 0)) + int(
            action is not None
        )
        state["environment_steps"] = int(state.get("environment_steps", 0)) + int(
            environment_result.get("executed_steps", 0)
        )
        evidence_summary = self._evidence_summary(verification)
        state.setdefault("history", []).append(
            {
                "step": state["step"],
                "execution_id": execution_id,
                "attempt_id": attempt_id,
                "skill": (
                    active_execution.get("skill")
                    if isinstance(active_execution, dict)
                    else None
                ),
                "subtask": (
                    active_execution.get("subtask")
                    if isinstance(active_execution, dict)
                    else None
                ),
                "planner_called": planner_called,
                "previous_status": previous_status,
                "next_status": next_status,
                "transition_reason": transition_reason,
                "verifier_evidence": evidence_summary,
                "recovery_action": recovery_action,
                "last_action_success": verification.get("last_action_success"),
                "task_progress": verification.get("task_progress"),
                "executed_steps": environment_result.get("executed_steps", 0),
            }
        )

        event = {
            "planner_output": planner_output,
            "planner_called": planner_called,
            "replanned": replanned,
            "execution_id": execution_id,
            "attempt_id": attempt_id,
            "skill": (
                active_execution.get("skill")
                if isinstance(active_execution, dict)
                else None
            ),
            "subtask": (
                active_execution.get("subtask")
                if isinstance(active_execution, dict)
                else None
            ),
            "action": action,
            "environment_result": environment_result,
            "verification": verification,
            "previous_status": previous_status,
            "next_status": next_status,
            "transition_reason": transition_reason,
            "verifier_evidence": evidence_summary,
            "recovery_action": recovery_action,
            "transition": transition,
            "completed_executions": list(state["completed_executions"]),
            "failed_executions": list(state["failed_executions"]),
            "decision": decision,
        }
        agent.update(state, event)
        return {
            **event,
            "invalid_action": bool(environment_result.get("planner_error"))
            or not bool(verification.get("last_action_success", False)),
            "success": success,
            "termination_reason": termination_reason,
        }

    @staticmethod
    def _ensure_graph_state(state: dict[str, Any]) -> None:
        state.setdefault("active_execution", None)
        state.setdefault("completed_executions", [])
        state.setdefault("failed_executions", [])
        state.setdefault("execution_history", [])
        state.setdefault("execution_sequence", 0)
        if state["active_execution"] is not None and not isinstance(
            state["active_execution"], dict
        ):
            raise TypeError("state['active_execution'] must be a dict or None")
        for key in ("completed_executions", "failed_executions", "execution_history"):
            if not isinstance(state[key], list):
                raise TypeError(f"state[{key!r}] must be a list")

    def _start_execution(
        self,
        state: dict[str, Any],
        planner_output: Any,
        available_skills: Any,
    ) -> dict[str, Any]:
        if not isinstance(planner_output, dict):
            raise PlannerOutputError(
                "SkillExecutionPipeline requires a planner proposal dict"
            )
        skill = self._extract_skill(planner_output, available_skills)
        subtask = planner_output.get("subtask")
        if not isinstance(subtask, str) or not subtask.strip():
            raise PlannerOutputError("Planner proposal requires a non-empty subtask")
        grounded_arguments = planner_output.get("grounded_arguments")
        if not isinstance(grounded_arguments, dict):
            raise PlannerOutputError(
                "Planner proposal requires grounded_arguments dict"
            )
        expected_outcome = planner_output.get("expected_outcome")
        if not isinstance(expected_outcome, str) or not expected_outcome.strip():
            raise PlannerOutputError(
                "Planner proposal requires a non-empty expected_outcome"
            )
        skill_id = planner_output.get("skill_id")
        if skill_id is not None and (
            not isinstance(skill_id, int)
            or isinstance(skill_id, bool)
            or skill_id < 0
        ):
            raise PlannerOutputError("Planner proposal skill_id must be non-negative")

        sequence = int(state["execution_sequence"]) + 1
        state["execution_sequence"] = sequence
        execution_id = f"{state.get('session_id', 'execution')}:{sequence}"
        execution = {
            "execution_id": execution_id,
            "attempt_id": f"{execution_id}:attempt:1",
            "attempt_count": 1,
            "skill": skill,
            "skill_id": skill_id,
            "subtask": subtask.strip(),
            "grounded_arguments": grounded_arguments,
            "expected_outcome": expected_outcome.strip(),
            "status": "planned",
            "chunk_count": 0,
            "attempt_chunk_count": 0,
            "failure_count": 0,
            "uncertain_count": 0,
            "no_progress_count": 0,
            "last_progress_marker": None,
            "planner_output": planner_output,
        }
        state["execution_history"].append(
            {
                "execution_id": execution_id,
                "skill": skill,
                "skill_id": skill_id,
                "grounded_arguments": grounded_arguments,
                "expected_outcome": expected_outcome.strip(),
            }
        )
        return execution

    @staticmethod
    def _execution_status(verification: dict[str, Any]) -> str:
        status = verification.get("execution_status")
        if status is None:
            if verification.get("task_success"):
                return "completed"
            if verification.get("environment_done") or not verification.get(
                "last_action_success", False
            ):
                return "failed"
            return "in_progress"
        if status not in EXECUTION_STATUSES:
            raise VerifierOutputError(
                f"Verifier returned invalid execution_status: {status!r}"
            )
        return str(status)

    @staticmethod
    def _evidence_summary(verification: Mapping[str, Any]) -> list[str]:
        evidence = verification.get("evidence", [])
        if not isinstance(evidence, list):
            return [str(evidence)[:256]]
        return [str(item)[:256] for item in evidence[:3]]

    def _record_execution(
        self,
        state: dict[str, Any],
        execution: dict[str, Any],
        verification: dict[str, Any],
        reason: str,
        *,
        completed: bool,
    ) -> None:
        record = {
            "execution_id": execution["execution_id"],
            "attempt_id": execution["attempt_id"],
            "attempt_count": execution["attempt_count"],
            "skill": execution["skill"],
            "skill_id": execution.get("skill_id"),
            "subtask": execution["subtask"],
            "grounded_arguments": execution["grounded_arguments"],
            "expected_outcome": execution["expected_outcome"],
            "status": "completed" if completed else "failed",
            "chunk_count": execution["chunk_count"],
            "failure_count": execution["failure_count"],
            "reason": reason,
            "confidence": verification.get("confidence"),
            "evidence": self._evidence_summary(verification),
        }
        ledger = "completed_executions" if completed else "failed_executions"
        state[ledger].append(record)
