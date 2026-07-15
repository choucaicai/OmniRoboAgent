from typing import Any

import numpy as np
import pytest

from omniroboagent.backends.skills.groot import GR00TRemotePolicyBackend
from omniroboagent.exceptions import BackendError


def action_chunk(batch: bool = False) -> dict[str, np.ndarray]:
    prefix = (1, 4) if batch else (4,)
    return {
        "action.end_effector_position": np.zeros((*prefix, 3), dtype=np.float32),
        "action.end_effector_rotation": np.zeros((*prefix, 3), dtype=np.float32),
        "action.gripper_close": np.zeros((*prefix, 1), dtype=np.float32),
        "action.base_motion": np.zeros((*prefix, 4), dtype=np.float32),
        "action.control_mode": np.zeros((*prefix, 1), dtype=np.float32),
    }


class FakeGR00TClient:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.requests: list[dict[str, Any]] = []
        self.reset_calls = 0

    def ping(self) -> bool:
        return True

    def call_endpoint(self, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        assert endpoint == "reset_episode_memory"
        self.reset_calls += 1
        return {"status": "ok"}

    def get_action(self, observation: dict[str, Any]) -> dict[str, np.ndarray]:
        self.requests.append(observation)
        return action_chunk(batch=True)


def groot_inputs(skill: str = "CloseBlenderLid") -> dict[str, Any]:
    return {
        "task": {
            "name": "CloseBlenderLid",
            "episode_index": 0,
        },
        "skill": skill,
        "subtask": "close the blender lid",
        "session_id": "session-1",
        "observation": {
            "video.robot0_agentview_left": np.zeros((256, 256, 3), dtype=np.uint8),
            "video.robot0_agentview_right": np.zeros((256, 256, 3), dtype=np.uint8),
            "video.robot0_eye_in_hand": np.zeros((256, 256, 3), dtype=np.uint8),
            "state.gripper_qpos": np.zeros(2, dtype=np.float32),
            "state.base_position": np.zeros(3, dtype=np.float32),
            "state.base_rotation": np.zeros(4, dtype=np.float32),
            "state.end_effector_position_relative": np.zeros(3, dtype=np.float32),
            "state.end_effector_rotation_relative": np.zeros(4, dtype=np.float32),
            "annotation.human.task_description": "task description",
            "available_skills": ["CloseBlenderLid"],
        },
    }


def test_groot_remote_prepares_temporal_input_and_action_chunk() -> None:
    backend = GR00TRemotePolicyBackend(client_factory=FakeGR00TClient)

    actions = backend.predict(groot_inputs())
    client = backend.client

    assert actions["action.base_motion"].shape == (4, 4)
    assert client.requests[0]["video.robot0_agentview_left"].shape == (
        1,
        1,
        256,
        256,
        3,
    )
    assert client.requests[0]["state.gripper_qpos"].shape == (1, 1, 2)
    assert client.requests[0]["annotation.human.task_description"].tolist() == (
        ["close the blender lid"]
    )
    assert client.requests[0]["skill"].tolist() == ["CloseBlenderLid"]
    assert client.reset_calls == 1


def test_groot_remote_requires_concrete_task_skill() -> None:
    backend = GR00TRemotePolicyBackend(client_factory=FakeGR00TClient)

    with pytest.raises(BackendError, match="requires skill to equal"):
        backend.predict(groot_inputs("Close_Lid"))


def test_groot_remote_accepts_composite_task_with_explicit_skill_id() -> None:
    backend = GR00TRemotePolicyBackend(client_factory=FakeGR00TClient)
    inputs = groot_inputs("Close_Lid")
    inputs["task"]["name"] = "DeliverStraw"
    inputs["planner_output"] = {
        "skill": "Close_Lid",
        "skill_id": 3,
        "subtask": "close the straw container lid",
    }

    backend.predict(inputs)
    request = backend.client.requests[0]

    assert request["task"].tolist() == ["DeliverStraw"]
    assert request["skill"].tolist() == ["Close_Lid"]
    assert request["skill_id"].tolist() == [3]


@pytest.mark.parametrize("skill_id", [None, -1, True, "3"])
def test_groot_remote_rejects_invalid_explicit_skill_id(skill_id: Any) -> None:
    backend = GR00TRemotePolicyBackend(client_factory=FakeGR00TClient)
    inputs = groot_inputs("Close_Lid")
    inputs["task"]["name"] = "DeliverStraw"
    inputs["planner_output"] = {"skill_id": skill_id}

    with pytest.raises(BackendError, match="skill_id must be a non-negative integer"):
        backend.predict(inputs)


def test_groot_remote_requires_complete_panda_omron_observation() -> None:
    backend = GR00TRemotePolicyBackend(client_factory=FakeGR00TClient)
    inputs = groot_inputs()
    del inputs["observation"]["video.robot0_eye_in_hand"]

    with pytest.raises(BackendError, match="missing video"):
        backend.predict(inputs)


def test_groot_remote_rejects_invalid_state_dtype() -> None:
    backend = GR00TRemotePolicyBackend(client_factory=FakeGR00TClient)
    inputs = groot_inputs()
    inputs["observation"]["state.gripper_qpos"] = np.zeros(2, dtype=np.int64)

    with pytest.raises(BackendError, match="finite floats"):
        backend.predict(inputs)


def test_groot_remote_healthcheck() -> None:
    backend = GR00TRemotePolicyBackend(client_factory=FakeGR00TClient)

    assert backend.healthcheck()["healthy"] is True
