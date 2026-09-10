import json
import re
from collections.abc import Mapping
from typing import Any

from omniroboagent.agent_core.adaptive_prompt_skill import (
    AdaptivePromptSkill,
    CallMode,
    GenerateRequest,
    Role,
    SkillSpec,
)
from omniroboagent.agent_core.verifiers.base import Verifier
from omniroboagent.backends.llm.base import LLMBackend
from omniroboagent.exceptions import ConfigError, VerifierOutputError
from omniroboagent.serialization import to_jsonable

EXECUTION_STATUSES = {"in_progress", "completed", "failed", "uncertain"}
PROGRESS_ASSESSMENTS = {"advanced", "unchanged", "regressed", "unknown"}

DEFAULT_SUBTASK_VERIFIER_PROMPT = """You verify one embodied subtask after an
action chunk. Compare the observation before and after execution against the expected
outcome. Judge only the active subtask, not the whole benchmark task. Return uncertain
when the visual evidence is insufficient.

Independently assess visible subtask progress. Use advanced only when a before-to-after
change directly moves the active subtask toward its expected outcome. Use unchanged when
the relevant visible state is materially the same, regressed when it moved away from the
outcome, and unknown when the relevant state is occluded, absent, or not comparable.
Unknown is not evidence of failure or no progress.

Return JSON with exactly these fields:
{
  "execution_status": "in_progress, completed, failed, or uncertain",
  "progress_assessment": "advanced, unchanged, regressed, or unknown",
  "reason": "short reason",
  "confidence": 0.0,
  "evidence": ["short observable evidence"],
  "observed_facts": [{"subject": "object", "predicate": "state", "value": "observable value"}],
  "node_transition": {"node_id": "id", "from_status": "active", "to_status": "completed"}
}
"""


