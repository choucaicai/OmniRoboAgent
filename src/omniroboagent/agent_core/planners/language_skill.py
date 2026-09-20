import json
import re
from collections.abc import Mapping
from typing import Any

from omniroboagent.agent_core.planners.base import Planner
from omniroboagent.agent_core.prompting import working_frame_content
from omniroboagent.backends.llm.base import LLMBackend
from omniroboagent.exceptions import PlannerOutputError
from omniroboagent.serialization import to_jsonable

DEFAULT_LANGUAGE_SKILL_PROMPT = """You are an embodied agent operating in a home.
Select exactly one action for the current observation. After the action, the environment
will provide feedback and you will plan again. Do not return a multi-step plan.

Return JSON with exactly these fields:
{"reasoning": "short reason", "skill": "exact action string from the list"}
"""


class LanguageSkillPlanner(Planner):
    def __init__(
        self,
        backend: LLMBackend,
        system_prompt: str = DEFAULT_LANGUAGE_SKILL_PROMPT,
        max_tokens: int = 1024,
        temperature: float = 0.0,
        extra_body: dict[str, Any] | None = None,
    ) -> None:
        self.backend = backend
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra_body = extra_body or {}

    def healthcheck(self) -> dict[str, Any]:
        return self.backend.healthcheck()

    def close(self) -> None:
        self.backend.close()

    def plan(self, inputs: dict[str, Any]) -> dict[str, Any]:
        available_skills = inputs.get("available_skills")
        if not isinstance(available_skills, list) or not available_skills:
            raise PlannerOutputError("LanguageSkillPlanner requires available_skills")
        instruction = self._instruction(inputs.get("task"))
        history = inputs.get("history", [])
        action_text = "\n".join(
            f"{index}: {skill}" for index, skill in enumerate(available_skills)
        )
        prompt = (
            f"Task: {instruction}\n\nAvailable actions:\n{action_text}\n\n"
            f"Previous interaction feedback:\n{json.dumps(history, ensure_ascii=False)}"
        )
        memory_context = inputs.get("memory_context")
        memory_prompt = self._memory_prompt(memory_context)
        if memory_prompt:
            prompt += f"\n\nMemory context:\n{memory_prompt}"
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        observation = inputs.get("observation")
        if isinstance(observation, dict):
            images = observation.get("images")
            if images is None and observation.get("head_rgb") is not None:
                images = [observation["head_rgb"]]
            elif images is not None and not isinstance(images, list):
                images = [images]
            for image in images or []:
                content.append({"type": "image_url", "image_url": {"url": image}})
        content.extend(working_frame_content(memory_context))

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
                        "name": "language_skill",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "reasoning": {"type": "string"},
                                "skill": {
                                    "type": "string",
                                    "enum": [str(skill) for skill in available_skills],
                                },
                            },
                            "required": ["reasoning", "skill"],
                            "additionalProperties": False,
                        },
                    },
                },
                "extra_body": self.extra_body,
            }
        )
        model_output = self._response_text(response)
        parsed = self._parse_json(model_output)
        skill = self._select_skill(parsed, available_skills)
        return {
            "skill": skill,
            "reasoning": parsed.get("reasoning")
            or parsed.get("reasoning_and_reflection", ""),
            "model_output": model_output,
            "raw_response": response,
        }

    @staticmethod
    def _instruction(task: Any) -> str:
        if isinstance(task, dict):
            for key in ("instruction", "task", "description"):
                if key in task:
                    return str(task[key])
        return str(task)

    @staticmethod
    def _response_text(response: dict[str, Any]) -> str:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise PlannerOutputError(
                "LLM response is missing choices[0].message.content"
            ) from error
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(item.get("text", "")) for item in content if isinstance(item, dict)
            )
        reasoning_content = response["choices"][0]["message"].get("reasoning_content")
        if isinstance(reasoning_content, str) and "{" in reasoning_content:
            return reasoning_content
        raise PlannerOutputError(
            "LLM response content is empty; increase max_tokens or disable reasoning"
        )

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
                raise PlannerOutputError(
                    f"Planner returned invalid JSON: {text}"
                ) from error
            try:
                parsed = json.loads(stripped[start : end + 1])
            except json.JSONDecodeError as nested_error:
                raise PlannerOutputError(
                    f"Planner returned invalid JSON: {text}"
                ) from nested_error
        if not isinstance(parsed, dict):
            raise PlannerOutputError("Planner JSON output must be an object")
        return parsed

    @staticmethod
    def _select_skill(parsed: dict[str, Any], available_skills: list[Any]) -> Any:
        if "skill" in parsed:
            skill = parsed["skill"]
        elif "action_id" in parsed:
            action_id = parsed["action_id"]
            if not isinstance(action_id, int) or not 0 <= action_id < len(
                available_skills
            ):
                raise PlannerOutputError(f"Invalid action_id: {action_id!r}")
            skill = available_skills[action_id]
        elif (
            isinstance(parsed.get("executable_plan"), list)
            and parsed["executable_plan"]
        ):
            first_action = parsed["executable_plan"][0]
            if not isinstance(first_action, dict):
                raise PlannerOutputError("executable_plan items must be objects")
            if "action_id" in first_action:
                action_id = first_action["action_id"]
                if not isinstance(action_id, int) or not 0 <= action_id < len(
                    available_skills
                ):
                    raise PlannerOutputError(f"Invalid action_id: {action_id!r}")
                skill = available_skills[action_id]
            else:
                skill = first_action.get("action_name")
        else:
            raise PlannerOutputError("Planner JSON is missing skill or action_id")
        if isinstance(skill, str) and skill not in available_skills:
            indexed = re.fullmatch(r"\s*(?:action\s*id\s*)?(\d+)\s*:\s*(.+?)\s*", skill)
            if indexed and indexed.group(2) in available_skills:
                skill = indexed.group(2)
            elif skill.strip().isdigit():
                action_id = int(skill.strip())
                if 0 <= action_id < len(available_skills):
                    skill = available_skills[action_id]
        if skill not in available_skills:
            raise PlannerOutputError(f"Planner selected unavailable skill: {skill!r}")
        return skill

    @staticmethod
    def _memory_prompt(memory_context: Any) -> str:
        if not isinstance(memory_context, Mapping):
            return ""
        summary = memory_context.get("summary", "")
        recent_events = memory_context.get("recent_events", [])
        key_events = memory_context.get("key_events", [])
        lessons = memory_context.get("lessons", [])
        object_state = memory_context.get("object_state", [])
        procedures = memory_context.get("procedures", [])
        if (
            not summary
            and not recent_events
            and not key_events
            and not lessons
            and not object_state
            and not procedures
        ):
            return ""
        payload: dict[str, Any] = {
            "summary": summary,
            "recent_events": (
                recent_events[-10:]
                if isinstance(recent_events, list)
                else recent_events
            ),
            "key_events": (
                key_events[-10:] if isinstance(key_events, list) else key_events
            ),
        }
        if isinstance(procedures, list) and procedures:
            payload["procedures"] = [
                procedure.get("text")
                for procedure in procedures
                if isinstance(procedure, Mapping)
            ]
        if isinstance(object_state, list) and object_state:
            payload["object_state"] = [
                entry.get("text")
                for entry in object_state
                if isinstance(entry, Mapping)
            ]
        if isinstance(lessons, list) and lessons:
            payload["lessons"] = [
                {
                    "lesson_id": lesson.get("lesson_id"),
                    "text": lesson.get("text"),
                }
                for lesson in lessons
                if isinstance(lesson, Mapping)
            ]
        return json.dumps(to_jsonable(payload), ensure_ascii=False)
