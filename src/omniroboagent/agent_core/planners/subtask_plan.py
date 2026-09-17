import json
from pathlib import Path
from typing import Any

from omniroboagent.agent_core.planners.base import Planner
from omniroboagent.backends.llm.base import LLMBackend
from omniroboagent.exceptions import PlannerOutputError

PLAN_PROMPT = (
    "From the current images and complete task, generate the full ordered subtask "
    "sequence. Each instruction will be sent directly to the short-horizon VLA, "
    "so keep the exact object, destination, and relation. Do not assign a left or "
    "right arm; the VLA chooses the arm from the current images. Use concise "
    "physical stages and do not add non-physical checking steps. Each "
    "success_condition must be one visible condition for that subtask. Return "
    'exactly {"subtasks":[{"instruction":"...","success_condition":"..."}]} '
    "with no other fields."
)

SCHEDULED_PLAN_PROMPT = (
    "From the initial images and complete task, generate the full ordered execution "
    "plan once. Each item must select one available skill, give one concise subtask "
    "instruction for the short-horizon VLA, one visible success condition, and a "
    "positive action-chunk budget. Preserve the demonstrated task-specific branch "
    "and object order. Do not add checking steps or arm assignments. Use zero-based "
    "consecutive subtask_index values. Return exactly "
    '{"subtasks":[{"subtask_index":0,"skill":"...","instruction":"...",'
    '"success_condition":"...","chunk_budget":1}]} with no other fields.'
)

SCHEDULED_SELECTION_PROMPT = (
    "Select the one subtask that must run now from the previously generated "
    "execution_plan. Follow the explicit progress exactly: do not skip, repeat, "
    "rewrite, or add a subtask. Copy the selected plan item verbatim. The current "
    "images and recent history are context for the normal Omni planner call. "
    "Return exactly one object with subtask_index, skill, instruction, "
    "success_condition, and chunk_budget, with no other fields."
)


