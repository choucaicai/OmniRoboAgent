from typing import Any

import pytest
from PIL import Image

from omniroboagent.agent_core import SubtaskVerifier
from omniroboagent.backends.llm import LLMBackend
from omniroboagent.exceptions import ConfigError, VerifierOutputError


class FakeLLMBackend(LLMBackend):
    def __init__(self, content: str) -> None:
        self.content = content
        self.inputs: dict[str, Any] = {}
        self.calls = 0
        self.closed = False

    def complete(self, inputs: dict[str, Any]) -> dict[str, Any]:
        self.inputs = inputs
        self.calls += 1
        return {"choices": [{"message": {"content": self.content}}]}

    def close(self) -> None:
        self.closed = True


def make_inputs(**result: Any) -> dict[str, Any]:
    return {
        "task": "prepare a drink",
        "observation": {"head_rgb": Image.new("RGB", (2, 2), "red")},
        "active_execution": {
            "skill": "CloseFridge",
            "subtask": "close the fridge door",
            "grounded_arguments": {"target": "fridge door"},
            "expected_outcome": "the fridge door is fully closed",
            "chunk_count": 1,
        },
        "environment_result": {
            "observation": {"head_rgb": Image.new("RGB", (2, 2), "blue")},
            "task_success": False,
            "task_progress": 0.5,
            "last_action_success": True,
            "done": False,
            **result,
        },
    }


def test_subtask_verifier_preserves_authoritative_task_success() -> None:
    backend = FakeLLMBackend("{}")

    output = SubtaskVerifier(backend).verify(make_inputs(task_success=True))

    assert output["task_success"] is True
    assert output["execution_status"] == "completed"
    assert output["confidence"] == 1.0
    assert backend.calls == 0


def test_subtask_verifier_classifies_action_failure() -> None:
    output = SubtaskVerifier().verify(
        make_inputs(last_action_success=False, env_feedback="grasp failed")
    )

    assert output["execution_status"] == "failed"
    assert output["reason"] == "grasp failed"


def test_subtask_verifier_uses_structured_environment_status() -> None:
    output = SubtaskVerifier().verify(
        make_inputs(
            execution_status="uncertain",
            verification_reason="target is occluded",
            verification_confidence=0.4,
            verification_evidence=["door edge is not visible"],
        )
    )

    assert output["execution_status"] == "uncertain"
    assert output["reason"] == "target is occluded"
    assert output["evidence"] == ["door edge is not visible"]


def test_subtask_verifier_calls_vlm_with_before_after_images() -> None:
    backend = FakeLLMBackend(
        '{"execution_status":"completed","reason":"door is closed",'
        '"confidence":0.9,"evidence":["door is flush with the frame"]}'
    )

    inputs = make_inputs()
    inputs["memory_context"] = {
        "summary": "the door was moving toward closed",
        "recent_events": [{"status": "in_progress"}],
        "key_events": [
            {
                "event_type": "subtask_completed",
                "text_summary": "the cabinet is open",
            }
        ],
        "working_frames": [
            {"cameras": {"history": Image.new("RGB", (2, 2), "green")}}
        ],
    }

    output = SubtaskVerifier(backend).verify(inputs)

    assert output["execution_status"] == "completed"
    assert output["confidence"] == 0.9
    content = backend.inputs["messages"][1]["content"]
    assert sum(item["type"] == "image_url" for item in content) == 3
    assert "expected_outcome" in content[0]["text"]
    assert "door was moving" in content[0]["text"]
    assert "cabinet is open" in content[0]["text"]


def test_subtask_verifier_applies_the_memory_char_budget() -> None:
    backend = FakeLLMBackend(
        '{"execution_status":"completed","reason":"door is closed",'
        '"confidence":0.9,"evidence":["door is flush with the frame"]}'
    )
    inputs = make_inputs()
    inputs["memory_context"] = {
        "summary": "a long narrative that cannot survive this budget",
        "object_state": [{"text": "the cabinet is open"}],
    }

    SubtaskVerifier(backend, memory_char_budget=60).verify(inputs)

    prompt = backend.inputs["messages"][1]["content"][0]["text"]
    assert "the cabinet is open" in prompt
    assert "a long narrative" not in prompt


def test_subtask_verifier_rejects_a_non_positive_memory_budget() -> None:
    with pytest.raises(ConfigError, match="memory_char_budget must be positive"):
        SubtaskVerifier(FakeLLMBackend("{}"), memory_char_budget=0)


def test_subtask_verifier_defers_semantic_check_by_chunk_interval() -> None:
    backend = FakeLLMBackend("{}")
    inputs = make_inputs()
    inputs["active_execution"]["chunk_count"] = 2

    output = SubtaskVerifier(backend, check_interval_chunks=3).verify(inputs)

    assert output["execution_status"] == "in_progress"
    assert "deferred" in output["reason"]
    assert backend.calls == 0


def test_subtask_verifier_rejects_invalid_model_status() -> None:
    backend = FakeLLMBackend(
        '{"execution_status":"done","reason":"done",'
        '"confidence":1.0,"evidence":[]}'
    )

    with pytest.raises(VerifierOutputError, match="execution_status"):
        SubtaskVerifier(backend).verify(make_inputs())


def test_subtask_verifier_closes_backend() -> None:
    backend = FakeLLMBackend("{}")

    SubtaskVerifier(backend).close()

    assert backend.closed is True
