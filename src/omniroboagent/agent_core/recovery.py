from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
import re
from typing import Any

RECOVERY_ACTIONS = {
    "reobserve",
    "retry_current_skill",
    "change_view",
    "retreat_and_retry",
    "regrasp",
    "adjust_target_pose",
    "reduce_horizon",
    "replan_subtask",
    "safe_abort",
    "fallback_original_task_prompt",
}

_INFRASTRUCTURE_MARKERS = (
    "json",
    "planneroutputerror",
    "verifieroutputerror",
    "backenderror",
    "timeout",
    "http",
    "https",
    "cuda",
    "oom",
    "connection",
    "transport",
    "schema",
    "parse",
    "actionrangeerror",
    "action_out_of_range",
    "backend_unavailable",
    "policy_protocol_error",
    "simulator_exception",
    "simulator",
    "exception",
)


# Word-boundary matching keeps marker substrings inside ordinary words
# (e.g. "oom" inside "mushroom") from fabricating infrastructure failures.
_INFRASTRUCTURE_MARKER_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(marker) for marker in _INFRASTRUCTURE_MARKERS) + r")\b"
)

@dataclass(frozen=True)
class FailureLabel:
    category: str
    cause: str
    confidence: float
    physical_memory_eligible: bool
    evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["evidence"] = list(self.evidence)
        return result


@dataclass(frozen=True)
class RecoveryDecision:
    action: str
    reason: str
    directive: str | None


def classify_failure(
    reason: str,
    verification: Mapping[str, Any],
    environment_result: Mapping[str, Any] | None,
    causal_failure: Mapping[str, Any] | None = None,
) -> FailureLabel:
    evidence = _evidence(verification)
    if causal_failure is not None and causal_failure.get("detected") is True:
        cause = str(causal_failure.get("cause") or "world_model_mismatch")
        confidence = _confidence(causal_failure.get("confidence"), 0.5)
        causal_evidence = causal_failure.get("evidence", [])
        if isinstance(causal_evidence, list):
            evidence.extend(str(item)[:256] for item in causal_evidence[:4])
        return FailureLabel(
            category="physical",
            cause=cause,
            confidence=confidence,
            physical_memory_eligible=True,
            evidence=tuple(evidence[:6]),
        )

    result = environment_result or {}
    error_type = str(
        result.get("error_type")
        or verification.get("error_type")
        or result.get("control_failure")
        or ""
    )
    combined = " ".join(
        [
            reason,
            error_type,
            str(result.get("env_feedback", "")),
            str(verification.get("reason", "")),
        ]
    ).lower()
    explicit_protocol = any(
        result.get(key) is True
        for key in (
            "planner_error",
            "verifier_error",
            "infrastructure_error",
            "action_gate_rejected",
        )
    )
    if explicit_protocol or _INFRASTRUCTURE_MARKER_RE.search(combined):
        return FailureLabel(
            category="protocol_infrastructure",
            cause=error_type or "protocol_or_infrastructure_error",
            confidence=1.0,
            physical_memory_eligible=False,
            evidence=tuple(evidence[:6] or [reason[:256]]),
        )

    recovery_class = str(verification.get("recovery_class") or "stalled")
    cause = {
        "wrong_plan": "planning_mismatch",
        "stalled": "articulation_no_progress",
        "candidate_rejected": "safety_rejection",
    }.get(recovery_class, recovery_class)
    return FailureLabel(
        category="physical",
        cause=cause,
        confidence=_confidence(verification.get("confidence"), 0.5),
        physical_memory_eligible=True,
        evidence=tuple(evidence[:6] or [reason[:256]]),
    )


