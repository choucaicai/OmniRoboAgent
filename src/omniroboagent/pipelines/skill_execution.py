import json
import re
import sys
from collections.abc import Mapping
from copy import deepcopy
from math import ceil
from typing import Any

from omniroboagent.agent_core.agents.base import BaseAgent
from omniroboagent.agent_core.recovery import (
    BoundedRecoveryRouter,
    FailureLabel,
    classify_failure,
)
from omniroboagent.backends.world_models.base import (
    normalize_world_model_prediction,
)
from omniroboagent.environments.base import Environment
from omniroboagent.exceptions import PlannerOutputError, VerifierOutputError
from omniroboagent.pipelines.direct import DirectPipeline

EXECUTION_STATUSES = {"in_progress", "completed", "failed", "uncertain"}
WORLD_MODEL_MODES = {"disabled", "shadow", "control", "gate"}
WORLD_MODEL_CONTROL_POLICIES = {"immediate", "corroborated"}
RECOVERY_STRATEGIES = {"legacy", "bounded"}
_MAX_WORLD_MODEL_RECORD_BYTES = 32 * 1024
_MAX_WORLD_MODEL_HORIZON_STEPS = 1_000_000
_MAX_ERROR_TYPE_CHARS = 128
_DYNAMIC_NODE_ID = re.compile(r"^dynamic:[a-z0-9][a-z0-9_-]{0,63}$")
_DYNAMIC_UNSAFE_TERMS = {
    "disable safety",
    "ignore safety",
    "harm person",
    "leave kitchen",
}


