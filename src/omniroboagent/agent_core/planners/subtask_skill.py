import json
from collections.abc import Mapping
from typing import Any

from omniroboagent.agent_core.adaptive_prompt_skill import (
    AdaptivePromptSkill,
    CallMode,
    GenerateRequest,
    Role,
    SkillSpec,
)
from omniroboagent.agent_core.high_skills.context import (
    format_high_level_skill_context,
)
from omniroboagent.agent_core.planners.language_skill import LanguageSkillPlanner
from omniroboagent.backends.llm.base import LLMBackend
from omniroboagent.exceptions import ConfigError, PlannerOutputError
from omniroboagent.serialization import to_jsonable

DEFAULT_SUBTASK_SKILL_PROMPT = """You are an embodied agent executing a
long-horizon task. Select exactly one skill and one concrete current subtask for the
current observation. Reference subtasks are non-binding context only: the online
planner is authoritative and may choose a task-relevant subtask that is not in that
list. Use verifier and memory evidence, and do not decide whether an existing subtask
is complete.

Return JSON with exactly these fields:
{
  "decision": "keep or update",
  "reasoning": "short reason",
  "skill": "exact skill name",
  "subtask": "concrete instruction",
  "grounded_arguments": {"argument name": "grounded value"},
  "expected_outcome": "observable completion target"
}
"""

JOINT_ADJUDICATION_PROMPT = """You are the Planner acting as the second judge
for one subtask transition. The Verifier output is advisory, not authoritative.
Independently compare the official goal, active execution, before/after observations,
environment result, current plan graph, and bounded evidence ledger.

Use accept only when the evidence supports exactly the same status proposed by the
Verifier. Use reject when the proposal is contradicted. Use defer when the evidence is
insufficient or views are not comparable. Never claim whole-task success.

Return JSON with exactly these fields:
{
  "verifier_decision": "accept, reject, or defer",
  "adjudicated_status": "completed, in_progress, failed, or uncertain",
  "evidence_alignment": ["short supporting observation"],
  "contradictions": ["short contradiction or missing evidence"],
  "reasoning": "short reason"
}
"""


