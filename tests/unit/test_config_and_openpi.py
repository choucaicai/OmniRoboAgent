import time
from pathlib import Path
from typing import Any

import pytest

from omniroboagent.agents import DefaultAgent
from omniroboagent.backends.skills.openpi import OpenPIWebSocketPolicyBackend
from omniroboagent.config import build_agent, load_yaml
from omniroboagent.exceptions import BackendError, ConfigError


def test_build_agent_from_component_specs() -> None:
    agent = build_agent(
        {
            "agent": {"class_path": "omniroboagent.agents.DefaultAgent"},
            "planner": {
                "class_path": "omniroboagent.planners.LanguageSkillPlanner",
                "init_args": {
                    "backend": {
                        "class_path": (
                            "omniroboagent.backends.llm.OpenAICompatibleLLMBackend"
                        ),
                        "init_args": {
                            "base_url": "http://localhost:8000",
                            "model": "test-model",
                        },
                    }
                },
            },
            "verifier": {"class_path": "omniroboagent.verifiers.EnvironmentVerifier"},
            "memory": {"class_path": "omniroboagent.memory.InMemoryMemory"},
            "skill_backend": {
                "class_path": ("omniroboagent.backends.skills.LanguageSkillBackend")
            },
        }
    )

    assert isinstance(agent, DefaultAgent)
    agent.close()


def test_load_yaml_rejects_non_mapping(tmp_path: Path) -> None:
    path = tmp_path / "invalid.yaml"
    path.write_text("- item\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="Config root must be a mapping"):
        load_yaml(path)


class FakeWebSocket:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeOpenPIClient:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self._ws = FakeWebSocket()

    def infer(self, observation: dict[str, Any]) -> dict[str, Any]:
        return {"actions": [[1.0, 2.0]], "observation": observation}


def test_openpi_backend_returns_action_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = OpenPIWebSocketPolicyBackend(
        host="localhost", port=8001, client_factory=FakeOpenPIClient
    )
    monkeypatch.setattr(backend, "healthcheck", lambda: {"healthy": True})

    actions = backend.predict({"observation": {"state": [0.0]}})
    client = backend.client
    backend.close()

    assert actions == [[1.0, 2.0]]
    assert client._ws.closed is True


def test_openpi_backend_requires_observation_dict() -> None:
    backend = OpenPIWebSocketPolicyBackend("localhost", 8001)

    with pytest.raises(BackendError, match="observation dict"):
        backend.predict({"observation": "invalid"})


class SlowOpenPIClient(FakeOpenPIClient):
    def infer(self, observation: dict[str, Any]) -> dict[str, Any]:
        time.sleep(0.05)
        return super().infer(observation)


def test_openpi_backend_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    backend = OpenPIWebSocketPolicyBackend(
        host="localhost",
        port=8001,
        timeout_seconds=0.001,
        client_factory=SlowOpenPIClient,
    )
    monkeypatch.setattr(backend, "healthcheck", lambda: {"healthy": True})

    with pytest.raises(BackendError, match="timed out"):
        backend.predict({"observation": {"state": [0.0]}})
