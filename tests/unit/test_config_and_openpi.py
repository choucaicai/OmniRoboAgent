from pathlib import Path
from typing import Any

import numpy as np
import pytest

from omniroboagent.agent_core import DefaultAgent
from omniroboagent.backends.skills.openpi import (
    OpenPIRoboCasaPolicyBackend,
    OpenPIWebSocketPolicyBackend,
)
from omniroboagent.config import build_agent, load_yaml
from omniroboagent.exceptions import BackendError, ConfigError


def test_build_agent_from_component_specs() -> None:
    agent = build_agent(
        {
            "agent": {"class_path": "omniroboagent.agent_core.DefaultAgent"},
            "planner": {
                "class_path": "omniroboagent.agent_core.LanguageSkillPlanner",
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
            "verifier": {"class_path": "omniroboagent.agent_core.EnvironmentVerifier"},
            "memory": {"class_path": "omniroboagent.agent_core.InMemoryMemory"},
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
        self.observation = observation
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


def test_openpi_backend_adds_skill_and_subtask(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = OpenPIWebSocketPolicyBackend(
        host="ws://localhost", port=8001, client_factory=FakeOpenPIClient
    )
    monkeypatch.setattr(backend, "healthcheck", lambda: {"healthy": True})

    backend.predict(
        {
            "observation": {"state": [0.0]},
            "skill": "CloseBlenderLid",
            "subtask": "close the blender lid",
        }
    )

    assert backend.client.observation["skill"] == "CloseBlenderLid"
    assert backend.client.observation["prompt"] == "close the blender lid"
    assert (
        backend.client.observation["annotation.human.task_description"]
        == "close the blender lid"
    )


class FakeRoboCasaOpenPIClient(FakeOpenPIClient):
    def infer(self, observation: dict[str, Any]) -> dict[str, Any]:
        self.observation = observation
        return {"actions": np.zeros((10, 12), dtype=np.float32)}


def test_openpi_robocasa_backend_maps_observation_and_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = OpenPIRoboCasaPolicyBackend(
        host="localhost", port=8001, client_factory=FakeRoboCasaOpenPIClient
    )
    monkeypatch.setattr(backend, "healthcheck", lambda: {"healthy": True})
    observation = {
        "video.robot0_agentview_left": np.zeros((256, 256, 3), dtype=np.uint8),
        "video.robot0_agentview_right": np.zeros((256, 256, 3), dtype=np.uint8),
        "video.robot0_eye_in_hand": np.zeros((256, 256, 3), dtype=np.uint8),
        "state.end_effector_position_relative": np.zeros(3, dtype=np.float32),
        "state.end_effector_rotation_relative": np.zeros(4, dtype=np.float32),
        "state.base_position": np.zeros(3, dtype=np.float32),
        "state.base_rotation": np.zeros(4, dtype=np.float32),
        "state.gripper_qpos": np.zeros(2, dtype=np.float32),
        "annotation.human.task_description": "fallback prompt",
    }

    actions = backend.predict(
        {
            "observation": observation,
            "skill": "CloseBlenderLid",
            "subtask": "close the blender lid",
        }
    )

    request = backend.client.observation
    assert request["observation/image"].shape == (224, 224, 3)
    assert request["observation/state"].shape == (16,)
    assert request["prompt"] == "close the blender lid"
    assert request["skill"] == "CloseBlenderLid"
    assert actions["action.end_effector_position"].shape == (10, 3)
    assert actions["action.base_motion"].shape == (10, 4)
    assert actions["action.control_mode"].shape == (10, 1)


def test_openpi_backend_requires_observation_dict() -> None:
    backend = OpenPIWebSocketPolicyBackend("localhost", 8001)

    with pytest.raises(BackendError, match="observation dict"):
        backend.predict({"observation": "invalid"})


def test_openpi_backend_rejects_secure_scheme() -> None:
    with pytest.raises(ValueError, match="supports ws:// only"):
        OpenPIWebSocketPolicyBackend("wss://localhost", 8001)


class SlowOpenPIClient(FakeOpenPIClient):
    def infer(self, observation: dict[str, Any]) -> dict[str, Any]:
        raise TimeoutError


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