class SkillExecutionPipeline(DirectPipeline):
    """Execute one active skill through explicit deterministic graph state."""

    def __init__(
        self,
        action_execution_mode: str = "full",
        execute_steps: int | None = None,
        planner_check_interval_chunks: int = 8,
        max_chunks_per_skill: int | None = None,
        max_attempts_per_execution: int = 2,
        max_uncertain_verifications: int = 2,
        max_no_progress_steps: int | None = None,
        replan_on_no_progress: bool = False,
        replan_on_uncertain_exhaustion: bool = False,
        fallback_to_original_task_prompt: bool = False,
        max_replans: int | None = None,
        high_level_replan_limit: int | None = None,
        fallback_proposal: dict[str, Any] | None = None,
        world_model_mode: str = "disabled",
        world_model_control_policy: str = "immediate",
        recovery_enabled: bool = False,
        recovery_strategy: str = "legacy",
        max_recoveries_per_subtask: int = 1,
        max_recoveries_per_episode: int = 3,
        max_dynamic_nodes: int = 8,
        require_joint_adjudication: bool = False,
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
        if not isinstance(replan_on_no_progress, bool):
            raise ValueError("replan_on_no_progress must be a boolean")
        if not isinstance(replan_on_uncertain_exhaustion, bool):
            raise ValueError("replan_on_uncertain_exhaustion must be a boolean")
        if not isinstance(fallback_to_original_task_prompt, bool):
            raise ValueError(
                "fallback_to_original_task_prompt must be a boolean"
            )
        if max_replans is not None and high_level_replan_limit is not None:
            raise ValueError(
                "max_replans and high_level_replan_limit are mutually exclusive"
            )
        resolved_replan_limit = (
            high_level_replan_limit
            if high_level_replan_limit is not None
            else max_replans
        )
        if resolved_replan_limit is not None and resolved_replan_limit < 0:
            raise ValueError("high_level_replan_limit must be non-negative")
        if fallback_proposal is not None and not isinstance(fallback_proposal, dict):
            raise ValueError("fallback_proposal must be a dict")
        if world_model_mode not in WORLD_MODEL_MODES:
            raise ValueError(
                "world_model_mode must be 'disabled', 'shadow', 'control', or 'gate'"
            )
        if world_model_control_policy not in WORLD_MODEL_CONTROL_POLICIES:
            raise ValueError(
                "world_model_control_policy must be 'immediate' or 'corroborated'"
            )
        if not isinstance(recovery_enabled, bool):
            raise ValueError("recovery_enabled must be a boolean")
        if recovery_strategy not in RECOVERY_STRATEGIES:
            raise ValueError("recovery_strategy must be 'legacy' or 'bounded'")
        if not isinstance(max_dynamic_nodes, int) or isinstance(max_dynamic_nodes, bool):
            raise ValueError("max_dynamic_nodes must be a positive integer")
        if max_dynamic_nodes <= 0:
            raise ValueError("max_dynamic_nodes must be a positive integer")
        if not isinstance(require_joint_adjudication, bool):
            raise ValueError("require_joint_adjudication must be a boolean")
        # Kept for existing RunConfig compatibility. Completion now belongs to Verifier.
        self.planner_check_interval_chunks = planner_check_interval_chunks
        self.max_chunks_per_skill = max_chunks_per_skill
        self.max_attempts_per_execution = max_attempts_per_execution
        self.max_uncertain_verifications = max_uncertain_verifications
        self.max_no_progress_steps = max_no_progress_steps
        self.replan_on_no_progress = replan_on_no_progress
        self.replan_on_uncertain_exhaustion = replan_on_uncertain_exhaustion
        self.fallback_to_original_task_prompt = fallback_to_original_task_prompt
        self.max_replans = resolved_replan_limit
        self.high_level_replan_limit = resolved_replan_limit
        self.fallback_proposal = (
            dict(fallback_proposal) if fallback_proposal is not None else None
        )
        self.world_model_mode = world_model_mode
        self.world_model_control_policy = world_model_control_policy
        self.recovery_enabled = recovery_enabled
        self.recovery_strategy = recovery_strategy
        self.max_dynamic_nodes = max_dynamic_nodes
        self.require_joint_adjudication = require_joint_adjudication
        self.recovery_router = BoundedRecoveryRouter(
            max_per_subtask=max_recoveries_per_subtask,
            max_per_episode=max_recoveries_per_episode,
        )

    def step(
        self,
        agent: BaseAgent,
        environment: Environment,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        self._ensure_graph_state(state)
        self._attach_episode_task_graph(agent, state)
        reference_subtasks = self._reference_subtasks(state.get("task_graph"))
        state["reference_subtasks"] = reference_subtasks
        self._capture_original_task_prompt(state, state["observation"])
        state["latest_recovery_memory"] = None
        planner_replan = bool(state.pop("pending_replan", False))
        observation = state["observation"]
        self._capture_temporal_visual_frame(state, observation)
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
        policy_inference: dict[str, Any] = {}
        policy_exchange: dict[str, Any] = {}
        planner_trace_inputs: dict[str, Any] | None = None
        verifier_trace_inputs: dict[str, Any] | None = None
        verifier_called = False
        recovery_record: dict[str, Any] | None = None
        planner_output: Any = (
            active_execution.get("planner_output")
            if isinstance(active_execution, dict)
            else state.get("planner_output")
        )
        verification_observation = observation
        world_model_record: dict[str, Any] | None = None
        causal_failure: dict[str, Any] | None = None
        control_failure_reason: str | None = None
        control_failure_kind: str | None = None
        repeat_pattern: str | None = None
        reverify_only = (
            isinstance(active_execution, dict)
            and active_execution.get("status") == "uncertain"
        )
        planner_checkpoint_due = self._planner_checkpoint_due(
            state, active_execution, planner_replan
        )

        try:
            if planner_checkpoint_due:
                planner_called = True
                planner_memory = agent.recall(
                    {
                        "phase": "plan",
                        "session_id": state.get("session_id"),
                        "task": state["task"],
                        "step": state["step"],
                    }
                )
                planner_inputs = {
                    "task": state["task"],
                    "observation": observation,
                    "step": state["step"],
                    "history": (
                        self._history_without_world_model(state.get("history", []))
                        if self.world_model_mode == "shadow"
                        else state.get("history", [])
                    ),
                    "available_skills": available_skills,
                    "completed_executions": state["completed_executions"],
                    "reference_subtasks": reference_subtasks,
                    "planner_current_subtask": (
                        active_execution.get("subtask")
                        if isinstance(active_execution, Mapping)
                        else None
                    ),
                    "failed_executions": state["failed_executions"],
                    "memory_context": (
                        self._mapping_without_world_model(planner_memory)
                        if self.world_model_mode == "shadow"
                        else planner_memory
                    ),
                    "verifier_result": state.get("verification"),
                    "recovery_memory": list(state.get("recovery_memory", [])),
                    "recovery_context": {
                        "verifier": state.get("verification"),
                        "memory": list(state.get("recovery_memory", [])),
                        "is_replan": planner_replan,
                        "recovery_action": (
                            state["transition"].get("recovery_action")
                            if isinstance(state.get("transition"), Mapping)
                            else None
                        ),
                        "partial_recovery_handoff": state.get(
                            "horizon_recovery_handoff"
                        ),
                        "recovery_reconciliation": state.get(
                            "horizon_recovery_reconciliation"
                        ),
                    },
                    "critical_unknowns": (
                        state.get("horizon_recovery_reconciliation", {}).get(
                            "critical_unknowns", []
                        )
                        if isinstance(
                            state.get("horizon_recovery_reconciliation"), Mapping
                        )
                        else []
                    ),
                }
                planner_trace_inputs = self._planner_trace_inputs(planner_inputs)
                planner_output = agent.plan(planner_inputs)
                state["last_planner_inputs"] = planner_trace_inputs
                planner_decision = planner_output.get("decision", "update") if isinstance(planner_output, Mapping) else "update"
                if planner_decision == "keep":
                    if not isinstance(active_execution, dict):
                        raise PlannerOutputError("Planner cannot keep without an active execution")
                    active_execution["planner_output"] = dict(planner_output)
                elif planner_decision == "update":
                    canonical_output = dict(planner_output)
                    if (
                        not planner_replan
                        and isinstance(active_execution, dict)
                        and self._same_execution_semantics(
                            active_execution, canonical_output, available_skills
                        )
                    ):
                        active_execution["planner_output"] = canonical_output
                        planner_output = canonical_output
                    else:
                        previous_failure = self._equivalent_no_progress_failure(
                            state, canonical_output, available_skills
                        ) if planner_replan else None
                        fallback = self._start_original_task_prompt_fallback(
                            state, previous_failure, "equivalent no-progress replan", available_skills
                        ) if previous_failure is not None else None
                        if fallback is not None:
                            active_execution = fallback
                            planner_output = active_execution["planner_output"]
                        else:
                            active_execution = self._start_execution(
                                state, canonical_output, available_skills
                            )
                            planner_output = active_execution["planner_output"]
                            state["active_execution"] = active_execution
                else:
                    raise PlannerOutputError(f"Invalid planner decision: {planner_decision!r}")
                state["last_planner_checkpoint_chunks"] = int(
                    state.get("executed_action_chunks", 0)
                )
                state["planner_calls"] = int(state.get("planner_calls", 0)) + 1
                if planner_replan:
                    state["replan_planner_calls"] = (
                        int(state.get("replan_planner_calls", 0)) + 1
                    )
                repeat_pattern = active_execution.pop("_repeat_pattern", None)
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
                if self.world_model_mode == "shadow":
                    previous_world_model = state.get("world_model")
                    if type(previous_world_model) is dict:
                        world_model_record = self._reused_world_model_record(
                            previous_world_model,
                            current_step=self._bounded_step_count(
                                state["step"], default=0, allow_zero=True
                            ),
                        )
            else:
                action_inputs = {
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
                    "reference_subtasks": reference_subtasks,
                    "planner_current_subtask": active_execution["subtask"],
                    "original_task_prompt": state.get("original_task_prompt"),
                    "instruction_fallback": active_execution.get("instruction_fallback"),
                }
                action = self._predict_action(agent, action_inputs, state)
                skill_backend = getattr(agent, "skill_backend", None)
                policy_inference_value = getattr(skill_backend, "last_inference", {})
                policy_inference = (
                    dict(policy_inference_value)
                    if isinstance(policy_inference_value, Mapping)
                    else {}
                )
                policy_exchange_value = getattr(skill_backend, "last_exchange", {})
                policy_exchange = (
                    dict(policy_exchange_value)
                    if isinstance(policy_exchange_value, Mapping)
                    else {}
                )
                if self.world_model_mode in {"shadow", "control", "gate"}:
                    world_model_record = self._predict_world_model(
                        agent=agent,
                        action=action,
                        observation=observation,
                        state=state,
                        active_execution=active_execution,
                    )
                    if world_model_record.get("model_called") is True:
                        state["world_model_calls"] = (
                            int(state.get("world_model_calls", 0)) + 1
                        )
                        prediction = world_model_record.get("prediction")
                        metadata = (
                            prediction.get("metadata")
                            if isinstance(prediction, Mapping)
                            else None
                        )
                        latency = (
                            metadata.get("endpoint_latency_seconds")
                            if isinstance(metadata, Mapping)
                            else None
                        )
                        if isinstance(latency, (int, float)) and not isinstance(
                            latency, bool
                        ):
                            state["world_model_latency_seconds"] = float(
                                state.get("world_model_latency_seconds", 0.0)
                            ) + float(latency)
                state["candidate_action_chunks"] += 1
                gate_accepted = (
                    self.world_model_mode != "gate"
                    or self._world_model_accepts(world_model_record)
                )
                if gate_accepted:
                    state["accepted_action_chunks"] += 1
                    set_action_context = getattr(
                        environment, "set_action_context", None
                    )
                    if callable(set_action_context):
                        task_context = state.get("task")
                        set_action_context(
                            {
                                "task": (
                                    task_context.get("name")
                                    if isinstance(task_context, Mapping)
                                    else None
                                ),
                                "episode": (
                                    task_context.get("episode_index", 0)
                                    if isinstance(task_context, Mapping)
                                    else 0
                                ),
                                "seed": (
                                    task_context.get("seed", 0)
                                    if isinstance(task_context, Mapping)
                                    else 0
                                ),
                                "candidate_chunk_index": int(
                                    state.get("candidate_action_chunks", 0)
                                ),
                                "execution_id": active_execution["execution_id"],
                                "attempt_id": active_execution["attempt_id"],
                                "episode_attempt_id": state.get("episode_attempt_id"),
                                "fingerprint": state.get("run_fingerprint"),
                                "artifact_dir": state.get("artifact_dir"),
                            }
                        )
                    execute_steps = (
                        self.execute_steps
                        if self.action_execution_mode == "receding_horizon"
                        else None
                    )
                    recovery_execute_steps = state.pop(
                        "next_recovery_execute_steps", None
                    )
                    if isinstance(recovery_execute_steps, int):
                        execute_steps = min(
                            execute_steps or recovery_execute_steps,
                            recovery_execute_steps,
                        )
                    remaining = state.get("remaining_environment_steps")
                    if isinstance(remaining, int):
                        execute_steps = min(execute_steps or remaining, remaining)
                    environment_result = environment.execute(
                        action,
                        execute_steps=execute_steps,
                    )
                    if not isinstance(environment_result, dict):
                        raise TypeError("Environment.execute() must return a dict")
                    if environment_result.get("action_clipped") is True:
                        state["action_clipped_chunks"] = (
                            int(state.get("action_clipped_chunks", 0)) + 1
                        )
                        state["action_clipped_value_count"] = int(
                            state.get("action_clipped_value_count", 0)
                        ) + int(environment_result.get("action_clipped_value_count", 0))
                        fields = set(state.get("action_clipped_fields", []))
                        reported_fields = environment_result.get(
                            "action_clipped_fields", []
                        )
                        if isinstance(reported_fields, list):
                            fields.update(str(field) for field in reported_fields)
                        state["action_clipped_fields"] = sorted(fields)
                        state["max_preclip_range_excess"] = max(
                            float(state.get("max_preclip_range_excess", 0.0)),
                            float(
                                environment_result.get("max_preclip_range_excess", 0.0)
                            ),
                        )
                    observation_sequence = self._ingest_observation_sequence(
                        agent, environment_result, state
                    )
                    if world_model_record is not None:
                        causal_failure = self._observe_world_model_transition(
                            agent=agent,
                            state=state,
                            active_execution=active_execution,
                            observation_sequence=observation_sequence,
                            environment_result=environment_result,
                        )
                    if world_model_record is not None:
                        world_model_record = self._bounded_world_model_record(
                            {
                                **world_model_record,
                                "executed_steps": self._bounded_step_count(
                                    environment_result.get("executed_steps", 0),
                                    default=0,
                                    allow_zero=True,
                                ),
                                "environment_executed": True,
                                **(
                                    {"first_causal_failure": causal_failure}
                                    if causal_failure is not None
                                    else {}
                                ),
                            }
                        )
                    active_execution["chunk_count"] += 1
                    active_execution["attempt_chunk_count"] += 1
                    active_execution["status"] = "executed"
                    state["verification_observation"] = observation
                else:
                    state["rejected_action_chunks"] += 1
                    active_execution["status"] = "gate_rejected"
                    active_execution["candidate_rejection_count"] += 1
                    gate_reason = self._world_model_gate_reason(world_model_record)
                    environment_result = {
                        "observation": observation,
                        "task_success": False,
                        "task_progress": state.get("task_progress", 0.0),
                        "last_action_success": False,
                        "done": False,
                        "executed_steps": 0,
                        "environment_steps": state.get("environment_steps", 0),
                        "env_feedback": gate_reason,
                        "verification_reason": gate_reason,
                        "verification_confidence": 1.0,
                        "verification_evidence": [
                            "Cosmos action gate rejected candidate"
                        ],
                        "action_gate_rejected": True,
                        "recovery_class": "candidate_rejected",
                    }
        except PlannerOutputError as error:
            protocol_error = str(error).startswith("planner_protocol_error:")
            planner_output = {
                "error": str(error),
                "planner_protocol_error": protocol_error,
            }
            active_execution = None
            state["active_execution"] = None
            state["planner_protocol_error"] = protocol_error
            environment_result = {
                "observation": observation,
                "done": False,
                "task_success": False,
                "task_progress": state.get("task_progress", 0.0),
                "last_action_success": False,
                "executed_steps": 0,
                "env_feedback": str(error),
                "planner_error": True,
                "planner_protocol_error": protocol_error,
            }

        authoritative_success = self._authoritative_task_success(environment_result)
        action_gate_rejected = bool(environment_result.get("action_gate_rejected"))
        verifier_memory: dict[str, Any] = {}
        if not authoritative_success and not action_gate_rejected:
            verifier_memory = agent.recall(
                {
                    "phase": "verify",
                    "session_id": state.get("session_id"),
                    "task": state["task"],
                    "step": state["step"],
                    "execution_id": (
                        active_execution.get("execution_id")
                        if isinstance(active_execution, dict)
                        else None
                    ),
                }
            )
        post_action_observation = environment_result.get("observation", observation)
        state["observation"] = post_action_observation
        self._capture_temporal_visual_frame(state, post_action_observation)
        verification_inputs = {
            "task": state["task"],
            "observation": post_action_observation,
            "pre_action_observation": verification_observation,
            "post_action_observation": post_action_observation,
            "planner_output": planner_output,
            "active_execution": active_execution,
            "action": action,
            "environment_result": environment_result,
            "memory_context": (
                self._mapping_without_world_model(verifier_memory)
                if self.world_model_mode == "shadow"
                else verifier_memory
            ),
            "state": (
                self._state_without_world_model(state)
                if self.world_model_mode == "shadow"
                else state
            ),
        }
        verifier_trace_inputs = self._verifier_trace_inputs(verification_inputs)
        should_verify = getattr(
            getattr(agent, "verifier", None), "should_verify", None
        )
        verification_due = (
            bool(should_verify(verification_inputs))
            if callable(should_verify)
            else True
        )
        if authoritative_success:
            verification = {
                "task_success": True,
                "task_progress": 1.0,
                "last_action_success": True,
                "environment_done": True,
                "execution_status": "completed",
                "reason": "authoritative environment success",
                "confidence": 1.0,
                "evidence": ["environment success=true"],
            }
        elif isinstance(active_execution, Mapping) and active_execution.get("instruction_fallback"):
            verification = {
                "task_success": False,
                "task_progress": float(state.get("task_progress", 0.0)),
                "last_action_success": bool(environment_result.get("last_action_success", True)),
                "environment_done": bool(environment_result.get("done", False)),
                "execution_status": (
                    "in_progress"
                    if environment_result.get("last_action_success", True)
                    else "failed"
                ),
                "progress_assessment": "unknown",
                "reason": "original Xiaomi task prompt fallback active",
                "confidence": 1.0,
                "evidence": ["planner and semantic verifier are bypassed during fallback"],
                "verification_source": "original_task_prompt_fallback",
            }
        elif action_gate_rejected:
            verification = {
                "task_success": False,
                "task_progress": float(state.get("task_progress", 0.0)),
                "last_action_success": True,
                "environment_done": False,
                "execution_status": "in_progress",
                "reason": str(environment_result.get("env_feedback")),
                "confidence": 1.0,
                "evidence": ["candidate rejected before environment execution"],
                "recovery_class": "candidate_rejected",
            }
        elif not verification_due:
            verification = {
                "task_success": False,
                "task_progress": float(environment_result.get("task_progress", 0.0)),
                "last_action_success": bool(
                    environment_result.get("last_action_success", True)
                ),
                "environment_done": False,
                "execution_status": "in_progress",
                "progress_assessment": "unknown",
                "reason": "semantic verifier interval not due",
                "confidence": 1.0,
                "evidence": [],
                "verification_source": "interval_not_due",
                "verifier_scheduled": False,
                "action_summary_status": "interval_not_due",
            }
        else:
            state["verifier_calls"] += 1
            verifier_called = True
            verification = agent.verify(verification_inputs)
            if not isinstance(verification, dict):
                raise TypeError("Verifier.verify() must return a dict")
            # The environment owns task completion; verifier output cannot end an
            # episode while the simulator still reports failure or continuation.
            verification = {
                **verification,
                "environment_done": bool(environment_result.get("done", False)),
                "task_success": False,
            }
            if self.require_joint_adjudication:
                verification = self._adjudicate_verifier_candidate(
                    agent=agent,
                    state=state,
                    active_execution=active_execution,
                    verification_inputs=verification_inputs,
                    verification=verification,
                )
        causal_failure_detected = (
            causal_failure is not None and causal_failure.get("detected") is True
        )
        if causal_failure_detected:
            state["failure_detections"] = int(state.get("failure_detections", 0)) + 1
        if (
            self.world_model_mode == "control"
            and self.world_model_control_policy == "immediate"
            and causal_failure_detected
            and not authoritative_success
            and not bool(environment_result.get("done", False))
        ):
            cause = str(causal_failure.get("cause") or "world_model_mismatch")
            causal_evidence = causal_failure.get("evidence", [])
            if not isinstance(causal_evidence, list):
                causal_evidence = [str(causal_evidence)]
            verification = {
                **verification,
                "execution_status": "failed",
                "reason": f"first causal failure detected: {cause}",
                "evidence": [str(item)[:256] for item in causal_evidence[:4]],
                "confidence": float(causal_failure.get("confidence", 0.0)),
                "recovery_class": cause,
                "first_causal_failure": causal_failure,
            }
        execution_status = self._execution_status(verification)
        graph_transition: dict[str, Any] | None = None
        recovery_class = verification.get("recovery_class")
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
            and verifier_called
            and verification.get("verification_source") != "deferred"
            and (
                not self.require_joint_adjudication
                or verification.get("joint_transition_accepted") is True
            )
        ):
            progress_assessment = verification.get("progress_assessment", "unknown")
            if progress_assessment not in {"advanced", "unchanged", "regressed", "unknown"}:
                progress_assessment = "unknown"
            if progress_assessment == "advanced":
                active_execution["no_progress_count"] = 0
                active_execution["progress_marker_initialized"] = True
                active_execution["last_progress_marker"] = progress_assessment
            elif progress_assessment in {"unchanged", "regressed"}:
                if active_execution["progress_marker_initialized"]:
                    active_execution["no_progress_count"] += 1
                else:
                    active_execution["progress_marker_initialized"] = True
                    active_execution["no_progress_count"] = 0
                active_execution["last_progress_marker"] = progress_assessment
            if (
                self.max_no_progress_steps is not None
                and active_execution["no_progress_count"] >= self.max_no_progress_steps
            ):
                execution_status = "failed"
                transition_reason = "no progress detected"
                control_failure_kind = "no_progress"
                recovery_class = (
                    "wrong_plan" if self.replan_on_no_progress else "stalled"
                )
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
            recovery_class = "stalled"
            verification = {
                **verification,
                "execution_status": "failed",
                "reason": transition_reason,
                "evidence": [
                    *self._evidence_summary(verification),
                    f"chunk_count={active_execution['chunk_count']}",
                ],
            }

        if execution_status == "failed" and recovery_class is None:
            recovery_class = (
                "wrong_plan" if verification.get("wrong_plan") is True else "stalled"
            )
        if recovery_class is not None:
            verification = {**verification, "recovery_class": recovery_class}

        failure_label: FailureLabel | None = None
        if execution_status == "failed":
            failure_label = classify_failure(
                transition_reason,
                verification,
                environment_result,
                causal_failure,
            )
            verification = {
                **verification,
                "failure_label": failure_label.to_dict(),
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
                    allow_retry=recovery_class == "stalled",
                    allow_replan=recovery_class == "wrong_plan",
                    environment_result=environment_result,
                    action=action,
                    failure_label=failure_label,
                )
            else:
                if self.recovery_enabled:
                    self._record_recovery_memory(
                        state,
                        None,
                        verification,
                        transition_reason,
                        environment_result=environment_result,
                        action=action,
                        failure_label=failure_label,
                    )
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
            if active_execution["uncertain_count"] >= self.max_uncertain_verifications:
                transition_reason = "uncertain verification budget exhausted"
                recovery_class = (
                    "wrong_plan"
                    if self.replan_on_uncertain_exhaustion
                    else "stalled"
                )
                verification = {
                    **verification,
                    "execution_status": "failed",
                    "reason": transition_reason,
                    "recovery_class": recovery_class,
                }
                failure_label = classify_failure(
                    transition_reason,
                    verification,
                    environment_result,
                    causal_failure,
                )
                verification = {
                    **verification,
                    "failure_label": failure_label.to_dict(),
                }
                fallback = self._start_original_task_prompt_fallback(
                    state, active_execution, transition_reason, available_skills
                )
                if fallback is not None:
                    active_execution["status"] = "failed"
                    active_execution["failure_count"] += 1
                    if self.recovery_enabled:
                        self._record_recovery_memory(
                            state,
                            active_execution,
                            verification,
                            transition_reason,
                            environment_result=environment_result,
                            action=action,
                            failure_label=failure_label,
                        )
                    self._record_execution(
                        state, active_execution, verification, transition_reason, completed=False
                    )
                    next_status, decision, termination_reason = "planned", "continue", None
                    recovery_action, replanned = "fallback_original_task_prompt", False
                else:
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
                        allow_replan=self.replan_on_uncertain_exhaustion,
                        environment_result=environment_result,
                        action=action,
                        failure_label=failure_label,
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
            if recovery_class == "candidate_rejected":
                recovery_action = "resample_candidate"

        if next_status != "uncertain":
            state.pop("verification_observation", None)
        transition = {
            "execution_id": execution_id,
            "attempt_id": attempt_id,
            "previous_status": previous_status,
            "next_status": next_status,
            "transition_reason": transition_reason,
            "recovery_action": recovery_action,
            "recovery_class": recovery_class,
            "repeat_pattern": repeat_pattern,
            "next_execution_id": (
                state["active_execution"].get("execution_id")
                if isinstance(state["active_execution"], dict)
                else None
            ),
        }
        if failure_label is not None:
            transition["failure_label"] = failure_label.to_dict()
        if self.world_model_mode == "control" and causal_failure is not None:
            transition["first_causal_failure"] = causal_failure
        graph_transition = self._project_graph_transition(
            state, active_execution, str(verification.get("execution_status", execution_status)), transition_reason, verification
        )
        post_verify_memory_update = self._after_verification(
            agent,
            state,
            active_execution=active_execution,
            action=action,
            environment_result=environment_result,
            verification=verification,
        )
        if post_verify_memory_update is not None and not isinstance(
            post_verify_memory_update, dict
        ):
            raise TypeError("_after_verification() must return a dict or None")
        state["planner_output"] = planner_output
        state["action"] = action
        state["environment_result"] = environment_result
        if verification.get("verification_source") != "interval_not_due":
            state["verification"] = verification
        state["transition"] = transition
        if verifier_called:
            state["last_verifier_inputs"] = verifier_trace_inputs
        recovery_record = state.get("latest_recovery_memory")
        if not isinstance(recovery_record, dict):
            recovery_record = None
        if world_model_record is not None:
            state["world_model"] = world_model_record
        state["observation"] = environment_result.get("observation", observation)
        state["task_progress"] = float(verification.get("task_progress", 0.0))
        executed_steps = int(environment_result.get("executed_steps", 0))
        if executed_steps > 0:
            state["executed_action_chunks"] = (
                int(state.get("executed_action_chunks", 0)) + 1
            )
        state["action_chunks"] = int(state.get("executed_action_chunks", 0))
        state["environment_steps"] = (
            int(state.get("environment_steps", 0)) + executed_steps
        )
        evidence_summary = self._evidence_summary(verification)
        event_type = "transition"
        if next_status == "task_success":
            event_type = "task_success"
        elif decision == "failure":
            event_type = (
                "task_failed"
                if termination_reason == "environment_done"
                else "execution_aborted"
            )
        elif recovery_action in {"replan", "replan_subtask"}:
            event_type = "subtask_failed"
        elif recovery_action in {
            "retry_current",
            "reobserve",
            "retry_current_skill",
            "change_view",
            "retreat_and_retry",
            "regrasp",
            "adjust_target_pose",
            "reduce_horizon",
        }:
            event_type = "recovery_started"
        elif recovery_action == "fallback":
            event_type = "fallback_used"
        elif next_status == "plan":
            event_type = "subtask_completed"
        elif next_status == "failed":
            event_type = "subtask_failed"
        history_entry = {
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
            "recovery_class": recovery_class,
            "repeat_pattern": repeat_pattern,
            "last_action_success": verification.get("last_action_success"),
            "task_progress": verification.get("task_progress"),
            "executed_steps": environment_result.get("executed_steps", 0),
        }
        if failure_label is not None:
            history_entry["failure_label"] = failure_label.to_dict()
        if self.world_model_mode == "control" and causal_failure is not None:
            history_entry["first_causal_failure"] = causal_failure
        if world_model_record is not None:
            history_entry["world_model"] = world_model_record
        state.setdefault("history", []).append(history_entry)

        event = {
            "event_type": event_type,
            "planner_output": planner_output,
            "planner_inputs": planner_trace_inputs,
            "planner_called": planner_called,
            "planner_replan": planner_replan,
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
            "verifier_inputs": verifier_trace_inputs,
            "verification": verification,
            "recovery_memory": recovery_record,
            "previous_status": previous_status,
            "next_status": next_status,
            "transition_reason": transition_reason,
            "verifier_evidence": evidence_summary,
            "recovery_action": recovery_action,
            "recovery_class": recovery_class,
            "repeat_pattern": repeat_pattern,
            "transition": transition,
            "task_graph": state.get("task_graph"),
            "task_graph_revision": state.get("task_graph_revision", 0),
            "graph_transition": graph_transition,
            "completed_executions": list(state["completed_executions"]),
            "failed_executions": list(state["failed_executions"]),
            "decision": decision,
        }
        if failure_label is not None:
            event["failure_label"] = failure_label.to_dict()
        if self.world_model_mode == "control" and causal_failure is not None:
            event["first_causal_failure"] = causal_failure
        if post_verify_memory_update is not None:
            event["post_verify_memory_update"] = post_verify_memory_update
            memory_update_id = post_verify_memory_update.get("memory_update_id")
            if isinstance(memory_update_id, str) and memory_update_id:
                event["memory_update_id"] = memory_update_id
        trace_events: list[dict[str, Any]] = []
        if planner_called:
            trace_events.append(
                {
                    "event": "planner_call",
                    "step": state["step"],
                    "replan": planner_replan,
                    "inputs": planner_trace_inputs,
                    "output": planner_output,
                }
            )
        trace_events.append(
            {
                "event": "execution_result",
                "step": state["step"],
                "execution_id": execution_id,
                "attempt_id": attempt_id,
                "policy_inference": policy_inference,
                "policy_exchange": policy_exchange,
                "action": action,
                "environment_result": self._environment_result_trace(
                    environment_result
                ),
            }
        )
        if verifier_called:
            trace_events.append(
                {
                    "event": "verifier_call",
                    "step": state["step"],
                    "inputs": verifier_trace_inputs,
                    "output": verification,
                }
            )
        if post_verify_memory_update is not None:
            trace_events.append(
                {
                    "event": "post_verify_memory_update",
                    "step": state["step"],
                    **post_verify_memory_update,
                }
            )
        trace_events.append(
            {
                "event": "memory_update",
                "step": state["step"],
                "recovery_memory": recovery_record,
                "memory_records": int(state.get("memory_records", 0)),
            }
        )
        if recovery_action in {"replan", "replan_subtask"}:
            trace_events.append(
                {
                    "event": "replan_requested",
                    "step": state["step"],
                    "reason": transition_reason,
                    "recovery_memory": recovery_record,
                    "replan_count": int(state.get("replan_count", 0)),
                }
            )
        trace_events.append(
            {
                "event": "state_transition",
                "step": state["step"],
                "transition": transition,
                "decision": decision,
            }
        )
        event["trace_events"] = trace_events
        if world_model_record is not None:
            event["world_model"] = world_model_record
        if self.world_model_mode == "shadow":
            agent.update(
                self._state_without_world_model(state),
                self._mapping_without_world_model(event),
            )
        else:
            agent.update(state, event)
        return {
            **event,
            "invalid_action": bool(environment_result.get("planner_error"))
            or not bool(verification.get("last_action_success", False)),
            "success": success,
            "termination_reason": termination_reason,
        }

    def _after_verification(
        self,
        agent: BaseAgent,
        state: dict[str, Any],
        *,
        active_execution: dict[str, Any] | None,
        action: Any,
        environment_result: dict[str, Any],
        verification: dict[str, Any],
    ) -> dict[str, Any] | None:
        return None

    def _predict_world_model(
        self,
        *,
        agent: BaseAgent,
        action: Any,
        observation: Any,
        state: dict[str, Any],
        active_execution: dict[str, Any],
    ) -> dict[str, Any]:
        invalid_requested_horizon = False
        requested_horizon: int | None
        if self.action_execution_mode == "receding_horizon":
            requested_horizon = self._bounded_step_count(
                self.execute_steps, default=0, allow_zero=False
            )
            invalid_requested_horizon = requested_horizon == 0
        else:
            try:
                requested_horizon = self._action_horizon(action)
            except Exception:
                requested_horizon = None
        if requested_horizon is None:
            requested_horizon = 1
        record: dict[str, Any] = {
            "status": "unavailable",
            "prediction": None,
            "requested_horizon_steps": requested_horizon,
            "executed_steps": 0,
            "error": None,
            "model_called": False,
            "score_called": self.world_model_mode == "gate",
            "environment_executed": False,
            "reused": False,
            "prediction_step": self._bounded_step_count(
                state["step"], default=0, allow_zero=True
            ),
        }
        if invalid_requested_horizon:
            record["status"] = "error"
            record["error"] = {
                "type": "ValueError",
                "message": "world model requested horizon is outside supported bounds",
            }
            return record
        model_inputs = {
            "task": state["task"],
            "observation": observation,
            "action": action,
            "step": state["step"],
            "session_id": state.get("session_id"),
            "execution_id": active_execution["execution_id"],
            "attempt_id": active_execution["attempt_id"],
            "skill": active_execution["skill"],
            "skill_id": active_execution.get("skill_id"),
            "subtask": active_execution["subtask"],
            "grounded_arguments": active_execution["grounded_arguments"],
            "expected_outcome": active_execution["expected_outcome"],
            "requested_execute_steps": requested_horizon,
            "candidate_chunk_index": int(state.get("candidate_action_chunks", 0)) + 1,
            "episode_attempt_id": state.get("episode_attempt_id"),
        }
        if not self._world_model_backend_ready(agent):
            return record
        try:
            detached_inputs = self._detach_world_model_value(model_inputs)
        except Exception as error:
            record["status"] = "error"
            record["error"] = {
                "type": self._bounded_error_type(error),
                "message": "world model input isolation failed",
            }
            return record
        record["model_called"] = True
        try:
            prediction = (
                agent.score_action(detached_inputs)
                if self.world_model_mode == "gate"
                else agent.predict_transition(detached_inputs)
            )
        except Exception as error:
            record["status"] = "error"
            record["error"] = {
                "type": self._bounded_error_type(error),
                "message": "world model backend failed",
            }
            return record
        if prediction is None:
            return record
        try:
            normalized_prediction = normalize_world_model_prediction(prediction)
        except Exception as error:
            record["status"] = "error"
            record["error"] = {
                "type": self._bounded_error_type(error),
                "message": "world model prediction schema invalid",
            }
            return record
        record["status"] = "ok"
        record["prediction"] = normalized_prediction
        return record

    def _observe_world_model_transition(
        self,
        *,
        agent: BaseAgent,
        state: dict[str, Any],
        active_execution: dict[str, Any],
        observation_sequence: list[Mapping[str, Any]],
        environment_result: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        observer = getattr(agent, "observe_transition", None)
        if not callable(observer):
            return None
        sequence: list[Mapping[str, Any]] = observation_sequence
        if not sequence:
            final_observation = environment_result.get("observation")
            if isinstance(final_observation, Mapping):
                sequence = [final_observation]
        task_progress_value = environment_result.get("task_progress", 0.0)
        task_progress = (
            float(task_progress_value)
            if type(task_progress_value) in {int, float}
            else 0.0
        )
        inputs = {
            "task": state["task"],
            "session_id": state.get("session_id"),
            "step": state["step"],
            "runtime_step": state["step"],
            "candidate_chunk_index": int(state.get("candidate_action_chunks", 0)),
            "episode_attempt_id": state.get("episode_attempt_id"),
            "execution_id": active_execution["execution_id"],
            "attempt_id": active_execution["attempt_id"],
            "subtask": active_execution["subtask"],
            "observation_sequence": sequence,
            "post_action_observation": environment_result.get("observation"),
            "task_success": bool(environment_result.get("task_success", False)),
            "task_progress": task_progress,
            "executed_steps": self._bounded_step_count(
                environment_result.get("executed_steps", 0),
                default=0,
                allow_zero=True,
            ),
        }
        try:
            detached = self._detach_world_model_value(inputs)
            result = observer(detached)
        except Exception as error:
            return {
                "detected": False,
                "first_failure_step": None,
                "cause": "world_model_observation_error",
                "confidence": 0.0,
                "evidence": ["world model transition observation failed"],
                "error_type": self._bounded_error_type(error),
            }
        if result is None:
            return None
        if not isinstance(result, dict):
            return {
                "detected": False,
                "first_failure_step": None,
                "cause": "world_model_observation_schema_error",
                "confidence": 0.0,
                "evidence": ["world model transition observation returned non-dict"],
            }
        state["world_model_observations"] = (
            int(state.get("world_model_observations", 0)) + 1
        )
        return result

    @staticmethod
    def _world_model_accepts(record: dict[str, Any] | None) -> bool:
        if not isinstance(record, dict) or record.get("status") != "ok":
            return False
        prediction = record.get("prediction")
        metadata = prediction.get("metadata") if isinstance(prediction, dict) else None
        return (
            isinstance(metadata, dict)
            and type(metadata.get("accepted")) is bool
            and bool(metadata["accepted"])
        )

    @staticmethod
    def _world_model_gate_reason(record: dict[str, Any] | None) -> str:
        if not isinstance(record, dict):
            return "Cosmos action gate unavailable"
        prediction = record.get("prediction")
        metadata = prediction.get("metadata") if isinstance(prediction, dict) else None
        if isinstance(metadata, dict):
            value = metadata.get("value")
            threshold = metadata.get("threshold")
            if isinstance(value, (int, float)) and isinstance(threshold, (int, float)):
                return (
                    f"Cosmos action score {float(value):.4f} below "
                    f"threshold {float(threshold):.4f}"
                )
        error = record.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"]
        return "Cosmos action gate rejected candidate"

    @classmethod
    def _reused_world_model_record(
        cls, previous: dict[str, Any], *, current_step: int
    ) -> dict[str, Any]:
        fallback_step = max(0, current_step - 1)
        prediction_step = cls._bounded_step_count(
            previous.get("prediction_step"),
            default=fallback_step,
            allow_zero=True,
        )
        source_status = previous.get("source_status", previous.get("status"))
        if type(source_status) is not str or source_status not in {
            "ok",
            "unavailable",
            "error",
            "reused",
        }:
            source_status = "unknown"
        return cls._bounded_world_model_record(
            {
                "status": "reused",
                "prediction": None,
                "requested_horizon_steps": 0,
                "executed_steps": 0,
                "error": None,
                "model_called": False,
                "environment_executed": False,
                "reused": True,
                "prediction_step": prediction_step,
                "source_status": source_status,
            }
        )

    @staticmethod
    def _world_model_backend_ready(agent: BaseAgent) -> bool:
        try:
            agent_attributes = object.__getattribute__(agent, "__dict__")
        except (AttributeError, TypeError):
            agent_attributes = {}
        if (
            "_world_model_ready" in agent_attributes
            and agent_attributes["_world_model_ready"] is not True
        ):
            return False
        agent_type = type(agent)
        method = None
        try:
            method_resolution_order = type.__getattribute__(agent_type, "__mro__")
            for candidate in method_resolution_order:
                candidate_attributes = type.__getattribute__(candidate, "__dict__")
                if "predict_transition" in candidate_attributes:
                    method = candidate_attributes["predict_transition"]
                    break
        except (AttributeError, TypeError):
            return True
        if method is BaseAgent.predict_transition:
            return (
                agent_attributes.get("world_model") is not None
                and agent_attributes.get("_world_model_ready") is True
            )
        return True

    @classmethod
    def _detach_world_model_value(
        cls, value: Any, *, ancestors: frozenset[int] = frozenset()
    ) -> Any:
        value_type = type(value)
        if value is None or value_type in (bool, int, float, complex, str, bytes):
            return value
        if value_type is bytearray:
            return bytearray(value)

        identity = id(value)
        if identity in ancestors:
            raise TypeError("cyclic world model input is unsupported")
        nested_ancestors = ancestors | {identity}
        if value_type is dict:
            return {
                cls._detach_world_model_value(
                    key, ancestors=nested_ancestors
                ): cls._detach_world_model_value(item, ancestors=nested_ancestors)
                for key, item in value.items()
            }
        if value_type is list:
            return [
                cls._detach_world_model_value(item, ancestors=nested_ancestors)
                for item in value
            ]
        if value_type is tuple:
            return tuple(
                cls._detach_world_model_value(item, ancestors=nested_ancestors)
                for item in value
            )

        np = sys.modules.get("numpy")
        if np is not None:
            if value_type is np.ndarray:
                if bool(value.dtype.hasobject):
                    raise TypeError(
                        "object arrays cannot be detached for world model input"
                    )
                return value.copy(order="K")
            if cls._is_trusted_numpy_scalar_type(value_type, np):
                if bool(value.dtype.hasobject):
                    raise TypeError(
                        "object scalars cannot be detached for world model input"
                    )
                return cls._detach_world_model_value(
                    value.item(), ancestors=nested_ancestors
                )
        torch = sys.modules.get("torch")
        if torch is not None and value_type is torch.Tensor:
            detached = torch.Tensor.detach(value)
            return torch.Tensor.clone(detached, memory_format=torch.preserve_format)

        raise TypeError("unsupported world model input type")

    @classmethod
    def _mapping_without_world_model(cls, value: Any) -> Any:
        if type(value) is not dict:
            return value
        if not any(type(key) is str and key == "world_model" for key in value.keys()):
            return value
        return {
            key: item
            for key, item in value.items()
            if not (type(key) is str and key == "world_model")
        }

    @classmethod
    def _history_without_world_model(cls, value: Any) -> Any:
        if type(value) is list:
            sanitized_list = [cls._mapping_without_world_model(item) for item in value]
            return (
                sanitized_list
                if any(
                    updated is not original
                    for updated, original in zip(sanitized_list, value, strict=True)
                )
                else value
            )
        if type(value) is tuple:
            sanitized_tuple = tuple(
                cls._mapping_without_world_model(item) for item in value
            )
            return (
                sanitized_tuple
                if any(
                    updated is not original
                    for updated, original in zip(sanitized_tuple, value, strict=True)
                )
                else value
            )
        return value

    @classmethod
    def _state_without_world_model(cls, value: Any) -> Any:
        if type(value) is not dict:
            return value
        sanitized: dict[Any, Any] = {}
        changed = False
        for key, item in value.items():
            if type(key) is str and key == "world_model":
                changed = True
                continue
            if type(key) is str and key == "history":
                sanitized_item = cls._history_without_world_model(item)
                sanitized[key] = sanitized_item
                changed = changed or sanitized_item is not item
            else:
                sanitized[key] = item
        return sanitized if changed else value

    @classmethod
    def _bounded_world_model_record(cls, record: dict[str, Any]) -> dict[str, Any]:
        try:
            encoded = json.dumps(
                record,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        except (OverflowError, TypeError, ValueError):
            encoded = None
        if encoded is not None and len(encoded) <= _MAX_WORLD_MODEL_RECORD_BYTES:
            return record
        bounded = {
            "status": "error",
            "prediction": None,
            "requested_horizon_steps": cls._bounded_step_count(
                record.get("requested_horizon_steps"), default=1, allow_zero=True
            ),
            "executed_steps": cls._bounded_step_count(
                record.get("executed_steps"), default=0, allow_zero=True
            ),
            "error": {
                "type": "ValueError",
                "message": "world model record exceeds bounded serialized size",
            },
            "model_called": bool(record.get("model_called", False)),
            "environment_executed": bool(record.get("environment_executed", False)),
            "reused": bool(record.get("reused", False)),
            "prediction_step": cls._bounded_step_count(
                record.get("prediction_step"), default=0, allow_zero=True
            ),
        }
        if "source_status" in record:
            source_status = str(record["source_status"])
            bounded["source_status"] = (
                source_status
                if source_status in {"ok", "unavailable", "error", "reused"}
                else "unknown"
            )
        return bounded

    @staticmethod
    def _bounded_error_type(error: Exception) -> str:
        error_class = type(error)
        if type(error_class) is not type:
            return "Exception"
        name = error_class.__name__
        if (
            type(name) is not str
            or len(name) > _MAX_ERROR_TYPE_CHARS
            or not name.isidentifier()
        ):
            return "Exception"
        return name

    @staticmethod
    def _bounded_step_count(value: Any, *, default: int, allow_zero: bool) -> int:
        if type(value) is not int:
            return default
        count = value
        minimum = 0 if allow_zero else 1
        if count < minimum or count > _MAX_WORLD_MODEL_HORIZON_STEPS:
            return default
        return count

    @classmethod
    def _action_horizon(cls, action: Any) -> int | None:
        shape = cls._trusted_array_shape(action)
        if shape is not None:
            if len(shape) == 1:
                return (
                    1
                    if cls._bounded_step_count(shape[0], default=0, allow_zero=False)
                    else None
                )
            if len(shape) >= 2:
                return (
                    cls._bounded_step_count(shape[0], default=0, allow_zero=False)
                    or None
                )
            return None
        action_type = type(action)
        if action_type is dict:
            for value in action.values():
                candidate = cls._action_horizon(value)
                if candidate is not None:
                    return candidate
            return None
        if action_type in (list, tuple):
            action_length = len(action)
            if action_length == 0:
                return None
            first = action[0]
            is_chunk = cls._trusted_array_shape(first) is not None or type(first) in (
                dict,
                list,
                tuple,
            )
            if not is_chunk:
                return 1
            return (
                cls._bounded_step_count(action_length, default=0, allow_zero=False)
                or None
            )
        return None

    @staticmethod
    def _trusted_array_shape(value: Any) -> tuple[Any, ...] | None:
        value_type = type(value)
        np = sys.modules.get("numpy")
        if np is not None and value_type is np.ndarray:
            return tuple(value.shape)
        torch = sys.modules.get("torch")
        if torch is not None and value_type is torch.Tensor:
            return tuple(value.shape)
        return None

    @staticmethod
    def _is_trusted_numpy_scalar_type(value_type: type[Any], np: Any) -> bool:
        return any(
            value_type is candidate
            for candidate in np.sctypeDict.values()
            if type(candidate) is type
        )

    @staticmethod
    def _ensure_graph_state(state: dict[str, Any]) -> None:
        state.setdefault("active_execution", None)
        state.setdefault("completed_executions", [])
        state.setdefault("failed_executions", [])
        state.setdefault("execution_history", [])
        state.setdefault("execution_sequence", 0)
        state.setdefault("replan_count", 0)
        state.setdefault("high_level_replan_count", state["replan_count"])
        state.setdefault(
            "high_level_replan_epoch_count", state["high_level_replan_count"]
        )
        state.setdefault("fallback_count", 0)
        state.setdefault("fallback_epoch_count", state["fallback_count"])
        state.setdefault("pending_replan", False)
        state.setdefault("recovery_memory", [])
        state.setdefault("recovery_attempts", 0)
        state.setdefault("memory_records", 0)
        state.setdefault("planner_calls", 0)
        state.setdefault("last_planner_checkpoint_chunks", -1)
        state.setdefault("task_graph_revision", 0)
        state.setdefault("action_chunks", 0)
        state.setdefault("executed_action_chunks", state["action_chunks"])
        state.setdefault("environment_steps", 0)
        state.setdefault("verifier_calls", 0)
        state.setdefault("planner_adjudication_calls", 0)
        state.setdefault("verifier_only_transition_violations", 0)
        state.setdefault("evidence_ledger", [])
        state.setdefault("replan_planner_calls", 0)
        state.setdefault("candidate_action_chunks", 0)
        state.setdefault("accepted_action_chunks", 0)
        state.setdefault("rejected_action_chunks", 0)
        state.setdefault("latest_recovery_memory", None)
        state.setdefault("physical_failure_memory", [])
        state.setdefault("protocol_failure_memory", [])
        state.setdefault("physical_failure_records", 0)
        state.setdefault("protocol_failure_records", 0)
        state.setdefault("bounded_recovery_count", 0)
        state.setdefault(
            "bounded_recovery_epoch_count", state["bounded_recovery_count"]
        )
        state.setdefault("bounded_recovery_by_execution", {})
        state.setdefault("bounded_recovery_signatures", [])
        state.setdefault("recovery_action_counts", {})
        state.setdefault("original_task_prompt", None)
        state.setdefault("original_task_prompt_fallback_count", 0)
        state.setdefault(
            "original_task_prompt_fallback_epoch_count",
            state["original_task_prompt_fallback_count"],
        )
        state.setdefault("original_task_prompt_fallback_causes", [])
        state.setdefault("world_model_calls", 0)
        state.setdefault("world_model_observations", 0)
        state.setdefault("world_model_latency_seconds", 0.0)
        state.setdefault("failure_detections", 0)
        if state["active_execution"] is not None and not isinstance(
            state["active_execution"], dict
        ):
            raise TypeError("state['active_execution'] must be a dict or None")
        for key in ("completed_executions", "failed_executions", "execution_history"):
            if not isinstance(state[key], list):
                raise TypeError(f"state[{key!r}] must be a list")
        if not isinstance(state["recovery_memory"], list):
            raise TypeError("state['recovery_memory'] must be a list")

    def restart_from_task_decomposition(
        self, state: dict[str, Any]
    ) -> dict[str, Any]:
        """Clear agent-side execution state before a fresh Task Decompose call.

        The runtime owns simulator resets and cumulative audit counters. This
        method discards planner, verifier, task-graph, and bounded-recovery
        working state so the next attempt begins with no semantic carry-over.
        """
        self._ensure_graph_state(state)
        cleared = {
            "history_entries": len(state.get("history", [])),
            "completed_executions": len(state["completed_executions"]),
            "failed_executions": len(state["failed_executions"]),
            "execution_history": len(state["execution_history"]),
            "recovery_memories": len(state["recovery_memory"]),
        }
        state["active_execution"] = None
        state["completed_executions"] = []
        state["failed_executions"] = []
        state["execution_history"] = []
        state["history"] = []
        state["pending_replan"] = False
        state["recovery_memory"] = []
        state["latest_recovery_memory"] = None
        state["physical_failure_memory"] = []
        state["protocol_failure_memory"] = []
        state["bounded_recovery_by_execution"] = {}
        state["bounded_recovery_signatures"] = []
        state["high_level_replan_epoch_count"] = 0
        state["fallback_epoch_count"] = 0
        state["bounded_recovery_epoch_count"] = 0
        state["original_task_prompt_fallback_epoch_count"] = 0
        state["original_task_prompt"] = None
        state["last_planner_checkpoint_chunks"] = int(
            state.get("executed_action_chunks", 0)
        )
        state["task_graph_revision"] = 0
        for key in (
            "task_graph",
            "high_skill_selection",
            "reference_subtasks",
            "planner_output",
            "verification",
            "transition",
            "action",
            "environment_result",
            "verification_observation",
            "last_planner_inputs",
            "last_verifier_inputs",
            "skill_backend_history_current",
            "world_model",
            "next_recovery_execute_steps",
        ):
            state.pop(key, None)
        return {
            **cleared,
            "preserved_environment_steps": int(state.get("environment_steps", 0)),
            "preserved_executed_action_chunks": int(
                state.get("executed_action_chunks", 0)
            ),
            "preserved_execution_sequence": int(state["execution_sequence"]),
        }

    def restart_for_partial_recovery(
        self, state: dict[str, Any]
    ) -> dict[str, Any]:
        """Reset semantic state while preserving the goal and bounded evidence."""
        self._ensure_graph_state(state)
        graph = state.get("task_graph")
        if not isinstance(graph, Mapping):
            raise RuntimeError("partial recovery requires an existing task graph")
        active_execution = state.get("active_execution")
        verification = state.get("verification")
        latest_recovery = state.get("latest_recovery_memory")
        completed = state.get("completed_executions", [])
        failed = state.get("failed_executions", [])
        jointly_confirmed = [
            item
            for item in completed
            if isinstance(item, Mapping)
            and item.get("joint_transition_accepted") is True
        ]
        disputed = [
            item
            for item in state.get("evidence_ledger", [])
            if isinstance(item, Mapping) and item.get("joint_confirmed") is not True
        ]
        evidence_bundle = {
            "schema_version": 2,
            "immutable_goal_contract": deepcopy(state.get("goal_contract")),
            "mutable_task_graph_before_recovery": deepcopy(dict(graph)),
            "jointly_confirmed_executions": deepcopy(jointly_confirmed[-32:]),
            "disputed_claims": deepcopy(disputed[-16:]),
            "evidence_ledger": deepcopy(state.get("evidence_ledger", [])[-64:]),
            "last_failed_executions": deepcopy(failed[-8:]),
            "active_execution_before_reset": self._execution_trace(active_execution),
            "latest_verifier_result": deepcopy(dict(verification))
            if isinstance(verification, Mapping)
            else None,
            "latest_recovery_record": (
                {
                    "old_plan": self._execution_trace(
                        latest_recovery.get("old_plan")
                    ),
                    "verifier": deepcopy(latest_recovery.get("verifier")),
                    "current_progress": deepcopy(
                        latest_recovery.get("current_progress")
                    ),
                    "failure_label": deepcopy(
                        latest_recovery.get("failure_label")
                    ),
                    "recent_execution_result": self._environment_result_trace(
                        latest_recovery.get("recent_execution_result")
                    ),
                }
                if isinstance(latest_recovery, Mapping)
                else None
            ),
            "last_executed_action": {
                "type": type(state.get("action")).__name__,
                "horizon": self._action_horizon(state.get("action")),
            }
            if state.get("action") is not None
            else None,
            "failure_summary": (
                str(verification.get("reason", ""))
                if isinstance(verification, Mapping)
                else "horizon reached before authoritative success"
            ),
            "correctable_target_before_visual_reconciliation": (
                active_execution.get("subtask")
                if isinstance(active_execution, Mapping)
                else None
            ),
            "environment_steps": int(state.get("environment_steps", 0)),
            "executed_action_chunks": int(state.get("executed_action_chunks", 0)),
        }
        cleared = {
            "history_entries": len(state.get("history", [])),
            "completed_executions": len(completed),
            "failed_executions": len(failed),
            "execution_history": len(state.get("execution_history", [])),
            "recovery_memories": len(state.get("recovery_memory", [])),
        }
        state["recovery_evidence_bundle"] = evidence_bundle
        state["horizon_recovery_handoff"] = evidence_bundle
        state["active_execution"] = None
        state["completed_executions"] = []
        state["failed_executions"] = []
        state["execution_history"] = []
        state["history"] = []
        state["pending_replan"] = True
        state["recovery_memory"] = []
        state["latest_recovery_memory"] = None
        state["physical_failure_memory"] = []
        state["protocol_failure_memory"] = []
        state["bounded_recovery_by_execution"] = {}
        state["bounded_recovery_signatures"] = []
        state["high_level_replan_epoch_count"] = 0
        state["fallback_epoch_count"] = 0
        state["bounded_recovery_epoch_count"] = 0
        state["original_task_prompt_fallback_epoch_count"] = 0
        state["last_planner_checkpoint_chunks"] = int(
            state.get("executed_action_chunks", 0)
        )
        for key in (
            "high_skill_selection",
            "planner_output",
            "verification",
            "transition",
            "action",
            "environment_result",
            "verification_observation",
            "last_planner_inputs",
            "last_verifier_inputs",
            "skill_backend_history_current",
            "world_model",
            "next_recovery_execute_steps",
        ):
            state.pop(key, None)
        return {
            **cleared,
            "task_graph_preserved_for_revision": True,
            "preserved_graph_nodes": len(graph.get("nodes", [])),
            "goal_contract_preserved": True,
            "evidence_bundle_preserved": True,
            "memory_reset": True,
            "planner_replan_required": True,
            "preserved_environment_steps": int(state.get("environment_steps", 0)),
            "preserved_executed_action_chunks": int(
                state.get("executed_action_chunks", 0)
            ),
        }

    @staticmethod
    def _capture_temporal_visual_frame(
        state: dict[str, Any], observation: Any
    ) -> None:
        if not isinstance(observation, Mapping):
            return
        cameras = {
            str(key): value
            for key, value in observation.items()
            if value is not None
            and (
                str(key).startswith("video.")
                or key in {"images", "head_rgb"}
            )
        }
        if not cameras:
            return
        compact_observation = {
            **cameras,
            **{
                key: observation[key]
                for key in (
                    "annotation.human.task_description",
                    "available_skills",
                )
                if observation.get(key) is not None
            },
        }
        environment_steps = int(state.get("environment_steps", 0))
        action_chunks = int(state.get("executed_action_chunks", 0))
        threshold = state.get("horizon_recovery_threshold_environment_steps")
        frames = state.setdefault("_temporal_visual_frames", [])
        if not isinstance(frames, list):
            raise TypeError("_temporal_visual_frames must be a list")

        def record(phase: str) -> dict[str, Any]:
            return {
                "phase": phase,
                "environment_steps": environment_steps,
                "action_chunks": action_chunks,
                "observation": compact_observation,
            }

        phases = {frame.get("phase") for frame in frames if isinstance(frame, Mapping)}
        if "initial" not in phases:
            frames.append(record("initial"))
        if isinstance(threshold, int) and threshold > 0:
            for phase, fraction in (("early", 1 / 3), ("middle", 2 / 3)):
                if phase not in phases and environment_steps >= ceil(threshold * fraction):
                    frames.append(record(phase))
        frames[:] = [
            frame
            for frame in frames
            if not isinstance(frame, Mapping) or frame.get("phase") != "latest"
        ]
        frames.append(record("latest"))


    @staticmethod
    def _attach_episode_task_graph(agent: BaseAgent, state: dict[str, Any]) -> None:
        if isinstance(state.get("task_graph"), Mapping):
            return
        artifact = state.get("high_skill_selection")
        graph = artifact.get("task_graph") if isinstance(artifact, Mapping) else None
        if not isinstance(graph, Mapping):
            graph = getattr(agent, "episode_task_graph", None)
        if isinstance(graph, Mapping):
            state["task_graph"] = graph
            state["task_graph_revision"] = int(graph.get("revision", 0))

    def _planner_checkpoint_due(
        self,
        state: Mapping[str, Any],
        active_execution: Any,
        planner_replan: bool,
    ) -> bool:
        if isinstance(active_execution, Mapping) and active_execution.get("instruction_fallback"):
            return False
        if active_execution is None or planner_replan:
            return True
        if isinstance(active_execution, Mapping) and active_execution.get("status") == "uncertain":
            return False
        chunks = int(state.get("executed_action_chunks", 0))
        last = int(state.get("last_planner_checkpoint_chunks", -1))
        return chunks > 0 and chunks != last and chunks % self.planner_check_interval_chunks == 0


    @staticmethod
    def _capture_original_task_prompt(state: dict[str, Any], observation: Any) -> None:
        if isinstance(state.get("original_task_prompt"), str) and state["original_task_prompt"].strip():
            return
        if not isinstance(observation, Mapping):
            return
        prompt = observation.get("annotation.human.task_description")
        if isinstance(prompt, str) and prompt.strip():
            state["original_task_prompt"] = prompt.strip()
            state["goal_contract"] = {
                "schema_version": 1,
                "source": "official_task_instruction",
                "immutable": True,
                "official_instruction": prompt.strip(),
            }

    def _start_original_task_prompt_fallback(
        self,
        state: dict[str, Any],
        execution: Mapping[str, Any] | None,
        reason: str,
        available_skills: Any,
    ) -> dict[str, Any] | None:
        if not self.fallback_to_original_task_prompt:
            return None
        if int(state.get("original_task_prompt_fallback_epoch_count", 0)) >= 1:
            return None
        prompt = state.get("original_task_prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            return None
        skill = execution.get("skill") if isinstance(execution, Mapping) else None
        if not isinstance(skill, str) or (
            isinstance(available_skills, list) and available_skills and skill not in available_skills
        ):
            skill = available_skills[0] if isinstance(available_skills, list) and available_skills else None
        if not isinstance(skill, str) or not skill.strip():
            return None
        fallback = self._start_execution(
            state,
            {
                "skill": skill,
                "skill_id": execution.get("skill_id") if isinstance(execution, Mapping) else None,
                "subtask": prompt.strip(),
                "grounded_arguments": {},
                "expected_outcome": "Complete the official task instruction.",
                "decision": "update",
                "reasoning": "Fallback to the original Xiaomi task prompt after recovery exhaustion.",
            },
            available_skills,
        )
        fallback["instruction_fallback"] = "original_task_prompt"
        fallback["fallback_reason"] = reason
        state["active_execution"] = fallback
        state["pending_replan"] = False
        state["original_task_prompt_fallback_epoch_count"] = 1
        state["original_task_prompt_fallback_count"] = int(
            state.get("original_task_prompt_fallback_count", 0)
        ) + 1
        causes = state["original_task_prompt_fallback_causes"]
        if isinstance(causes, list):
            causes.append(reason)
        return fallback

    @staticmethod
    def _reference_subtasks(graph: Any) -> list[str]:
        nodes = graph.get("nodes") if isinstance(graph, Mapping) else None
        if not isinstance(nodes, list):
            return []
        subtasks: list[str] = []
        for node in nodes:
            if not isinstance(node, Mapping):
                continue
            text = node.get("instruction", node.get("subtask"))
            if isinstance(text, str) and text.strip():
                subtasks.append(text.strip())
        return subtasks

    @staticmethod
    def _active_graph_node(
        state: Mapping[str, Any], active_execution: Any
    ) -> dict[str, Any] | None:
        node_id = active_execution.get("node_id") if isinstance(active_execution, Mapping) else None
        graph = state.get("task_graph")
        nodes = graph.get("nodes") if isinstance(graph, Mapping) else None
        if isinstance(nodes, list):
            for node in nodes:
                if isinstance(node, Mapping) and node.get("id") == node_id:
                    return dict(node)
        return None


    @staticmethod
    def _planner_proposal(
        state: Mapping[str, Any], planner_output: dict[str, Any]
    ) -> dict[str, Any]:
        return dict(planner_output)

    def _same_execution_semantics(
        self,
        active_execution: Mapping[str, Any],
        planner_output: Mapping[str, Any],
        available_skills: Any,
    ) -> bool:
        subtask = planner_output.get("subtask")
        grounded_arguments = planner_output.get("grounded_arguments")
        expected_outcome = planner_output.get("expected_outcome")
        skill_id = planner_output.get("skill_id")
        if not isinstance(subtask, str) or not subtask.strip():
            raise PlannerOutputError("Planner proposal requires a non-empty subtask")
        if not isinstance(grounded_arguments, dict):
            raise PlannerOutputError(
                "Planner proposal requires grounded_arguments dict"
            )
        if not isinstance(expected_outcome, str) or not expected_outcome.strip():
            raise PlannerOutputError(
                "Planner proposal requires a non-empty expected_outcome"
            )
        if skill_id is not None and (
            not isinstance(skill_id, int)
            or isinstance(skill_id, bool)
            or skill_id < 0
        ):
            raise PlannerOutputError("Planner proposal skill_id must be non-negative")
        skill = self._extract_skill(planner_output, available_skills)
        return (
            active_execution.get("skill") == skill
            and active_execution.get("skill_id") == skill_id
            and active_execution.get("subtask") == subtask.strip()
            and active_execution.get("grounded_arguments") == grounded_arguments
            and active_execution.get("expected_outcome") == expected_outcome.strip()
        )


    def _equivalent_no_progress_failure(
        self,
        state: Mapping[str, Any],
        planner_output: Mapping[str, Any],
        available_skills: Any,
    ) -> Mapping[str, Any] | None:
        failures = state.get("failed_executions")
        if not isinstance(failures, list) or not failures:
            return None
        previous = failures[-1]
        if not isinstance(previous, Mapping) or previous.get("reason") != "no progress detected":
            return None
        grounded_arguments = planner_output.get("grounded_arguments")
        expected_outcome = planner_output.get("expected_outcome")
        if not isinstance(grounded_arguments, dict) or not isinstance(expected_outcome, str):
            return None
        skill = self._extract_skill(planner_output, available_skills)
        if (
            previous.get("skill") == skill
            and previous.get("skill_id") == planner_output.get("skill_id")
            and previous.get("grounded_arguments") == grounded_arguments
            and previous.get("expected_outcome") == expected_outcome.strip()
        ):
            return previous
        return None

    @staticmethod
    def _project_graph_transition(
        state: dict[str, Any],
        active_execution: Any,
        execution_status: str,
        reason: str,
        verification: dict[str, Any],
    ) -> dict[str, Any] | None:
        return None

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
        planner_output = self._planner_proposal(state, planner_output)
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
            not isinstance(skill_id, int) or isinstance(skill_id, bool) or skill_id < 0
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
            "candidate_rejection_count": 0,
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
            execution["_repeat_pattern"] = "repeated_skill"
        elif (
            len(recent_signatures) >= 2
            and signature == recent_signatures[-2]
            and signature != recent_signatures[-1]
        ):
            execution["_repeat_pattern"] = "A-B-A"
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

    def _adjudicate_verifier_candidate(
        self,
        *,
        agent: BaseAgent,
        state: dict[str, Any],
        active_execution: Any,
        verification_inputs: Mapping[str, Any],
        verification: dict[str, Any],
    ) -> dict[str, Any]:
        verifier_candidate = deepcopy(verification)
        adjudicate = getattr(agent, "adjudicate", None)
        if not callable(adjudicate):
            raise RuntimeError("joint verifier-planner adjudication is required")
        state["planner_adjudication_calls"] = int(
            state.get("planner_adjudication_calls", 0)
        ) + 1
        adjudication = adjudicate(
            {
                **dict(verification_inputs),
                "verifier_candidate": verifier_candidate,
                "goal_contract": state.get("goal_contract"),
                "task_graph": state.get("task_graph"),
                "evidence_ledger": list(state.get("evidence_ledger", []))[-64:],
            }
        )
        final_status = self._joint_execution_status(
            verifier_candidate, adjudication
        )
        joint_accepted = (
            adjudication.get("verifier_decision") == "accept"
            and adjudication.get("adjudicated_status")
            == verifier_candidate.get("execution_status")
        )
        ledger = state.setdefault("evidence_ledger", [])
        if not isinstance(ledger, list):
            raise TypeError("evidence_ledger must be a list")
        ledger.append(
            {
                "step": state.get("step"),
                "execution_id": (
                    active_execution.get("execution_id")
                    if isinstance(active_execution, Mapping)
                    else None
                ),
                "verifier_candidate": {
                    key: verifier_candidate.get(key)
                    for key in (
                        "execution_status",
                        "progress_assessment",
                        "reason",
                        "confidence",
                        "evidence",
                    )
                },
                "planner_adjudication": deepcopy(adjudication),
                "final_status": final_status,
                "joint_confirmed": joint_accepted,
            }
        )
        del ledger[:-64]
        return {
            **verification,
            "verifier_candidate_status": verifier_candidate.get(
                "execution_status"
            ),
            "planner_adjudication": adjudication,
            "joint_transition": True,
            "joint_transition_accepted": joint_accepted,
            "execution_status": final_status,
        }

    @staticmethod
    def _joint_execution_status(
        verifier_candidate: Mapping[str, Any], adjudication: Mapping[str, Any]
    ) -> str:
        candidate = verifier_candidate.get("execution_status")
        decision = adjudication.get("verifier_decision")
        planner_status = adjudication.get("adjudicated_status")
        if candidate not in EXECUTION_STATUSES:
            raise VerifierOutputError(
                f"Verifier returned invalid execution_status: {candidate!r}"
            )
        if decision not in {"accept", "reject", "defer"}:
            raise PlannerOutputError("Planner returned invalid verifier_decision")
        if planner_status not in EXECUTION_STATUSES:
            raise PlannerOutputError("Planner returned invalid adjudicated_status")
        if decision == "accept":
            if planner_status != candidate:
                raise PlannerOutputError(
                    "joint accept requires matching verifier and planner statuses"
                )
            return str(candidate)
        if decision == "defer":
            return "uncertain"
        return "in_progress"

    @staticmethod
    def _authoritative_task_success(environment_result: Any) -> bool:
        if not isinstance(environment_result, Mapping):
            return False
        environment_info = environment_result.get("env_info")
        if isinstance(environment_info, Mapping) and "success" in environment_info:
            return environment_info.get("success") is True
        return environment_result.get("task_success") is True

    @staticmethod
    def _evidence_summary(verification: Mapping[str, Any]) -> list[str]:
        evidence = verification.get("evidence", [])
        if not isinstance(evidence, list):
            return [str(evidence)[:256]]
        return [str(item)[:256] for item in evidence[:3]]

    @classmethod
    def _planner_trace_inputs(cls, inputs: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "task": inputs.get("task"),
            "step": inputs.get("step"),
            "observation": cls._observation_trace(inputs.get("observation")),
            "available_skills": inputs.get("available_skills", []),
            "history": cls._bounded_trace_list(inputs.get("history", [])),
            "completed_executions": cls._bounded_trace_list(
                inputs.get("completed_executions", [])
            ),
            "failed_executions": cls._bounded_trace_list(
                inputs.get("failed_executions", [])
            ),
            "memory_context": cls._memory_context_trace(inputs.get("memory_context")),
            "verifier_result": inputs.get("verifier_result"),
            "recovery_memory": cls._bounded_trace_list(
                inputs.get("recovery_memory", [])
            ),
            "recovery_context": inputs.get("recovery_context"),
            "reference_subtasks": inputs.get("reference_subtasks", []),
            "planner_current_subtask": inputs.get("planner_current_subtask"),
        }

    @classmethod
    def _verifier_trace_inputs(cls, inputs: Mapping[str, Any]) -> dict[str, Any]:
        active_execution = inputs.get("active_execution")
        return {
            "task": inputs.get("task"),
            "step": inputs.get("state", {}).get("step")
            if isinstance(inputs.get("state"), Mapping)
            else None,
            "observation": cls._observation_trace(inputs.get("observation")),
            "pre_action_observation": cls._observation_trace(
                inputs.get("pre_action_observation")
            ),
            "post_action_observation": cls._observation_trace(
                inputs.get("post_action_observation")
            ),
            "planner_output": inputs.get("planner_output"),
            "active_execution": cls._execution_trace(active_execution),
            "action": inputs.get("action"),
            "environment_result": cls._environment_result_trace(
                inputs.get("environment_result")
            ),
            "memory_context": cls._memory_context_trace(inputs.get("memory_context")),
        }

    @staticmethod
    def _observation_trace(observation: Any) -> Any:
        if not isinstance(observation, Mapping):
            return observation
        result: dict[str, Any] = {"keys": [str(key) for key in observation]}
        metadata: dict[str, Any] = {}
        for key, value in observation.items():
            key_text = str(key)
            if (
                "image" in key_text.lower()
                or key_text.startswith("video.")
                or key_text.endswith("_rgb")
            ):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                metadata[key_text] = value
            elif isinstance(value, list) and len(value) <= 16:
                metadata[key_text] = value
        if metadata:
            result["metadata"] = metadata
        return result

    @classmethod
    def _memory_context_trace(cls, memory_context: Any) -> Any:
        if not isinstance(memory_context, Mapping):
            return memory_context
        return {
            "summary": memory_context.get("summary", ""),
            "recent_events": [
                cls._memory_event_trace(event)
                for event in cls._bounded_trace_list(
                    memory_context.get("recent_events", [])
                )
            ],
            "key_events": [
                cls._memory_event_trace(event)
                for event in cls._bounded_trace_list(
                    memory_context.get("key_events", [])
                )
            ],
            "recovery_memories": cls._bounded_trace_list(
                memory_context.get("recovery_memories", [])
            ),
        }

    @classmethod
    def _memory_event_trace(cls, event: Any) -> Any:
        if not isinstance(event, Mapping):
            return event
        verification = event.get("verification")
        return {
            "step": event.get("step"),
            "execution_id": event.get("execution_id"),
            "attempt_id": event.get("attempt_id"),
            "event_type": event.get("event_type"),
            "skill": event.get("skill"),
            "subtask": event.get("subtask"),
            "status": event.get("next_status", event.get("status")),
            "reason": event.get("transition_reason", event.get("reason")),
            "recovery_action": event.get("recovery_action"),
            "verification": (
                {
                    key: verification.get(key)
                    for key in (
                        "task_success",
                        "task_progress",
                        "last_action_success",
                        "environment_done",
                        "execution_status",
                        "reason",
                        "confidence",
                        "evidence",
                    )
                    if key in verification
                }
                if isinstance(verification, Mapping)
                else verification
            ),
            "text_summary": event.get("text_summary"),
        }

    @classmethod
    def _environment_result_trace(cls, environment_result: Any) -> Any:
        if not isinstance(environment_result, Mapping):
            return environment_result
        keys = (
            "task_success",
            "task_progress",
            "last_action_success",
            "done",
            "executed_steps",
            "environment_steps",
            "env_feedback",
            "env_info",
            "execution_status",
            "verification_reason",
            "verification_confidence",
            "verification_evidence",
            "planner_error",
            "control_failure",
            "action_range_policy",
            "action_clipped",
            "action_clipped_value_count",
            "action_clipped_fields",
            "max_preclip_range_excess",
        )
        return {
            key: environment_result.get(key)
            for key in keys
            if key in environment_result
        }

    @classmethod
    def _execution_trace(cls, execution: Any) -> Any:
        if not isinstance(execution, Mapping):
            return execution
        keys = (
            "execution_id",
            "attempt_id",
            "attempt_count",
            "skill",
            "skill_id",
            "node_id",
            "subtask",
            "grounded_arguments",
            "expected_outcome",
            "status",
            "chunk_count",
            "attempt_chunk_count",
            "failure_count",
            "uncertain_count",
            "no_progress_count",
            "instruction_fallback",
            "fallback_reason",
        )
        return {key: execution.get(key) for key in keys if key in execution}

    @staticmethod
    def _bounded_trace_list(value: Any, limit: int = 20) -> Any:
        if not isinstance(value, list):
            return value
        return value[-limit:]

    @classmethod
    def _record_recovery_memory(
        cls,
        state: dict[str, Any],
        execution: Mapping[str, Any] | None,
        verification: Mapping[str, Any],
        reason: str,
        *,
        environment_result: Mapping[str, Any] | None,
        action: Any,
        failure_label: FailureLabel | None = None,
    ) -> dict[str, Any]:
        recent_result = cls._environment_result_trace(environment_result)
        if not isinstance(recent_result, dict):
            recent_result = {"value": recent_result}
        recent_result["action"] = action
        record = {
            "record_type": "recovery_memory",
            "step": state.get("step"),
            "execution_id": execution.get("execution_id")
            if isinstance(execution, Mapping)
            else None,
            "attempt_id": execution.get("attempt_id")
            if isinstance(execution, Mapping)
            else None,
            "old_plan": cls._execution_trace(execution),
            "verifier": {
                **dict(verification),
                "reason": reason,
            },
            "current_progress": {
                "task_progress": verification.get(
                    "task_progress", state.get("task_progress", 0.0)
                ),
                "environment_steps": (
                    environment_result.get("environment_steps")
                    if isinstance(environment_result, Mapping)
                    else state.get("environment_steps", 0)
                ),
                "step": state.get("step"),
            },
            "attempt_count": execution.get("attempt_count", 0)
            if isinstance(execution, Mapping)
            else 0,
            "recent_execution_result": recent_result,
            "failure_label": (
                failure_label.to_dict()
                if failure_label is not None
                else {
                    "category": "unclassified",
                    "cause": "unknown",
                    "confidence": 0.0,
                    "physical_memory_eligible": False,
                    "evidence": [],
                }
            ),
        }
        state.setdefault("recovery_memory", []).append(record)
        if failure_label is not None and failure_label.physical_memory_eligible:
            state.setdefault("physical_failure_memory", []).append(record)
            state["physical_failure_records"] = (
                int(state.get("physical_failure_records", 0)) + 1
            )
        else:
            state.setdefault("protocol_failure_memory", []).append(record)
            state["protocol_failure_records"] = (
                int(state.get("protocol_failure_records", 0)) + 1
            )
        state["latest_recovery_memory"] = record
        state["recovery_attempts"] = int(state.get("recovery_attempts", 0)) + 1
        state["memory_records"] = int(state.get("memory_records", 0)) + 1
        return record

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
            "node_id": execution.get("node_id"),
            "subtask": execution["subtask"],
            "grounded_arguments": execution["grounded_arguments"],
            "expected_outcome": execution["expected_outcome"],
            "status": "completed" if completed else "failed",
            "chunk_count": execution["chunk_count"],
            "failure_count": execution["failure_count"],
            "reason": reason,
            "confidence": verification.get("confidence"),
            "evidence": self._evidence_summary(verification),
            "joint_transition_accepted": verification.get(
                "joint_transition_accepted"
            ),
            "planner_adjudication": deepcopy(
                verification.get("planner_adjudication")
            ),
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
        environment_result: dict[str, Any] | None,
        action: Any,
        failure_label: FailureLabel | None = None,
    ) -> tuple[str, str, str | None, str, bool]:
        execution["failure_count"] += 1
        if self.recovery_enabled:
            self._record_recovery_memory(
                state,
                execution,
                verification,
                reason,
                environment_result=environment_result,
                action=action,
                failure_label=failure_label,
            )
        if self.recovery_strategy == "bounded" and self.recovery_enabled:
            label = failure_label or classify_failure(
                reason,
                verification,
                environment_result,
            )
            recovery = self.recovery_router.route(state, execution, label)
            counts = state.setdefault("recovery_action_counts", {})
            if not isinstance(counts, dict):
                raise TypeError("recovery_action_counts must be a dict")
            counts[recovery.action] = int(counts.get(recovery.action, 0)) + 1
            if recovery.action == "fallback_original_task_prompt":
                execution["status"] = "failed"
                self._record_execution(
                    state, execution, verification, recovery.reason, completed=False
                )
                fallback = self._start_original_task_prompt_fallback(
                    state, execution, recovery.reason, available_skills
                )
                if fallback is not None:
                    return "planned", "continue", None, recovery.action, False
                state["active_execution"] = None
                return "aborted", "failure", "recovery_aborted", "abort", False
            if recovery.action == "replan_subtask":
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
                    allow_replan=True,
                )
            if recovery.action != "safe_abort" and (
                execution["attempt_count"] < self.max_attempts_per_execution
            ):
                execution["attempt_count"] += 1
                execution["attempt_id"] = (
                    f"{execution['execution_id']}:attempt:{execution['attempt_count']}"
                )
                execution["attempt_chunk_count"] = 0
                execution["status"] = "retrying"
                execution["recovery_action"] = recovery.action
                execution["no_progress_count"] = 0
                execution["progress_marker_initialized"] = False
                execution["last_progress_marker"] = None
                if recovery.directive is not None:
                    execution.setdefault("original_subtask", execution["subtask"])
                    execution["subtask"] = recovery.directive
                if recovery.action == "reduce_horizon" and self.execute_steps:
                    state["next_recovery_execute_steps"] = max(
                        1, self.execute_steps // 2
                    )
                state["active_execution"] = execution
                return (
                    "retrying",
                    "retry",
                    None,
                    recovery.action,
                    False,
                )
            if recovery.action != "safe_abort":
                fallback = self._start_original_task_prompt_fallback(
                    state, execution, recovery.reason, available_skills
                )
                if fallback is not None:
                    return "planned", "continue", None, "fallback_original_task_prompt", False
            execution["status"] = "failed"
            self._record_execution(
                state,
                execution,
                verification,
                recovery.reason,
                completed=False,
            )
            state["active_execution"] = None
            state["pending_replan"] = False
            return (
                "aborted",
                "failure",
                "recovery_aborted",
                "safe_abort",
                False,
            )
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
            self.high_level_replan_limit is None
            or state["high_level_replan_epoch_count"]
            < self.high_level_replan_limit
        ):
            state["high_level_replan_epoch_count"] += 1
            state["high_level_replan_count"] += 1
            state["replan_count"] = state["high_level_replan_count"]
            state["pending_replan"] = True
            return "plan", "retry", None, "replan", True

        if (
            self.fallback_proposal is not None
            and state["fallback_epoch_count"] == 0
        ):
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
                    state["pending_replan"] = False
                    state["fallback_epoch_count"] += 1
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

        replans_exhausted = (
            allow_replan
            and self.high_level_replan_limit is not None
            and state["high_level_replan_epoch_count"]
            >= self.high_level_replan_limit
        )
        fallback = self._start_original_task_prompt_fallback(
            state,
            None,
            "high-level replan budget exhausted" if replans_exhausted else "execution recovery exhausted",
            available_skills,
        )
        if fallback is not None:
            return "planned", "continue", None, "fallback_original_task_prompt", False
        state["active_execution"] = None
        state["pending_replan"] = False
        return (
            "aborted",
            "failure",
            "max_replans"
            if self.recovery_enabled and replans_exhausted
            else "execution_aborted",
            "abort",
            False,
        )

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
