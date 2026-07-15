from typing import Any

import pytest

from omniroboagent.agent_core import BaseAgent, Memory, Planner, Verifier
from omniroboagent.backends.skills import SkillBackend


class TrackingPlanner(Planner):
    def __init__(self) -> None:
        self.close_calls = 0

    def plan(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"planned": inputs}

    def close(self) -> None:
        self.close_calls += 1


class TrackingVerifier(Verifier):
    def __init__(self) -> None:
        self.close_calls = 0

    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"verified": inputs}

    def close(self) -> None:
        self.close_calls += 1


class TrackingMemory(Memory):
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.close_calls = 0

    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        self.events.append(event)

    def close(self) -> None:
        self.close_calls += 1


class TrackingSkillBackend(SkillBackend):
    def __init__(self) -> None:
        self.close_calls = 0

    def predict(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"action": inputs}

    def close(self) -> None:
        self.close_calls += 1


class CustomAgent(BaseAgent):
    def plan(self, inputs: dict[str, Any]) -> Any:
        return {"custom_plan": self.planner.plan(inputs)}

    def predict_action(self, inputs: dict[str, Any]) -> Any:
        return {"custom_action": self.skill_backend.predict(inputs)}

    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"custom_verify": self.verifier.verify(inputs)}


def make_agent() -> tuple[
    CustomAgent,
    TrackingPlanner,
    TrackingVerifier,
    TrackingMemory,
    TrackingSkillBackend,
]:
    planner = TrackingPlanner()
    verifier = TrackingVerifier()
    memory = TrackingMemory()
    skill_backend = TrackingSkillBackend()
    return (
        CustomAgent(planner, verifier, memory, skill_backend),
        planner,
        verifier,
        memory,
        skill_backend,
    )


def test_inherited_agent_reuses_composed_components_and_memory_update() -> None:
    agent, _, _, memory, _ = make_agent()

    assert agent.plan({"task": "test"})["custom_plan"]["planned"]["task"] == "test"
    assert agent.predict_action({"skill": "pick"})["custom_action"]["action"] == {
        "skill": "pick"
    }
    assert agent.verify({"result": "ok"})["custom_verify"]["verified"] == {
        "result": "ok"
    }

    event = {"transition": "completed"}
    agent.update({"session_id": "session"}, event)

    assert memory.events == [event]


def test_base_agent_healthcheck_reports_composed_components() -> None:
    agent, _, _, _, _ = make_agent()

    health = agent.healthcheck()

    assert health["healthy"] is True
    assert set(health) == {
        "healthy",
        "planner",
        "verifier",
        "memory",
        "skill_backend",
    }


def test_base_agent_close_is_idempotent() -> None:
    agent, planner, verifier, memory, skill_backend = make_agent()

    agent.close()
    agent.close()

    assert planner.close_calls == 1
    assert verifier.close_calls == 1
    assert memory.close_calls == 1
    assert skill_backend.close_calls == 1


def test_base_agent_close_attempts_all_components_after_error() -> None:
    class FailingPlanner(TrackingPlanner):
        def close(self) -> None:
            super().close()
            raise RuntimeError("planner close failed")

    planner = FailingPlanner()
    verifier = TrackingVerifier()
    memory = TrackingMemory()
    skill_backend = TrackingSkillBackend()
    agent = CustomAgent(planner, verifier, memory, skill_backend)

    with pytest.raises(RuntimeError, match="planner close failed"):
        agent.close()

    assert planner.close_calls == 1
    assert verifier.close_calls == 1
    assert memory.close_calls == 1
    assert skill_backend.close_calls == 1
