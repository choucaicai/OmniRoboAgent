import json
from typing import Any

import httpx
from PIL import Image

from omniroboagent.backends.llm import OpenAICompatibleLLMBackend
from omniroboagent.contracts import LLMBackend
from omniroboagent.planners import LanguageSkillPlanner


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
