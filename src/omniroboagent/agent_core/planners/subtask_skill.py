import json
from collections.abc import Mapping
from typing import Any

from omniroboagent.agent_core.planners.language_skill import LanguageSkillPlanner
from omniroboagent.backends.llm.base import LLMBackend
from omniroboagent.exceptions import ConfigError, PlannerOutputError

DEFAULT_SUBTASK_SKILL_PROMPT = """You are an embodied agent executing a
long-horizon task. Select exactly one skill and one concrete subtask for the current
observation. Return continue_subtask only when the selected skill and subtask exactly
match the active ones; otherwise return new_subtask.

Return JSON with exactly these fields:
{
  "reasoning": "short reason",
  "skill": "exact skill name",
  "subtask": "concrete instruction",
  "execution_status": "new_subtask or continue_subtask"
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
        system_prompt: str = DEFAULT_SUBTASK_SKILL_PROMPT,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        extra_body: dict[str, Any] | None = None,
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

        history = inputs.get("history", [])
        if not isinstance(history, list):
            raise PlannerOutputError("SubtaskSkillPlanner history must be a list")
        recent_history = history[-self.history_limit :] if self.history_limit else []
        skill_text = "\n".join(
            f"- {skill} (id={self.skill_ids[skill]}): {self.skill_definitions[skill]}"
            for skill in skills
        )
        active_skill = inputs.get("active_skill")
        active_subtask = inputs.get("active_subtask")
        prompt = (
            f"Task: {instruction}\n\nSkills:\n{skill_text}\n\n"
            f"Active skill: {json.dumps(active_skill, ensure_ascii=False)}\n"
            f"Active subtask: {json.dumps(active_subtask, ensure_ascii=False)}\n\n"
            "Recent interaction feedback:\n"
            f"{json.dumps(recent_history, ensure_ascii=False)}"
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        if isinstance(observation, Mapping):
            for camera_key in self.camera_keys:
                images = observation.get(camera_key)
                if images is None:
                    continue
                if not isinstance(images, list):
                    images = [images]
                for image in images:
                    content.append({"type": "image_url", "image_url": {"url": image}})

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
                        "name": "subtask_skill",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "reasoning": {"type": "string"},
                                "skill": {"type": "string", "enum": skills},
                                "subtask": {"type": "string", "minLength": 1},
                                "execution_status": {
                                    "type": "string",
                                    "enum": [
                                        "new_subtask",
                                        "continue_subtask",
                                    ],
                                },
                            },
                            "required": [
                                "reasoning",
                                "skill",
                                "subtask",
                                "execution_status",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "extra_body": self.extra_body,
            }
        )
        model_output = self._response_text(response)
        parsed = self._parse_json(model_output)
        skill = parsed.get("skill")
        if not isinstance(skill, str) or skill not in skills:
            raise PlannerOutputError(f"Planner selected unavailable skill: {skill!r}")
        subtask = parsed.get("subtask")
        if not isinstance(subtask, str) or not subtask.strip():
            raise PlannerOutputError("Planner returned an invalid subtask")
        subtask = subtask.strip()
        execution_status = parsed.get("execution_status")
        if not isinstance(execution_status, str) or execution_status not in {
            "new_subtask",
            "continue_subtask",
        }:
            raise PlannerOutputError(
                f"Planner returned invalid execution_status: {execution_status!r}"
            )
        if execution_status == "continue_subtask":
            if not isinstance(active_skill, str) or not active_skill:
                raise PlannerOutputError("continue_subtask requires an active skill")
            if skill != active_skill:
                raise PlannerOutputError(
                    "continue_subtask skill does not match active skill: "
                    f"{skill!r} != {active_skill!r}"
                )
            if active_subtask is not None and subtask != active_subtask:
                raise PlannerOutputError(
                    "continue_subtask does not match active subtask: "
                    f"{subtask!r} != {active_subtask!r}"
                )

        return {
            "skill": skill,
            "skill_id": self.skill_ids[skill],
            "subtask": subtask,
            "execution_status": execution_status,
            "reasoning": parsed.get("reasoning", ""),
            "model_output": model_output,
            "raw_response": response,
        }
