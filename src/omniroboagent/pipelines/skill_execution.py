import json
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
        max_attempts_per_execution: int = 2,
        max_uncertain_verifications: int = 2,
        max_no_progress_steps: int | None = None,
        max_replans: int | None = None,
        fallback_proposal: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(action_execution_mode, execute_steps)
        if planner_check_interval_chunks <= 0:
            raise ValueError("planner_check_interval_chunks must be positive")
        if max_chunks_per_skill is not None and max_chunks_per_skill <= 0:
            raise ValueError("max_chunks_per_skill must be positive")
        if max_attempts_per_execution <= 0:
            raise ValueError("max_attempts_per_execution must be positive")
        if max_uncertain_verifications <= 0:
            raise ValueError("max_uncertain_verifications must be positive")
        if max_no_progress_steps is not None and max_no_progress_steps <= 0:
            raise ValueError("max_no_progress_steps must be positive")
        if max_replans is not None and max_replans < 0:
            raise ValueError("max_replans must be non-negative")
        if fallback_proposal is not None and not isinstance(fallback_proposal, dict):
            raise ValueError("fallback_proposal must be a dict")
        # Kept for existing RunConfig compatibility. Completion now belongs to Verifier.
        self.planner_check_interval_chunks = planner_check_interval_chunks
        self.max_chunks_per_skill = max_chunks_per_skill
        self.max_attempts_per_execution = max_attempts_per_execution
        self.max_uncertain_verifications = max_uncertain_verifications
        self.max_no_progress_steps = max_no_progress_steps
        self.max_replans = max_replans
        self.fallback_proposal = (
            dict(fallback_proposal) if fallback_proposal is not None else None
        )

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
        planner_output: Any = (
            active_execution.get("planner_output")
            if isinstance(active_execution, dict)
            else state.get("planner_output")
        )
        verification_observation = observation
        control_failure_reason: str | None = None
        control_failure_kind: str | None = None
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
                loop_reason = active_execution.pop("_loop_reason", None)
                if loop_reason is not None:
                    control_failure_reason = str(loop_reason)
                    control_failure_kind = "loop"
                reverify_only = False

            if control_failure_reason is not None:
                environment_result = {
                    "observation": observation,
                    "done": False,
                    "task_success": False,
                    "task_progress": state.get("task_progress", 0.0),
                    "last_action_success": True,
                    "executed_steps": 0,
                    "env_feedback": control_failure_reason,
                    "execution_status": "failed",
                    "verification_reason": control_failure_reason,
                    "verification_confidence": 1.0,
                    "verification_evidence": [control_failure_reason],
                    "control_failure": control_failure_kind,
                }
            elif reverify_only:
                previous_environment_result = state.get("environment_result")
                if not isinstance(previous_environment_result, dict):
                    raise VerifierOutputError(
                        "uncertain execution requires the previous environment_result"
                    )
                environment_result = previous_environment_result
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
        if control_failure_reason is not None:
            execution_status = "failed"
            transition_reason = control_failure_reason
            verification = {
                **verification,
                "execution_status": "failed",
                "reason": transition_reason,
                "confidence": 1.0,
                "evidence": [control_failure_reason],
            }
        if (
            execution_status == "in_progress"
            and isinstance(active_execution, dict)
            and action is not None
        ):
            progress_marker = verification.get(
                "progress_marker", verification.get("task_progress")
            )
            if not active_execution["progress_marker_initialized"]:
                active_execution["last_progress_marker"] = progress_marker
                active_execution["no_progress_count"] = 0
                active_execution["progress_marker_initialized"] = True
            elif progress_marker == active_execution["last_progress_marker"]:
                active_execution["no_progress_count"] += 1
            else:
                active_execution["last_progress_marker"] = progress_marker
                active_execution["no_progress_count"] = 0
            if (
                self.max_no_progress_steps is not None
                and active_execution["no_progress_count"]
                >= self.max_no_progress_steps
            ):
                execution_status = "failed"
                transition_reason = "no progress detected"
                control_failure_kind = "no_progress"
                verification = {
                    **verification,
                    "execution_status": "failed",
                    "reason": transition_reason,
                    "evidence": [
                        *self._evidence_summary(verification),
                        f"no_progress_count={active_execution['no_progress_count']}",
                    ],
                }
        if (
            execution_status == "in_progress"
            and isinstance(active_execution, dict)
            and self.max_chunks_per_skill is not None
            and active_execution["chunk_count"] >= self.max_chunks_per_skill
        ):
            execution_status = "failed"
            transition_reason = "chunk budget exhausted"
            control_failure_kind = "chunk_budget"
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
                (
                    next_status,
                    decision,
                    termination_reason,
                    recovery_action,
                    replanned,
                ) = self._recover_execution(
                    state,
                    active_execution,
                    verification,
                    transition_reason,
                    available_skills,
                    allow_retry=control_failure_kind is None,
                    allow_replan=control_failure_kind != "loop",
                )
            else:
                (
                    next_status,
                    decision,
                    termination_reason,
                    recovery_action,
                    replanned,
                ) = self._next_recovery(
                    state,
                    verification,
                    available_skills,
                    allow_replan=True,
                )
        elif execution_status == "uncertain":
            if not isinstance(active_execution, dict):
                raise VerifierOutputError(
                    "uncertain verification requires an active execution"
                )
            active_execution["status"] = "uncertain"
            active_execution["uncertain_count"] += 1
            if (
                active_execution["uncertain_count"]
                >= self.max_uncertain_verifications
            ):
                transition_reason = "uncertain verification budget exhausted"
                verification = {
                    **verification,
                    "execution_status": "failed",
                    "reason": transition_reason,
                }
                (
                    next_status,
                    decision,
                    termination_reason,
                    recovery_action,
                    replanned,
                ) = self._recover_execution(
                    state,
                    active_execution,
                    verification,
                    transition_reason,
                    available_skills,
                    allow_retry=False,
                    allow_replan=True,
                )
            else:
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
            "next_execution_id": (
                state["active_execution"].get("execution_id")
                if isinstance(state["active_execution"], dict)
                else None
            ),
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
        state.setdefault("replan_count", 0)
        state.setdefault("fallback_count", 0)
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
            "progress_marker_initialized": False,
            "last_progress_marker": None,
            "planner_output": planner_output,
        }
        signature = self._execution_signature(execution)
        recent_signatures = [
            item.get("signature")
            for item in state["execution_history"]
            if isinstance(item, dict)
        ]
        if (
            len(recent_signatures) >= 2
            and signature == recent_signatures[-1] == recent_signatures[-2]
        ):
            execution["_loop_reason"] = "repeated execution loop detected"
        elif (
            len(recent_signatures) >= 2
            and signature == recent_signatures[-2]
            and signature != recent_signatures[-1]
        ):
            execution["_loop_reason"] = "A-B-A execution loop detected"
        state["execution_history"].append(
            {
                "execution_id": execution_id,
                "skill": skill,
                "skill_id": skill_id,
                "grounded_arguments": grounded_arguments,
                "expected_outcome": expected_outcome.strip(),
                "signature": signature,
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
        if not isinstance(status, str) or status not in EXECUTION_STATUSES:
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

    def _recover_execution(
        self,
        state: dict[str, Any],
        execution: dict[str, Any],
        verification: dict[str, Any],
        reason: str,
        available_skills: Any,
        *,
        allow_retry: bool,
        allow_replan: bool,
    ) -> tuple[str, str, str | None, str, bool]:
        execution["failure_count"] += 1
        if allow_retry and execution["attempt_count"] < self.max_attempts_per_execution:
            execution["attempt_count"] += 1
            execution["attempt_id"] = (
                f"{execution['execution_id']}:attempt:{execution['attempt_count']}"
            )
            execution["attempt_chunk_count"] = 0
            execution["status"] = "retrying"
            state["active_execution"] = execution
            return "retrying", "retry", None, "retry_current", False

        execution["status"] = "failed"
        self._record_execution(
            state,
            execution,
            verification,
            reason,
            completed=False,
        )
        state["active_execution"] = None
        return self._next_recovery(
            state,
            verification,
            available_skills,
            allow_replan=allow_replan,
        )

    def _next_recovery(
        self,
        state: dict[str, Any],
        verification: dict[str, Any],
        available_skills: Any,
        *,
        allow_replan: bool,
    ) -> tuple[str, str, str | None, str, bool]:
        if allow_replan and (
            self.max_replans is None or state["replan_count"] < self.max_replans
        ):
            state["replan_count"] += 1
            return "plan", "retry", None, "replan", True

        if self.fallback_proposal is not None and state["fallback_count"] == 0:
            try:
                fallback = self._start_execution(
                    state, self.fallback_proposal, available_skills
                )
            except PlannerOutputError:
                fallback = None
            if fallback is not None:
                loop_reason = fallback.pop("_loop_reason", None)
                if loop_reason is None:
                    fallback["status"] = "planned"
                    state["active_execution"] = fallback
                    state["fallback_count"] += 1
                    return "planned", "continue", None, "fallback", True
                fallback["status"] = "failed"
                fallback["failure_count"] += 1
                self._record_execution(
                    state,
                    fallback,
                    verification,
                    str(loop_reason),
                    completed=False,
                )

        state["active_execution"] = None
        return "aborted", "failure", "execution_aborted", "abort", False

    @staticmethod
    def _execution_signature(execution: Mapping[str, Any]) -> str:
        return json.dumps(
            {
                "skill": execution.get("skill"),
                "skill_id": execution.get("skill_id"),
                "grounded_arguments": execution.get("grounded_arguments"),
                "expected_outcome": execution.get("expected_outcome"),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
