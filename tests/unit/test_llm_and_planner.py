import json
from typing import Any

import httpx
import pytest
from PIL import Image

from omniroboagent.agent_core import LanguageSkillPlanner, SubtaskSkillPlanner
from omniroboagent.backends.llm import LLMBackend, OpenAICompatibleLLMBackend
from omniroboagent.exceptions import ConfigError, PlannerOutputError


def test_openai_backend_health_and_multimodal_request() -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "test-model"}]})
        payload = json.loads(request.content)
        requests.append(payload)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"skill":"find a Mug"}'}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1},
            },
        )

    backend = OpenAICompatibleLLMBackend(
        "http://localhost:8000",
        "test-model",
        transport=httpx.MockTransport(handler),
    )
    image = Image.new("RGB", (2, 2), color="red")

    assert backend.healthcheck()["healthy"] is True
    result = backend.complete(
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "choose"},
                        {"type": "image_url", "image_url": {"url": image}},
                        {"type": "image_url", "image_url": {"url": image}},
                    ],
                }
            ]
        }
    )

    assert result["usage"]["prompt_tokens"] == 1
    content = requests[0]["messages"][0]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[2]["image_url"]["url"].startswith("data:image/png;base64,")


class FakeLLMBackend(LLMBackend):
    def __init__(self, content: str) -> None:
        self.content = content
        self.inputs: dict[str, Any] = {}

    def complete(self, inputs: dict[str, Any]) -> dict[str, Any]:
        self.inputs = inputs
        return {"choices": [{"message": {"content": self.content}}]}


def test_language_skill_planner_selects_one_skill() -> None:
    backend = FakeLLMBackend('{"reasoning":"visible mug", "skill":"find a Mug"}')
    planner = LanguageSkillPlanner(backend)

    output = planner.plan(
        {
            "task": {"instruction": "find the mug"},
            "observation": {"head_rgb": Image.new("RGB", (2, 2))},
            "available_skills": ["find a Mug", "pick up the Mug"],
            "history": [],
        }
    )

    assert output["skill"] == "find a Mug"
    assert len(backend.inputs["messages"][1]["content"]) == 2


def test_language_skill_planner_uses_explicit_memory_context() -> None:
    backend = FakeLLMBackend('{"reasoning":"memory","skill":"find a Mug"}')
    planner = LanguageSkillPlanner(backend)
    memory_image = Image.new("RGB", (2, 2), color="blue")

    planner.plan(
        {
            "task": "find mug",
            "observation": {},
            "available_skills": ["find a Mug"],
            "memory_context": {
                "summary": "the mug was last seen near the sink",
                "recent_events": [{"status": "in_progress"}],
                "key_events": [
                    {
                        "event_type": "subtask_completed",
                        "text_summary": "opened the cabinet",
                    }
                ],
                "working_frames": [
                    {
                        "step": 7,
                        "event_type": "subtask_failed",
                        "status": "failed",
                        "cameras": {"head": memory_image},
                    }
                ],
                "procedures": [{"text": "task=find mug successes=1 steps=1) MoveTo|"}],
            },
        }
    )

    content = backend.inputs["messages"][1]["content"]
    assert "mug was last seen" in content[0]["text"]
    assert "opened the cabinet" in content[0]["text"]
    assert "successes=1" in content[0]["text"]
    assert content[-2]["text"] == "step=7 event=subtask_failed status=failed"
    assert content[-1]["image_url"]["url"] is memory_image


def test_language_skill_planner_accepts_baseline_action_id() -> None:
    backend = FakeLLMBackend(
        '{"reasoning_and_reflection":"next", "executable_plan":'
        '[{"action_id":1,"action_name":"pick up the Mug"}]}'
    )

    output = LanguageSkillPlanner(backend).plan(
        {
            "task": "pick mug",
            "observation": {},
            "available_skills": ["find a Mug", "pick up the Mug"],
        }
    )

    assert output["skill"] == "pick up the Mug"


def test_language_skill_planner_strips_index_prefix() -> None:
    backend = FakeLLMBackend('{"reasoning":"next", "skill":"1: pick up the Mug"}')

    output = LanguageSkillPlanner(backend).plan(
        {
            "task": "pick mug",
            "observation": {},
            "available_skills": ["find a Mug", "pick up the Mug"],
        }
    )

    assert output["skill"] == "pick up the Mug"


