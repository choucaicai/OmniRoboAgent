import re
from collections.abc import Mapping
from typing import Any

from omniroboagent.agent_core.planners.subtask_skill import (
    DEFAULT_SUBTASK_SKILL_PROMPT,
    SubtaskSkillPlanner,
)
from omniroboagent.exceptions import ConfigError, PlannerOutputError


STATE_GROUNDED_PROMPT = DEFAULT_SUBTASK_SKILL_PROMPT + """

State consistency rules:
- Treat the newest observation and verified memory as the current state.
- Never propose an operation whose target state is already verified.
- Never invert a verified state unless the task explicitly requires that inversion.
- On a replan, address verifier evidence and change the failed proposal.
- The expected outcome must be observable and agree with the subtask.
"""


class StateGroundedSubtaskPlanner(SubtaskSkillPlanner):
    """Reject plans that repeat or invert recently verified state transitions."""

    _OPPOSITES = {
        "open": "close",
        "close": "open",
        "turn on": "turn off",
        "turn off": "turn on",
        "start": "stop",
        "stop": "start",
    }

    def __init__(
        self,
        *args: Any,
        semantic_retry_limit: int = 2,
        system_prompt: str = STATE_GROUNDED_PROMPT,
        **kwargs: Any,
    ) -> None:
        if semantic_retry_limit < 0:
            raise ConfigError("semantic_retry_limit must be non-negative")
        super().__init__(*args, system_prompt=system_prompt, **kwargs)
        self.semantic_retry_limit = semantic_retry_limit

    def plan(self, inputs: dict[str, Any]) -> dict[str, Any]:
        working_inputs = dict(inputs)
        rejections: list[str] = []
        for attempt in range(self.semantic_retry_limit + 1):
            try:
                proposal = super().plan(working_inputs)
            except PlannerOutputError as error:
                if isinstance(inputs.get("planner_current_subtask"), str):
                    raise
                rejection = f"initial planner response invalid: {error}"
                rejections.append(rejection)
                history = list(inputs.get("history", []))
                history.append({
                    "event": "planner_proposal_rejected",
                    "reason": rejection,
                })
                working_inputs = {**inputs, "history": history}
                continue
            protocol_error = self._initial_keep_protocol_error(proposal, inputs)
            if protocol_error is None and self._is_initial_keep(proposal, inputs):
                proposal = {
                    **proposal,
                    "decision": "update",
                    "protocol_normalization": "initial_keep_to_update",
                }
            contradiction = protocol_error or self._contradiction(proposal, inputs)
            if contradiction is None:
                return {
                    **proposal,
                    "semantic_validation": {
                        "valid": True,
                        "attempts": attempt + 1,
                        "prior_rejections": rejections,
                    },
                }
            rejections.append(contradiction)
            history = list(inputs.get("history", []))
            history.append({
                "event": "planner_proposal_rejected",
                "reason": contradiction,
                "proposal": {
                    "skill": proposal.get("skill"),
                    "subtask": proposal.get("subtask"),
                    "expected_outcome": proposal.get("expected_outcome"),
                },
            })
            working_inputs = {**inputs, "history": history}
        prefix = (
            "planner_protocol_error: "
            if any(item.startswith("initial ") for item in rejections)
            else ""
        )
        raise PlannerOutputError(prefix + "; ".join(rejections))

    @staticmethod
    def _is_initial_keep(
        proposal: Mapping[str, Any], inputs: Mapping[str, Any]
    ) -> bool:
        return (
            proposal.get("decision") == "keep"
            and not isinstance(inputs.get("planner_current_subtask"), str)
        )

    @classmethod
    def _initial_keep_protocol_error(
        cls, proposal: Mapping[str, Any], inputs: Mapping[str, Any]
    ) -> str | None:
        return None

    @classmethod
    def _contradiction(
        cls, proposal: Mapping[str, Any], inputs: Mapping[str, Any]
    ) -> str | None:
        proposal_subtask = cls._normalize(str(proposal.get("subtask", "")))
        proposal_text = cls._normalize(
            f"{proposal.get('subtask', '')} {proposal.get('expected_outcome', '')}"
        )
        for event in cls._completed_events(inputs.get("memory_context")):
            previous_subtask = cls._normalize(str(event.get("subtask", "")))
            previous = cls._normalize(
                f"{event.get('subtask', '')} {event.get('expected_outcome', '')} "
                f"{event.get('text_summary', '')}"
            )
            if proposal_subtask and proposal_subtask == previous_subtask:
                return "proposal repeats a subtask already verified as completed"
            for operation, opposite in cls._OPPOSITES.items():
                if operation in previous and opposite in proposal_text:
                    target = cls._shared_target(previous, proposal_text)
                    if target:
                        return (
                            f"proposal reverses verified state for {target}: "
                            f"{operation} -> {opposite}"
                        )
        return None

    @staticmethod
    def _completed_events(memory_context: Any) -> list[Mapping[str, Any]]:
        if not isinstance(memory_context, Mapping):
            return []
        events: list[Mapping[str, Any]] = []
        for key in ("recent_events", "key_events"):
            value = memory_context.get(key, [])
            if not isinstance(value, list):
                continue
            for event in value:
                if not isinstance(event, Mapping):
                    continue
                status = event.get("next_status", event.get("status"))
                verification = event.get("verification")
                verified_status = (
                    verification.get("execution_status")
                    if isinstance(verification, Mapping)
                    else None
                )
                if status == "completed" or verified_status == "completed":
                    events.append(event)
        return events[-20:]

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", value.lower()))

    @staticmethod
    def _shared_target(left: str, right: str) -> str | None:
        ignored = {
            "the", "a", "an", "is", "to", "and", "then", "fully", "should",
            "be", "open", "close", "closed", "turn", "on", "off", "start", "stop",
        }
        shared = [
            token for token in left.split()
            if token not in ignored and token in right.split()
        ]
        return " ".join(shared[:4]) or None