class SubtaskSkillPlanner(LanguageSkillPlanner):
    def __init__(
        self,
        backend: LLMBackend,
        skill_ids: dict[str, int],
        skill_definitions: dict[str, str],
        camera_keys: list[str] | None = None,
        history_limit: int = 10,
        max_images: int | None = None,
        system_prompt: str = DEFAULT_SUBTASK_SKILL_PROMPT,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        extra_body: dict[str, Any] | None = None,
        response_format_mode: str = "json_schema",
        prompt_skill: AdaptivePromptSkill | None = None,
    ) -> None:
        if not isinstance(skill_ids, dict) or not skill_ids:
            raise ConfigError("SubtaskSkillPlanner requires non-empty skill_ids")
        if any(not isinstance(skill, str) or not skill for skill in skill_ids):
            raise ConfigError("skill_ids keys must be non-empty strings")
        ids = list(skill_ids.values())
        if any(
            not isinstance(skill_id, int) or isinstance(skill_id, bool) or skill_id < 0
            for skill_id in ids
        ):
            raise ConfigError("skill_ids values must be non-negative integers")
        if len(set(ids)) != len(ids):
            raise ConfigError("skill_ids values must be unique")
        if not isinstance(skill_definitions, dict):
            raise ConfigError("skill_definitions must be a dictionary")
        if set(skill_definitions) != set(skill_ids):
            raise ConfigError("skill_definitions keys must match skill_ids keys")
        if any(
            not isinstance(definition, str) or not definition
            for definition in skill_definitions.values()
        ):
            raise ConfigError("skill_definitions values must be non-empty strings")
        if not isinstance(history_limit, int) or isinstance(history_limit, bool):
            raise ConfigError("history_limit must be a non-negative integer")
        if history_limit < 0:
            raise ConfigError("history_limit must be a non-negative integer")
        if max_images is not None and (
            not isinstance(max_images, int)
            or isinstance(max_images, bool)
            or max_images <= 0
        ):
            raise ConfigError("max_images must be a positive integer or null")

        if camera_keys is not None and not isinstance(camera_keys, list):
            raise ConfigError("camera_keys must be a list")
        resolved_camera_keys = (
            ["images", "head_rgb"] if camera_keys is None else camera_keys
        )
        if any(
            not isinstance(camera_key, str) or not camera_key
            for camera_key in resolved_camera_keys
        ):
            raise ConfigError("camera_keys must contain non-empty strings")
        if len(set(resolved_camera_keys)) != len(resolved_camera_keys):
            raise ConfigError("camera_keys must be unique")

        super().__init__(
            backend=backend,
            system_prompt=system_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            extra_body=extra_body,
        )
        self.skill_ids = dict(skill_ids)
        self.skill_definitions = dict(skill_definitions)
        self.camera_keys = list(resolved_camera_keys)
        self.history_limit = history_limit
        self.max_images = max_images
        if response_format_mode not in {"json_schema", "json_object"}:
            raise ConfigError("response_format_mode must be json_schema or json_object")
        self.response_format_mode = response_format_mode
        self.prompt_skill = prompt_skill
        self.last_prompt_manifest: dict[str, Any] | None = None


    def _history_prompt(self, inputs: Mapping[str, Any]) -> str:
        history = inputs.get("history", [])
        if not isinstance(history, list):
            raise PlannerOutputError("SubtaskSkillPlanner history must be a list")
        recent_history = history[-self.history_limit :] if self.history_limit else []
        return json.dumps(recent_history, ensure_ascii=False)

    def _memory_context_prompt(self, inputs: Mapping[str, Any]) -> str:
        return self._memory_prompt(inputs.get("memory_context"))

    def _recovery_context_prompt(self, inputs: Mapping[str, Any]) -> str:
        recovery_context = inputs.get("recovery_context")
        if not self._meaningful_recovery_context(recovery_context):
            return ""
        recovery_prompt = {
            "verifier": self._compact_verification(recovery_context.get("verifier")),
            "memory": self._compact_recovery_memories(recovery_context.get("memory")),
            "recovery_action": recovery_context.get("recovery_action"),
            "partial_recovery_handoff": recovery_context.get(
                "partial_recovery_handoff"
            ),
            "recovery_reconciliation": recovery_context.get(
                "recovery_reconciliation"
            ),
        }
        return json.dumps(to_jsonable(recovery_prompt), ensure_ascii=False)

    @staticmethod
    def _meaningful_recovery_context(value: Any) -> bool:
        if not isinstance(value, Mapping):
            return False
        if value.get("is_replan") is True:
            return True
        if any(
            value.get(key) not in (None, [], {}, "")
            for key in (
                "memory",
                "recovery_action",
                "partial_recovery_handoff",
                "recovery_reconciliation",
            )
        ):
            return True
        verifier = value.get("verifier")
        return bool(
            isinstance(verifier, Mapping)
            and (
                verifier.get("execution_status") in {"failed", "uncertain"}
                or verifier.get("progress_assessment") in {"regressed", "unchanged"}
            )
        )

    def plan(self, inputs: dict[str, Any]) -> dict[str, Any]:
        task = inputs.get("task")
        observation = inputs.get("observation")
        observed_instruction = (
            observation.get("annotation.human.task_description")
            if isinstance(observation, Mapping)
            else None
        )
        if isinstance(observed_instruction, str) and observed_instruction.strip():
            instruction = observed_instruction.strip()
        elif (
            isinstance(task, Mapping)
            and isinstance(task.get("name"), str)
            and task["name"].strip()
        ):
            instruction = task["name"].strip()
        else:
            instruction = self._instruction(task)

        available_skills = inputs.get("available_skills")
        if "available_skills" in inputs:
            if not isinstance(available_skills, list) or not available_skills:
                raise PlannerOutputError(
                    "SubtaskSkillPlanner requires non-empty available_skills"
                )
            if any(
                not isinstance(skill, str) or skill not in self.skill_ids
                for skill in available_skills
            ):
                raise PlannerOutputError(
                    "available_skills must be configured in skill_ids"
                )
            if len(set(available_skills)) != len(available_skills):
                raise PlannerOutputError("available_skills must be unique")
            skills = available_skills
        else:
            skills = list(self.skill_ids)

        history_prompt = self._history_prompt(inputs)
        skill_text = "\n".join(
            f"- {skill} (id={self.skill_ids[skill]}): {self.skill_definitions[skill]}"
            for skill in skills
        )
        planner_context = {
            "reference_subtasks": inputs.get("reference_subtasks", []),
            "planner_current_subtask": inputs.get("planner_current_subtask"),
            "verifier_result": self._compact_verification(inputs.get("verifier_result")),
        }
        prompt = (
            f"Task: {instruction}\n\nReference and checkpoint context:\n"
            f"{json.dumps(to_jsonable(planner_context), ensure_ascii=False)}\n\nSkills:\n{skill_text}\n\n"
            "Recent interaction feedback:\n"
            f"{history_prompt}"
        )
        memory_context = inputs.get("memory_context")
        memory_prompt = self._memory_context_prompt(inputs)
        if memory_prompt:
            prompt += f"\n\nMemory context:\n{memory_prompt}"
        recovery_prompt = self._recovery_context_prompt(inputs)
        if recovery_prompt:
            prompt += (
                "\n\nRecovery context from the previous execution attempt:\n"
                f"{recovery_prompt}"
            )
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        observation_images: list[Any] = []
        if isinstance(observation, Mapping):
            for camera_key in self.camera_keys:
                images = observation.get(camera_key)
                if images is None:
                    continue
                if not isinstance(images, list):
                    images = [images]
                for image in images:
                    observation_images.append(image)
        if self.max_images is not None:
            observation_images = observation_images[: self.max_images]
        for image in observation_images:
            content.append({"type": "image_url", "image_url": {"url": image}})
        memory_images = self._memory_images(memory_context)
        if self.max_images is not None:
            remaining = max(self.max_images - len(observation_images), 0)
            memory_images = memory_images[-remaining:] if remaining else []
        if memory_images:
            content.append(
                {"type": "text", "text": "Visual working memory, oldest to newest"}
            )
            for image in memory_images:
                content.append({"type": "image_url", "image_url": {"url": image}})

        high_skill_prompt = format_high_level_skill_context(
            inputs.get("high_level_skill_context")
        )
        initial_checkpoint = not isinstance(inputs.get("planner_current_subtask"), str)
        allowed_decisions = ["update"] if initial_checkpoint else ["keep", "update"]
        if initial_checkpoint:
            prompt += (
                "\n\nThis is the initial planner checkpoint with no active execution. "
                "You must return decision=update."
            )
            content[0]["text"] = prompt
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": self.system_prompt + high_skill_prompt,
            },
            {"role": "user", "content": content},
        ]
        if self.prompt_skill is not None:
            history = inputs.get("history", [])
            history_events = tuple(
                dict(event) for event in history if isinstance(event, Mapping)
            )
            recovery_context = inputs.get("recovery_context")
            meaningful_recovery = self._meaningful_recovery_context(recovery_context)
            reconciliation = (
                recovery_context.get("recovery_reconciliation")
                if isinstance(recovery_context, Mapping)
                else None
            )
            correctable_target = (
                reconciliation.get("correctable_target")
                if isinstance(reconciliation, Mapping)
                else None
            )
            failure_information = (
                {
                    "scope": (
                        "local_correction"
                        if isinstance(correctable_target, str)
                        and bool(correctable_target.strip())
                        else "node_replan"
                    ),
                    "target_visible": bool(
                        isinstance(correctable_target, str)
                        and correctable_target.strip()
                    ),
                    "failure_class": "execution_or_verification_feedback",
                    "summary": to_jsonable(recovery_context),
                    "correctable_target": correctable_target,
                }
                if meaningful_recovery
                else None
            )
            generated = self.prompt_skill.generate(
                GenerateRequest(
                    role=Role.PLANNER,
                    task={"instruction": instruction},
                    observations=(observation if isinstance(observation, Mapping) else {}),
                    task_state={
                        "task_graph": inputs.get("task_graph"),
                        "reference_subtasks": inputs.get("reference_subtasks", []),
                        "planner_current_subtask": inputs.get("planner_current_subtask"),
                        "verifier_result": inputs.get("verifier_result"),
                        "critical_unknowns": inputs.get("critical_unknowns", []),
                        "recovery_handoff": (
                            recovery_context.get("partial_recovery_handoff")
                            if isinstance(recovery_context, Mapping)
                            else None
                        ),
                        "recovery_reconciliation": reconciliation,
                    },
                    execution_history=history_events,
                    failure_information=failure_information,
                    available_skills=tuple(
                        SkillSpec(
                            skill_id=skill,
                            description=self.skill_definitions[skill],
                        )
                        for skill in skills
                    ),
                    prompt_version=self.prompt_skill.default_version,
                    call_mode=(
                        CallMode.LOCAL_CORRECTION
                        if isinstance(failure_information, Mapping)
                        and failure_information.get("scope") == "local_correction"
                        else CallMode.FAILURE_REPLANNING
                        if failure_information is not None
                        else CallMode.NORMAL_PLANNING
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
        response = self._complete_with_thinking_fallback(
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
                        "name": "subtask_skill",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "decision": {
                                    "type": "string",
                                    "enum": allowed_decisions,
                                },
                                "reasoning": {"type": "string"},
                                "skill": {"type": "string", "enum": skills},
                                "subtask": {"type": "string", "minLength": 1},
                                "grounded_arguments": {
                                    "type": "object",
                                    "additionalProperties": True,
                                },
                                "expected_outcome": {
                                    "type": "string",
                                    "minLength": 1,
                                },
                            },
                            "required": [
                                "decision",
                                "reasoning",
                                "skill",
                                "subtask",
                                "grounded_arguments",
                                "expected_outcome",
                            ],
                            "additionalProperties": False,
                        },
                    },
                }
                ),
                "extra_body": self.extra_body,
            }
        )
        model_output = self._response_text(response)
        parsed = self._parse_json(model_output)
        decision = parsed.get("decision", "update")
        if decision not in {"keep", "update"}:
            raise PlannerOutputError(f"Planner returned invalid decision: {decision!r}")
        skill = parsed.get("skill")
        if not isinstance(skill, str) or skill not in skills:
            raise PlannerOutputError(f"Planner selected unavailable skill: {skill!r}")
        subtask = parsed.get("subtask")
        if not isinstance(subtask, str) or not subtask.strip():
            raise PlannerOutputError("Planner returned an invalid subtask")
        subtask = subtask.strip()
        grounded_arguments = parsed.get("grounded_arguments")
        if not isinstance(grounded_arguments, dict):
            raise PlannerOutputError("Planner returned invalid grounded_arguments")
        expected_outcome = parsed.get("expected_outcome")
        if not isinstance(expected_outcome, str) or not expected_outcome.strip():
            raise PlannerOutputError("Planner returned an invalid expected_outcome")

        return {
            "decision": decision,
            "skill": skill,
            "skill_id": self.skill_ids[skill],
            "subtask": subtask,
            "grounded_arguments": grounded_arguments,
            "expected_outcome": expected_outcome.strip(),
            "reasoning": parsed.get("reasoning", ""),
            "model_output": model_output,
            "raw_response": response,
            "thinking_fallback_used": self.thinking_fallback_used,
        }

    def adjudicate(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Review a verifier candidate before it can change subtask state."""
        candidate = inputs.get("verifier_candidate")
        if not isinstance(candidate, Mapping):
            raise PlannerOutputError("joint adjudication requires verifier_candidate")
        candidate_status = candidate.get("execution_status")
        if candidate_status not in {"completed", "in_progress", "failed", "uncertain"}:
            raise PlannerOutputError(
                f"invalid verifier candidate status: {candidate_status!r}"
            )
        observation = inputs.get("observation")
        task = inputs.get("task")
        payload = {
            "official_goal_contract": inputs.get("goal_contract"),
            "task": task,
            "active_execution": inputs.get("active_execution"),
            "verifier_candidate": candidate,
            "environment_result": inputs.get("environment_result"),
            "task_graph": inputs.get("task_graph"),
            "evidence_ledger": inputs.get("evidence_ledger", []),
        }
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": json.dumps(to_jsonable(payload), ensure_ascii=False),
            }
        ]
        if isinstance(observation, Mapping):
            images: list[Any] = []
            for camera_key in self.camera_keys:
                value = observation.get(camera_key)
                if value is None:
                    continue
                images.extend(value if isinstance(value, list) else [value])
            if self.max_images is not None:
                images = images[: self.max_images]
            for image in images:
                content.append({"type": "image_url", "image_url": {"url": image}})
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": JOINT_ADJUDICATION_PROMPT},
            {"role": "user", "content": content},
        ]
        if self.prompt_skill is not None:
            generated = self.prompt_skill.generate(
                GenerateRequest(
                    role=Role.PLANNER,
                    task={"instruction": self._instruction(task)},
                    observations=(
                        observation if isinstance(observation, Mapping) else {}
                    ),
                    task_state=payload,
                    execution_history=tuple(
                        item
                        for item in inputs.get("evidence_ledger", [])
                        if isinstance(item, Mapping)
                    ),
                    failure_information=(
                        {
                            "scope": "joint_transition_review",
                            "failure_class": "verifier_candidate",
                            "summary": candidate,
                        }
                        if candidate_status in {"failed", "uncertain"}
                        else None
                    ),
                    available_skills=tuple(
                        SkillSpec(
                            skill_id=skill,
                            description=self.skill_definitions[skill],
                        )
                        for skill in self.skill_ids
                    ),
                    prompt_version=self.prompt_skill.default_version,
                    call_mode=CallMode.JOINT_ADJUDICATION,
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
        statuses = ["completed", "in_progress", "failed", "uncertain"]
        response = self._complete_with_thinking_fallback(
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
                            "name": "joint_subtask_adjudication",
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "verifier_decision": {
                                        "type": "string",
                                        "enum": ["accept", "reject", "defer"],
                                    },
                                    "adjudicated_status": {
                                        "type": "string",
                                        "enum": statuses,
                                    },
                                    "evidence_alignment": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "contradictions": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "reasoning": {"type": "string"},
                                },
                                "required": [
                                    "verifier_decision",
                                    "adjudicated_status",
                                    "evidence_alignment",
                                    "contradictions",
                                    "reasoning",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    }
                ),
                "extra_body": self.extra_body,
            }
        )
        parsed = self._parse_json(self._response_text(response))
        decision = parsed.get("verifier_decision")
        status = parsed.get("adjudicated_status")
        if decision not in {"accept", "reject", "defer"} or status not in statuses:
            raise PlannerOutputError("invalid joint adjudication decision")
        for key in ("evidence_alignment", "contradictions"):
            value = parsed.get(key)
            if not isinstance(value, list) or any(
                not isinstance(item, str) for item in value
            ):
                raise PlannerOutputError(f"invalid joint adjudication {key}")
        if decision == "accept" and status != candidate_status:
            raise PlannerOutputError(
                "accept requires adjudicated_status to match verifier candidate"
            )
        return {
            "verifier_decision": decision,
            "adjudicated_status": status,
            "evidence_alignment": parsed["evidence_alignment"][:8],
            "contradictions": parsed["contradictions"][:8],
            "reasoning": str(parsed.get("reasoning", ""))[:2048],
        }