class SubtaskVerifier(Verifier):
    """Verify active execution state while preserving benchmark ground truth."""

    def __init__(
        self,
        backend: LLMBackend | None = None,
        camera_keys: list[str] | None = None,
        check_interval_chunks: int = 1,
        max_images: int | None = None,
        system_prompt: str = DEFAULT_SUBTASK_VERIFIER_PROMPT,
        max_tokens: int = 512,
        temperature: float = 0.0,
        extra_body: dict[str, Any] | None = None,
        response_format_mode: str = "json_schema",
        prompt_skill: AdaptivePromptSkill | None = None,
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
        if max_images is not None and (
            not isinstance(max_images, int)
            or isinstance(max_images, bool)
            or max_images <= 0
        ):
            raise ConfigError("max_images must be a positive integer or null")
        self.backend = backend
        self.camera_keys = list(resolved_camera_keys)
        self.check_interval_chunks = check_interval_chunks
        self.max_images = max_images
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra_body = extra_body or {}
        if response_format_mode not in {"json_schema", "json_object"}:
            raise ConfigError("response_format_mode must be json_schema or json_object")
        self.response_format_mode = response_format_mode
        self.prompt_skill = prompt_skill
        self.last_prompt_manifest: dict[str, Any] | None = None

    def healthcheck(self) -> dict[str, Any]:
        return (
            self.backend.healthcheck()
            if self.backend is not None
            else {"healthy": True}
        )

    def close(self) -> None:
        if self.backend is not None:
            self.backend.close()

    def should_verify(self, inputs: dict[str, Any]) -> bool:
        """Return whether this step needs a local or semantic verification."""
        result = inputs.get("environment_result")
        if not isinstance(result, dict):
            raise TypeError("SubtaskVerifier requires an environment_result dict")
        if (
            result.get("task_success")
            or result.get("done")
            or result.get("planner_error")
            or not bool(result.get("last_action_success", False))
            or result.get("execution_status") is not None
        ):
            return True

        active_execution = self._active_execution(inputs)
        if active_execution.get("status") == "uncertain":
            return True
        chunk_count = active_execution.get("chunk_count", 1)
        if not isinstance(chunk_count, int) or isinstance(chunk_count, bool):
            raise VerifierOutputError(
                "active_execution.chunk_count must be an integer"
            )
        return chunk_count % self.check_interval_chunks == 0

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
            return self._finalize_verification(
                {
                    **common,
                    "execution_status": "completed",
                    "reason": "benchmark reported authoritative task success",
                    "confidence": 1.0,
                    "evidence": ["environment_result.task_success=true"],
                },
                source="authoritative_success",
            )
        if common["environment_done"]:
            return self._finalize_verification(
                {
                    **common,
                    "execution_status": "failed",
                    "reason": "environment ended before task success",
                    "confidence": 1.0,
                    "evidence": ["environment_result.done=true"],
                },
                source="environment_done",
            )
        if result.get("planner_error") or not common["last_action_success"]:
            return self._finalize_verification(
                {
                    **common,
                    "execution_status": "failed",
                    "reason": str(common["env_feedback"] or "action execution failed"),
                    "confidence": 1.0,
                    "evidence": ["environment_result.last_action_success=false"],
                },
                source="action_failure",
            )

        explicit_status = result.get("execution_status")
        if explicit_status is not None:
            if (
                not isinstance(explicit_status, str)
                or explicit_status not in EXECUTION_STATUSES
            ):
                raise VerifierOutputError(
                    f"Invalid environment execution_status: {explicit_status!r}"
                )
            return self._finalize_verification(
                {
                    **common,
                    "execution_status": explicit_status,
                    "reason": str(
                        result.get("verification_reason", "environment signal")
                    ),
                    "confidence": self._confidence(
                        result.get("verification_confidence", 1.0)
                    ),
                    "evidence": self._evidence(result.get("verification_evidence", [])),
                },
                source="environment_signal",
            )

        active_execution = self._active_execution(inputs)
        if self.backend is None:
            return self._finalize_verification(
                {
                    **common,
                    "execution_status": "in_progress",
                    "reason": "action succeeded without structured completion evidence",
                    "confidence": 0.5,
                    "evidence": ["environment_result.last_action_success=true"],
                },
                source="backend_unavailable",
            )

        prompt = {
            "task": inputs.get("task"),
            "skill": active_execution.get("skill"),
            "subtask": active_execution.get("subtask"),
            "grounded_arguments": active_execution.get("grounded_arguments", {}),
            "expected_outcome": active_execution.get("expected_outcome"),
            "node_id": active_execution.get("node_id"),
            "task_graph": inputs.get("task_graph", inputs.get("state", {}).get("task_graph") if isinstance(inputs.get("state"), Mapping) else None),
            "environment_feedback": common["env_feedback"],
        }
        memory_context = inputs.get("memory_context")
        if isinstance(memory_context, Mapping):
            prompt["memory_context"] = to_jsonable(
                {
                    "summary": memory_context.get("summary", ""),
                    "recent_events": self._compact_memory_events(
                        memory_context.get("recent_events", [])
                    ),
                    "key_events": self._compact_memory_events(
                        memory_context.get("key_events", [])
                    ),
                }
            )
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": json.dumps(to_jsonable(prompt), ensure_ascii=False),
            }
        ]
        observations = [
            (
                "before",
                inputs.get("pre_action_observation", inputs.get("observation")),
            ),
            (
                "after",
                inputs.get("post_action_observation", result.get("observation")),
            ),
        ]
        image_count = 0
        for label, observation in observations:
            if not isinstance(observation, Mapping):
                continue
            observation_images: list[Any] = []
            for camera_key in self.camera_keys:
                images = observation.get(camera_key)
                if images is None:
                    continue
                if not isinstance(images, list):
                    images = [images]
                for image in images:
                    observation_images.append(image)
            if self.max_images is not None:
                remaining = max(self.max_images - image_count, 0)
                observation_images = observation_images[:remaining]
            if observation_images:
                content.append({"type": "text", "text": f"{label} observation"})
            for image in observation_images:
                content.append({"type": "image_url", "image_url": {"url": image}})
                image_count += 1
        if isinstance(memory_context, Mapping):
            working_frames = memory_context.get("working_frames", [])
            if isinstance(working_frames, list) and working_frames:
                memory_images: list[Any] = []
                for frame in working_frames:
                    cameras = (
                        frame.get("cameras") if isinstance(frame, Mapping) else None
                    )
                    if not isinstance(cameras, Mapping):
                        continue
                    for value in cameras.values():
                        images = value if isinstance(value, list) else [value]
                        for image in images:
                            memory_images.append(image)
                if self.max_images is not None:
                    remaining = max(self.max_images - image_count, 0)
                    memory_images = memory_images[-remaining:] if remaining else []
                if memory_images:
                    content.append(
                        {
                            "type": "text",
                            "text": "Visual working memory, oldest to newest",
                        }
                    )
                for image in memory_images:
                    content.append({"type": "image_url", "image_url": {"url": image}})

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": content},
        ]
        if self.prompt_skill is not None:
            task = inputs.get("task")
            task_record = dict(task) if isinstance(task, Mapping) else {"task": task}
            status = active_execution.get("status")
            failure_information = (
                {
                    "scope": "verification_only",
                    "failure_class": "insufficient_or_inconsistent_evidence",
                    "summary": f"active execution status is {status}",
                }
                if status == "uncertain"
                else None
            )
            skill = active_execution.get("skill")
            available_skills = (
                (SkillSpec(skill_id=skill),) if isinstance(skill, str) and skill else ()
            )
            history_events: list[Mapping[str, Any]] = []
            if isinstance(memory_context, Mapping):
                for key in ("recent_events", "key_events"):
                    events = memory_context.get(key, [])
                    if isinstance(events, list):
                        history_events.extend(
                            dict(event) for event in events if isinstance(event, Mapping)
                        )
            generated = self.prompt_skill.generate(
                GenerateRequest(
                    role=Role.VERIFIER,
                    task=task_record,
                    observations={},
                    task_state={
                        "task_graph": prompt.get("task_graph"),
                        "active_execution": dict(active_execution),
                        "environment_result": common,
                        "temporal_frame_metadata": [
                            {"phase": "before_action", "age_action_chunks": 1},
                            {"phase": "after_action_current", "age_action_chunks": 0},
                        ],
                        "recovery_handoff": (
                            inputs.get("state", {}).get("horizon_recovery_handoff")
                            if isinstance(inputs.get("state"), Mapping)
                            else None
                        ),
                        "recovery_reconciliation": (
                            inputs.get("state", {}).get(
                                "horizon_recovery_reconciliation"
                            )
                            if isinstance(inputs.get("state"), Mapping)
                            else None
                        ),
                    },
                    execution_history=tuple(history_events),
                    failure_information=failure_information,
                    available_skills=available_skills,
                    prompt_version=self.prompt_skill.default_version,
                    call_mode=(
                        CallMode.FAILURE_VERIFICATION
                        if failure_information is not None
                        else CallMode.NORMAL_VERIFICATION
                    ),
                    prebuilt_messages=tuple(messages),
                )
            )
            messages = [dict(message) for message in generated.messages]
            self.last_prompt_manifest = {
                "content_hash": generated.content_hash,
                "call_mode": generated.call_mode.value,
                "task_shape": generated.task_shape.value,
                "selected_blocks": [
                    {
                        "block_id": block.block_id,
                        "version": block.version,
                        "digest": block.digest,
                    }
                    for block in generated.selected_blocks
                ],
                "version_manifest": dict(generated.version_manifest),
                "prompt_audit": dict(self.prompt_skill.last_audit or {}),
            }
        response = self.backend.complete(
            {
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "response_format": (
                    {"type": "json_object"}
                    if self.response_format_mode == "json_object"
                    else {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "subtask_verification",
                        "schema": self._response_schema(),
                    },
                }
                ),
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
        progress_assessment = parsed.get("progress_assessment", "unknown")
        if isinstance(progress_assessment, str):
            progress_assessment = progress_assessment.strip().lower()
        if progress_assessment not in PROGRESS_ASSESSMENTS:
            progress_assessment = "unknown"
        reason = parsed.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise VerifierOutputError("Verifier returned an invalid reason")
        return self._finalize_verification(
            {
                **common,
                "execution_status": execution_status,
                "progress_assessment": progress_assessment,
                "reason": reason.strip(),
                "confidence": self._confidence(parsed.get("confidence")),
                "evidence": self._evidence(parsed.get("evidence")),
                "observed_facts": self._observed_facts(parsed.get("observed_facts", [])),
                "node_transition": self._node_transition(parsed.get("node_transition")),
            },
            source="model",
            model_output=parsed,
            inputs=inputs,
            model_usage=self._response_usage(response),
        )

    @staticmethod
    def _active_execution(inputs: Mapping[str, Any]) -> Mapping[str, Any]:
        active_execution = inputs.get("active_execution")
        if not isinstance(active_execution, Mapping):
            state = inputs.get("state")
            active_execution = (
                state.get("active_execution") if isinstance(state, Mapping) else None
            )
        return active_execution if isinstance(active_execution, Mapping) else {}

    def _response_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "execution_status": {
                    "type": "string",
                    "enum": sorted(EXECUTION_STATUSES),
                },
                "progress_assessment": {
                    "type": "string",
                    "enum": sorted(PROGRESS_ASSESSMENTS),
                },
                "reason": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 512,
                },
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                },
                "evidence": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "maxLength": 512,
                    },
                    "maxItems": 8,
                },
                "observed_facts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "subject": {"type": "string", "minLength": 1},
                            "predicate": {"type": "string", "minLength": 1},
                            "value": {"type": ["string", "number", "boolean"]},
                        },
                        "required": ["subject", "predicate", "value"],
                        "additionalProperties": False,
                    },
                    "maxItems": 12,
                },
                "node_transition": {
                    "type": "object",
                    "properties": {
                        "node_id": {"type": "string", "minLength": 1},
                        "from_status": {"type": "string", "minLength": 1},
                        "to_status": {"type": "string", "minLength": 1},
                    },
                    "required": ["node_id", "from_status", "to_status"],
                    "additionalProperties": False,
                },
            },
            "required": [
                "execution_status",
                "progress_assessment",
                "reason",
                "confidence",
                "evidence",
            ],
            "additionalProperties": False,
        }

    def _finalize_verification(
        self,
        verification: dict[str, Any],
        *,
        source: str,
        model_output: Mapping[str, Any] | None = None,
        inputs: Mapping[str, Any] | None = None,
        model_usage: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        finalized = {**verification, "verification_source": source}
        if model_output is not None:
            finalized["model_output"] = to_jsonable(model_output)
        if model_usage is not None:
            finalized["model_usage"] = to_jsonable(model_usage)
        return finalized

    @staticmethod
    def _response_usage(response: Any) -> dict[str, Any] | None:
        if not isinstance(response, Mapping):
            return None
        usage = response.get("usage")
        if not isinstance(usage, Mapping):
            return None
        return to_jsonable(
            {
                key: response.get(key)
                for key in ("id", "model")
                if response.get(key) is not None
            }
            | {"usage": dict(usage)}
        )

    @classmethod
    def _compact_memory_events(cls, events: Any) -> list[Any]:
        if not isinstance(events, list):
            return []
        return [cls._compact_memory_event(event) for event in events[-10:]]

    @staticmethod
    def _compact_memory_event(event: Any) -> Any:
        if not isinstance(event, Mapping):
            return to_jsonable(event)
        compact = {
            "step": event.get("step"),
            "event_type": event.get("event_type"),
            "skill": event.get("skill"),
            "subtask": event.get("subtask"),
            "status": event.get("next_status", event.get("status")),
            "reason": event.get("transition_reason", event.get("reason")),
            "verifier_evidence": event.get("verifier_evidence"),
            "recovery_action": event.get("recovery_action"),
            "recovery_class": event.get("recovery_class"),
            "text_summary": event.get("text_summary"),
        }
        verification = event.get("verification")
        if isinstance(verification, Mapping):
            compact["verification"] = {
                key: verification[key]
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
        return to_jsonable(
            {
                key: value
                for key, value in compact.items()
                if value not in (None, "", [], {})
            }
        )

    @classmethod
    def _observed_facts(cls, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list):
            raise VerifierOutputError("Verifier observed_facts must be a list")
        facts: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, Mapping) or set(item) != {"subject", "predicate", "value"}:
                raise VerifierOutputError("Verifier observed_facts entries are invalid")
            subject = item.get("subject")
            predicate = item.get("predicate")
            fact_value = item.get("value")
            if (
                not isinstance(subject, str)
                or not subject.strip()
                or not isinstance(predicate, str)
                or not predicate.strip()
                or not isinstance(fact_value, (str, int, float, bool))
            ):
                raise VerifierOutputError("Verifier observed_facts entries are invalid")
            facts.append(
                {
                    "subject": subject.strip(),
                    "predicate": predicate.strip(),
                    "value": fact_value,
                }
            )
        return facts[:12]

    @staticmethod
    def _node_transition(value: Any) -> dict[str, str] | None:
        if value is None:
            return None
        required = {"node_id", "from_status", "to_status"}
        # node_transition degrades to None on malformed model output (extra keys,
        # non-string values) instead of killing the episode with VerifierOutputError.
        if not isinstance(value, Mapping) or not required.issubset(value):
            return None
        if any(
            not isinstance(value.get(key), str) or not value[key].strip()
            for key in required
        ):
            return None
        return {
            key: str(value[key]).strip()
            for key in ("node_id", "from_status", "to_status")
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
                str(item.get("text", "")) for item in content if isinstance(item, dict)
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
            start = stripped.find("{")
            end = stripped.rfind("}")
            if start < 0 or end <= start:
                raise VerifierOutputError(
                    f"Verifier returned invalid JSON: {text}"
                ) from error
            try:
                parsed = json.loads(stripped[start : end + 1])
            except json.JSONDecodeError as nested_error:
                repaired = SubtaskVerifier._repair_evidence_scalars(
                    stripped[start : end + 1]
                )
                if repaired is None:
                    raise VerifierOutputError(
                        f"Verifier returned invalid JSON: {text}"
                    ) from nested_error
                try:
                    parsed = json.loads(repaired)
                except json.JSONDecodeError as repaired_error:
                    raise VerifierOutputError(
                        f"Verifier returned invalid JSON: {text}"
                    ) from repaired_error
        if not isinstance(parsed, dict):
            raise VerifierOutputError("Verifier JSON output must be an object")
        return parsed

    @staticmethod
    def _repair_evidence_scalars(text: str) -> str | None:
        evidence = re.search(r'("evidence"\s*:\s*\[)(.*?)(\])', text, re.DOTALL)
        if evidence is None:
            return None
        scalar = re.compile(
            r'"([^"\\]+)"\s*:\s*'
            r'("(?:\\.|[^"\\])*"|-?(?:0|[1-9]\d*)(?:\.\d+)?'
            r"(?:[eE][+-]?\d+)?|true|false|null)"
        )

        def stringify(match: re.Match[str]) -> str:
            value = json.loads(match.group(2))
            return json.dumps(f"{match.group(1)}={value}", ensure_ascii=False)

        repaired_body, replacements = scalar.subn(stringify, evidence.group(2))
        if replacements == 0:
            return None
        return text[: evidence.start(2)] + repaired_body + text[evidence.end(2) :]
