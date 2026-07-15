import json
import re
from collections.abc import Mapping
from typing import Any

from omniroboagent.agent_core.verifiers.base import Verifier
from omniroboagent.backends.llm.base import LLMBackend
from omniroboagent.exceptions import ConfigError, VerifierOutputError

EXECUTION_STATUSES = {"in_progress", "completed", "failed", "uncertain"}

DEFAULT_SUBTASK_VERIFIER_PROMPT = """You verify one embodied subtask after an
action chunk. Compare the observation before and after execution against the expected
outcome. Judge only the active subtask, not the whole benchmark task. Return uncertain
when the visual evidence is insufficient.

Return JSON with exactly these fields:
{
  "execution_status": "in_progress, completed, failed, or uncertain",
  "reason": "short reason",
  "confidence": 0.0,
  "evidence": ["short observable evidence"]
}
"""


class SubtaskVerifier(Verifier):
    """Verify active execution state while preserving benchmark ground truth."""

    def __init__(
        self,
        backend: LLMBackend | None = None,
        camera_keys: list[str] | None = None,
        check_interval_chunks: int = 1,
        system_prompt: str = DEFAULT_SUBTASK_VERIFIER_PROMPT,
        max_tokens: int = 512,
        temperature: float = 0.0,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        if check_interval_chunks <= 0:
            raise ConfigError("check_interval_chunks must be positive")
        resolved_camera_keys = (
            ["images", "head_rgb"] if camera_keys is None else camera_keys
        )
        if not isinstance(resolved_camera_keys, list) or any(
            not isinstance(key, str) or not key for key in resolved_camera_keys
        ):
            raise ConfigError("camera_keys must contain non-empty strings")
        if len(set(resolved_camera_keys)) != len(resolved_camera_keys):
            raise ConfigError("camera_keys must be unique")
        self.backend = backend
        self.camera_keys = list(resolved_camera_keys)
        self.check_interval_chunks = check_interval_chunks
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra_body = extra_body or {}

    def healthcheck(self) -> dict[str, Any]:
        return self.backend.healthcheck() if self.backend is not None else {
            "healthy": True
        }

    def close(self) -> None:
        if self.backend is not None:
            self.backend.close()

    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        result = inputs.get("environment_result")
        if not isinstance(result, dict):
            raise TypeError("SubtaskVerifier requires an environment_result dict")

        common = {
            "task_success": bool(result.get("task_success", False)),
            "task_progress": float(result.get("task_progress", 0.0)),
            "last_action_success": bool(result.get("last_action_success", False)),
            "environment_done": bool(result.get("done", False)),
            "env_feedback": result.get("env_feedback", ""),
            "progress_marker": result.get(
                "progress_marker", result.get("task_progress", 0.0)
            ),
        }
        if common["task_success"]:
            return {
                **common,
                "execution_status": "completed",
                "reason": "benchmark reported authoritative task success",
                "confidence": 1.0,
                "evidence": ["environment_result.task_success=true"],
            }
        if common["environment_done"]:
            return {
                **common,
                "execution_status": "failed",
                "reason": "environment ended before task success",
                "confidence": 1.0,
                "evidence": ["environment_result.done=true"],
            }
        if result.get("planner_error") or not common["last_action_success"]:
            return {
                **common,
                "execution_status": "failed",
                "reason": str(common["env_feedback"] or "action execution failed"),
                "confidence": 1.0,
                "evidence": ["environment_result.last_action_success=false"],
            }

        explicit_status = result.get("execution_status")
        if explicit_status is not None:
            if (
                not isinstance(explicit_status, str)
                or explicit_status not in EXECUTION_STATUSES
            ):
                raise VerifierOutputError(
                    f"Invalid environment execution_status: {explicit_status!r}"
                )
            return {
                **common,
                "execution_status": explicit_status,
                "reason": str(result.get("verification_reason", "environment signal")),
                "confidence": self._confidence(
                    result.get("verification_confidence", 1.0)
                ),
                "evidence": self._evidence(result.get("verification_evidence", [])),
            }

        active_execution = inputs.get("active_execution")
        if not isinstance(active_execution, Mapping):
            state = inputs.get("state")
            active_execution = (
                state.get("active_execution") if isinstance(state, Mapping) else None
            )
        if not isinstance(active_execution, Mapping):
            active_execution = {}
        chunk_count = (
            active_execution.get("chunk_count", 1)
        )
        if not isinstance(chunk_count, int) or isinstance(chunk_count, bool):
            raise VerifierOutputError("active_execution.chunk_count must be an integer")
        if chunk_count % self.check_interval_chunks != 0:
            return {
                **common,
                "execution_status": "in_progress",
                "reason": "semantic verification deferred until configured interval",
                "confidence": 1.0,
                "evidence": [f"chunk_count={chunk_count}"],
            }
        if self.backend is None:
            return {
                **common,
                "execution_status": "in_progress",
                "reason": "action succeeded without structured completion evidence",
                "confidence": 0.5,
                "evidence": ["environment_result.last_action_success=true"],
            }

        prompt = {
            "task": inputs.get("task"),
            "skill": active_execution.get("skill"),
            "subtask": active_execution.get("subtask"),
            "grounded_arguments": active_execution.get("grounded_arguments", {}),
            "expected_outcome": active_execution.get("expected_outcome"),
            "environment_feedback": common["env_feedback"],
        }
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": json.dumps(prompt, ensure_ascii=False),
            }
        ]
        observations = [
            ("before", inputs.get("observation")),
            ("after", result.get("observation")),
        ]
        for label, observation in observations:
            if not isinstance(observation, Mapping):
                continue
            content.append({"type": "text", "text": f"{label} observation"})
            for camera_key in self.camera_keys:
                images = observation.get(camera_key)
                if images is None:
                    continue
                if not isinstance(images, list):
                    images = [images]
                for image in images:
                    content.append(
                        {"type": "image_url", "image_url": {"url": image}}
                    )

        response = self.backend.complete(
            {
                "messages": [
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": content},
                ],
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "subtask_verification",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "execution_status": {
                                    "type": "string",
                                    "enum": sorted(EXECUTION_STATUSES),
                                },
                                "reason": {"type": "string", "minLength": 1},
                                "confidence": {
                                    "type": "number",
                                    "minimum": 0,
                                    "maximum": 1,
                                },
                                "evidence": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "required": [
                                "execution_status",
                                "reason",
                                "confidence",
                                "evidence",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "extra_body": self.extra_body,
            }
        )
        parsed = self._parse_json(self._response_text(response))
        execution_status = parsed.get("execution_status")
        if (
            not isinstance(execution_status, str)
            or execution_status not in EXECUTION_STATUSES
        ):
            raise VerifierOutputError(
                f"Verifier returned invalid execution_status: {execution_status!r}"
            )
        reason = parsed.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise VerifierOutputError("Verifier returned an invalid reason")
        return {
            **common,
            "execution_status": execution_status,
            "reason": reason.strip(),
            "confidence": self._confidence(parsed.get("confidence")),
            "evidence": self._evidence(parsed.get("evidence")),
        }

    @staticmethod
    def _confidence(value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise VerifierOutputError("Verifier confidence must be a number")
        confidence = float(value)
        if not 0.0 <= confidence <= 1.0:
            raise VerifierOutputError("Verifier confidence must be between 0 and 1")
        return confidence

    @staticmethod
    def _evidence(value: Any) -> list[str]:
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise VerifierOutputError("Verifier evidence must be a list of strings")
        return value

    @staticmethod
    def _response_text(response: dict[str, Any]) -> str:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise VerifierOutputError(
                "LLM response is missing choices[0].message.content"
            ) from error
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, dict)
            )
        raise VerifierOutputError("LLM verifier response content is empty")

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        stripped = text.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL)
        if fenced:
            stripped = fenced.group(1).strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise VerifierOutputError(
                f"Verifier returned invalid JSON: {text}"
            ) from error
        if not isinstance(parsed, dict):
            raise VerifierOutputError("Verifier JSON output must be an object")
        return parsed