class SubtaskPlanPlanner(Planner):
    """Expose an ordered plan as Omni proposals, advancing on verified completion."""

    def __init__(
        self,
        plan_path: str | None = None,
        backend: LLMBackend | None = None,
        camera_keys: list[str] | None = None,
        max_tokens: int = 2048,
        system_prompt: str | None = None,
        scheduled_chunks: bool = False,
    ) -> None:
        if plan_path is None and backend is None:
            raise ValueError("Provide plan_path or a planner backend")
        self.plan_path = Path(plan_path) if plan_path else None
        self.backend = backend
        self.camera_keys = camera_keys or ["head_rgb", "left_rgb", "right_rgb"]
        self.max_tokens = max_tokens
        self.scheduled_chunks = scheduled_chunks
        self.system_prompt = system_prompt or (
            SCHEDULED_PLAN_PROMPT if scheduled_chunks else PLAN_PROMPT
        )
        self._plan: list[dict[str, Any]] = []
        self._completed_offset = 0
        self._failed_count = 0

    def healthcheck(self) -> dict[str, Any]:
        if self.plan_path is not None and not self.plan_path.is_file():
            return {"healthy": False, "error": f"Missing plan: {self.plan_path}"}
        return self.backend.healthcheck() if self.backend else {"healthy": True}

    def close(self) -> None:
        if self.backend:
            self.backend.close()

    def plan(self, inputs: dict[str, Any]) -> dict[str, Any]:
        completed = inputs.get("completed_executions", [])
        failed = inputs.get("failed_executions", [])
        if inputs.get("step", 0) == 0:
            self._plan = []
            self._completed_offset = 0
            self._failed_count = 0
        recovering = len(failed) > self._failed_count
        if not self._plan or (recovering and self.backend is not None):
            available_skills = inputs.get("available_skills")
            if self.scheduled_chunks and (
                not isinstance(available_skills, list) or not available_skills
            ):
                raise PlannerOutputError(
                    "Scheduled plan requires non-empty available_skills"
                )
            if self.plan_path is not None and not recovering:
                payload = json.loads(self.plan_path.read_text(encoding="utf-8"))
            else:
                if self.backend is None:
                    raise PlannerOutputError("Replanning requires a model backend")
                observation = inputs["observation"]
                context = {
                    "task": observation.get(
                        "annotation.human.task_description", inputs["task"]
                    ),
                    "image_roles": self.camera_keys,
                }
                if self.scheduled_chunks:
                    context["available_skills"] = available_skills
                if observation.get("grounding") is not None:
                    context["grounding"] = observation["grounding"]
                if recovering:
                    context.update(
                        previous_plan=self._plan,
                        completed_subtasks=completed,
                        failed_subtasks=failed,
                        recent_history=inputs.get("history", [])[-20:],
                        recovery_instruction="Plan only the remaining work.",
                    )
                content: list[dict[str, Any]] = [
                    {"type": "text", "text": json.dumps(context)}
                ]
                for key in self.camera_keys:
                    if observation.get(key) is not None:
                        content.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": observation[key]},
                            }
                        )
                request: dict[str, Any] = {
                    "messages": [
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": content},
                    ],
                    "temperature": 0.0,
                    "max_tokens": self.max_tokens,
                }
                if self.scheduled_chunks:
                    request["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "subtask_plan",
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "subtasks": {
                                        "type": "array",
                                        "minItems": 1,
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "subtask_index": {
                                                    "type": "integer",
                                                    "minimum": 0,
                                                },
                                                "skill": {
                                                    "type": "string",
                                                    "enum": available_skills,
                                                },
                                                "instruction": {
                                                    "type": "string",
                                                    "minLength": 1,
                                                },
                                                "success_condition": {
                                                    "type": "string",
                                                    "minLength": 1,
                                                },
                                                "chunk_budget": {
                                                    "type": "integer",
                                                    "minimum": 1,
                                                },
                                            },
                                            "required": [
                                                "subtask_index",
                                                "skill",
                                                "instruction",
                                                "success_condition",
                                                "chunk_budget",
                                            ],
                                            "additionalProperties": False,
                                        },
                                    }
                                },
                                "required": ["subtasks"],
                                "additionalProperties": False,
                            },
                        },
                    }
                response = self.backend.complete(request)
                try:
                    payload = json.loads(response["choices"][0]["message"]["content"])
                except (KeyError, IndexError, TypeError, ValueError) as error:
                    raise PlannerOutputError(
                        "Model returned an invalid plan JSON"
                    ) from error
            plan = payload.get("subtasks") if isinstance(payload, dict) else None
            if not isinstance(plan, list) or not plan:
                raise PlannerOutputError("Plan requires non-empty subtasks")
            for index, item in enumerate(plan):
                if not isinstance(item, dict) or any(
                    not isinstance(item.get(key), str) or not item[key].strip()
                    for key in ("instruction", "success_condition")
                ):
                    raise PlannerOutputError(
                        "Each subtask requires instruction and success_condition"
                    )
                if self.scheduled_chunks:
                    if item.get("subtask_index") != index:
                        raise PlannerOutputError(
                            "Scheduled plan requires consecutive subtask_index values"
                        )
                    if (
                        not isinstance(item.get("skill"), str)
                        or item["skill"] not in available_skills
                    ):
                        raise PlannerOutputError(
                            "Scheduled plan requires an available skill per subtask"
                        )
                    budget = item.get("chunk_budget")
                    if type(budget) is not int or budget <= 0:
                        raise PlannerOutputError(
                            "Scheduled plan requires a positive chunk_budget "
                            "per subtask"
                        )
            self._plan = plan
            self._completed_offset = len(completed)
        self._failed_count = len(failed)
        index = len(completed) - self._completed_offset
        if index >= len(self._plan):
            return {"plan_complete": True}
        item = self._plan[index]
        if self.scheduled_chunks and self.backend is not None:
            observation = inputs["observation"]
            selection_context = {
                "task": observation.get(
                    "annotation.human.task_description", inputs["task"]
                ),
                "image_roles": self.camera_keys,
                "available_skills": inputs.get("available_skills", []),
                "execution_plan": self._plan,
                "progress": {
                    "completed_subtask_count": index,
                    "completed_subtask_indices": list(range(index)),
                    "current_subtask_index": index,
                    "current_chunk": 0,
                    "current_chunk_budget": item["chunk_budget"],
                    "total_subtasks": len(self._plan),
                },
                "recent_history": inputs.get("history", [])[-20:],
            }
            content: list[dict[str, Any]] = [
                {
                    "type": "text",
                    "text": json.dumps(selection_context, ensure_ascii=False),
                }
            ]
            for key in self.camera_keys:
                if observation.get(key) is not None:
                    content.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": observation[key]},
                        }
                    )
            response = self.backend.complete(
                {
                    "messages": [
                        {"role": "system", "content": SCHEDULED_SELECTION_PROMPT},
                        {"role": "user", "content": content},
                    ],
                    "temperature": 0.0,
                    "max_tokens": min(self.max_tokens, 512),
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "subtask_selection",
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "subtask_index": {
                                        "type": "integer",
                                        "minimum": 0,
                                    },
                                    "skill": {
                                        "type": "string",
                                        "enum": inputs.get("available_skills", []),
                                    },
                                    "instruction": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                    "success_condition": {
                                        "type": "string",
                                        "minLength": 1,
                                    },
                                    "chunk_budget": {
                                        "type": "integer",
                                        "minimum": 1,
                                    },
                                },
                                "required": [
                                    "subtask_index",
                                    "skill",
                                    "instruction",
                                    "success_condition",
                                    "chunk_budget",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    },
                }
            )
            try:
                selected = json.loads(response["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError, ValueError) as error:
                raise PlannerOutputError(
                    "Model returned an invalid subtask selection JSON"
                ) from error
            if selected != item:
                raise PlannerOutputError(
                    "Selected subtask must exactly match the current plan item"
                )
            item = selected
        grounded_arguments = dict(item.get("grounded_arguments") or {})
        if self.scheduled_chunks:
            grounded_arguments["subtask_index"] = item["subtask_index"]
        return {
            "skill": item.get("skill", "subtask"),
            "subtask": item["instruction"],
            "expected_outcome": item["success_condition"],
            "grounded_arguments": grounded_arguments,
            "plan_index": index,
            "plan": self._plan,
        }