class BoundedRecoveryRouter:
    """Map failure causes to bounded, auditable next-chunk recovery actions."""

    def __init__(
        self,
        max_per_subtask: int = 1,
        max_per_episode: int = 3,
    ) -> None:
        if max_per_subtask <= 0 or max_per_episode <= 0:
            raise ValueError("recovery limits must be positive")
        self.max_per_subtask = max_per_subtask
        self.max_per_episode = max_per_episode

    def route(
        self,
        state: dict[str, Any],
        execution: Mapping[str, Any],
        failure: FailureLabel,
    ) -> RecoveryDecision:
        if failure.category != "physical":
            return RecoveryDecision(
                action="safe_abort",
                reason="protocol/infrastructure failures are not physical recovery",
                directive=None,
            )
        episode_count = int(
            state.get(
                "bounded_recovery_epoch_count",
                state.get("bounded_recovery_count", 0),
            )
        )
        execution_id = str(execution.get("execution_id", "unknown"))
        per_execution = state.setdefault("bounded_recovery_by_execution", {})
        if not isinstance(per_execution, dict):
            raise TypeError("bounded_recovery_by_execution must be a dict")
        subtask_count = int(per_execution.get(execution_id, 0))
        if episode_count >= self.max_per_episode:
            return RecoveryDecision(
                "fallback_original_task_prompt", "episode recovery budget exhausted", None
            )
        if subtask_count >= self.max_per_subtask:
            return RecoveryDecision(
                "fallback_original_task_prompt", "subtask recovery budget exhausted", None
            )

        action = self._action_for(failure.cause)
        signature = f"{execution_id}|{failure.cause}|{action}"
        seen = state.setdefault("bounded_recovery_signatures", [])
        if not isinstance(seen, list):
            raise TypeError("bounded_recovery_signatures must be a list")
        # A repeated physical failure may consume another explicitly configured
        # retry. The per-subtask and per-episode budgets above are the loop
        # guard; rejecting the first repeated signature would silently cap the
        # execution at two total attempts even when max_per_subtask is larger.
        seen.append(signature)
        per_execution[execution_id] = subtask_count + 1
        state["bounded_recovery_epoch_count"] = episode_count + 1
        state["bounded_recovery_count"] = int(
            state.get("bounded_recovery_count", 0)
        ) + 1
        return RecoveryDecision(
            action=action,
            reason=f"bounded recovery for {failure.cause}",
            directive=self._directive(action, str(execution.get("subtask", ""))),
        )

    @staticmethod
    def _action_for(cause: str) -> str:
        normalized = cause.lower()
        if "grasp" in normalized or "slip" in normalized:
            return "regrasp"
        if (
            "pose" in normalized
            or "tracking" in normalized
            or "misalignment" in normalized
        ):
            return "adjust_target_pose"
        if (
            "view" in normalized
            or "occlu" in normalized
            or "not_visible" in normalized
        ):
            return "change_view"
        if (
            "collision" in normalized
            or "overshoot" in normalized
            or "contact_not_established" in normalized
        ):
            return "retreat_and_retry"
        if (
            "uncertain" in normalized
            or "insufficient" in normalized
            or "navigation_stall" in normalized
        ):
            return "reobserve"
        if "horizon" in normalized or "articulation_no_progress" in normalized:
            return "reduce_horizon"
        if "plan" in normalized:
            return "replan_subtask"
        return "retry_current_skill"

    @staticmethod
    def _directive(action: str, subtask: str) -> str | None:
        if action == "replan_subtask" or action == "safe_abort":
            return None
        prefixes = {
            "reobserve": "Re-observe the scene carefully, then continue",
            "retry_current_skill": "Retry once with a corrected motion",
            "change_view": "Move to a clearer camera view, then continue",
            "retreat_and_retry": "Retreat to a safe pose, then retry",
            "regrasp": "Release if needed, align the gripper, and regrasp",
            "adjust_target_pose": "Adjust end-effector pose before continuing",
            "reduce_horizon": "Use a smaller controlled motion before continuing",
        }
        prefix = prefixes.get(action)
        if prefix is None:
            return None
        return f"{prefix}: {subtask}" if subtask else prefix


def _evidence(verification: Mapping[str, Any]) -> list[str]:
    value = verification.get("evidence", [])
    if isinstance(value, list):
        return [str(item)[:256] for item in value[:4]]
    return [str(value)[:256]]


def _confidence(value: Any, fallback: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return fallback
    return min(1.0, max(0.0, float(value)))