def test_subtask_skill_planner_maps_skill_and_limits_context() -> None:
    backend = FakeLLMBackend(
        '{"reasoning":"the fridge is open","skill":"CloseFridge",'
        '"subtask":"close the fridge door",'
        '"grounded_arguments":{"target":"fridge door"},'
        '"expected_outcome":"the fridge door is fully closed"}'
    )
    planner = SubtaskSkillPlanner(
        backend,
        skill_ids={"OpenFridge": 3, "CloseFridge": 7},
        skill_definitions={
            "OpenFridge": "Open the fridge door.",
            "CloseFridge": "Close the fridge door.",
        },
        camera_keys=["left_rgb", "wrist_rgb"],
        history_limit=2,
    )

    output = planner.plan(
        {
            "task": {"name": "Fallback task name"},
            "observation": {
                "annotation.human.task_description": "Prepare a cold drink",
                "left_rgb": Image.new("RGB", (2, 2)),
                "wrist_rgb": Image.new("RGB", (2, 2)),
                "ignored_rgb": Image.new("RGB", (2, 2)),
            },
            "available_skills": ["CloseFridge"],
            "history": [
                {"step": 0, "feedback": "old"},
                {"step": 1, "feedback": "recent"},
                {"step": 2, "feedback": "latest"},
            ],
        }
    )

    assert output["skill"] == "CloseFridge"
    assert output["skill_id"] == 7
    assert output["subtask"] == "close the fridge door"
    assert output["grounded_arguments"] == {"target": "fridge door"}
    assert output["expected_outcome"] == "the fridge door is fully closed"
    assert "execution_status" not in output
    user_content = backend.inputs["messages"][1]["content"]
    assert len(user_content) == 3
    assert '"feedback": "old"' not in user_content[0]["text"]
    assert '"feedback": "recent"' in user_content[0]["text"]
    assert "Task: Prepare a cold drink" in user_content[0]["text"]
    assert "Fallback task name" not in user_content[0]["text"]
    assert "Open the fridge door." not in user_content[0]["text"]
    schema = backend.inputs["response_format"]["json_schema"]["schema"]
    assert schema["properties"]["skill"]["enum"] == ["CloseFridge"]
    assert "skill_id" not in schema["properties"]
    assert "execution_status" not in schema["properties"]


def test_subtask_skill_planner_requires_matching_skill_definitions() -> None:
    with pytest.raises(ConfigError, match="keys must match"):
        SubtaskSkillPlanner(
            FakeLLMBackend("{}"),
            skill_ids={"CloseFridge": 7},
            skill_definitions={"OpenFridge": "Open the fridge door."},
        )


def test_subtask_skill_planner_does_not_trust_model_skill_id() -> None:
    planner = SubtaskSkillPlanner(
        FakeLLMBackend(
            '{"reasoning":"close it","action_id":7,'
            '"subtask":"close the fridge door",'
            '"grounded_arguments":{"target":"fridge"},'
            '"expected_outcome":"closed"}'
        ),
        skill_ids={"CloseFridge": 7},
        skill_definitions={"CloseFridge": "Close the fridge door."},
    )

    with pytest.raises(PlannerOutputError, match="unavailable skill"):
        planner.plan({"task": "Prepare a cold drink", "observation": {}})


@pytest.mark.parametrize("available_skills", [[], ["UnknownSkill"]])
def test_subtask_skill_planner_rejects_invalid_available_skills(
    available_skills: list[str],
) -> None:
    planner = SubtaskSkillPlanner(
        FakeLLMBackend("{}"),
        skill_ids={"CloseFridge": 7},
        skill_definitions={"CloseFridge": "Close the fridge door."},
    )

    with pytest.raises(PlannerOutputError, match="available_skills"):
        planner.plan(
            {
                "task": "Prepare a cold drink",
                "observation": {},
                "available_skills": available_skills,
            }
        )


def test_subtask_skill_planner_requires_expected_outcome() -> None:
    planner = SubtaskSkillPlanner(
        FakeLLMBackend(
            '{"reasoning":"close it","skill":"CloseFridge",'
            '"subtask":"close the fridge door",'
            '"grounded_arguments":{"target":"fridge"}}'
        ),
        skill_ids={"CloseFridge": 7},
        skill_definitions={"CloseFridge": "Close the fridge door."},
    )

    with pytest.raises(PlannerOutputError, match="expected_outcome"):
        planner.plan({"task": "Prepare a cold drink", "observation": {}})
