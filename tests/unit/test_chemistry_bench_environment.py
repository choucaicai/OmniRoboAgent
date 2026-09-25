import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

import pytest
from PIL import Image

from omniroboagent.agent_core import (
    DefaultAgent,
    EnvironmentVerifier,
    InMemoryMemory,
    Planner,
)
from omniroboagent.backends.skills import LanguageSkillBackend
from omniroboagent.environments.benchmarks.chemistry_bench import (
    ChemistryBenchEnvironment,
)
from omniroboagent.environments.benchmarks.chemistry_bench.environment import TASK_ID
from omniroboagent.exceptions import EnvironmentError
from omniroboagent.pipelines import DirectPipeline
from omniroboagent.runtimes import SyncRuntime


@pytest.fixture
def env() -> ChemistryBenchEnvironment:
    stream = BytesIO()
    Image.new("RGB", (8, 8), "white").save(stream, format="PNG")
    environment = ChemistryBenchEnvironment()
    environment._channel = Mock()
    environment._pb = SimpleNamespace(
        Empty=SimpleNamespace,
        LoadSceneRequest=SimpleNamespace,
        ActionCommandMsg=SimpleNamespace,
    )
    environment._stub = Mock()
    environment._stub.Health.return_value = SimpleNamespace(ok=True)
    environment._stub.LoadScene.return_value = SimpleNamespace(ok=True)
    environment._stub.Act.return_value = SimpleNamespace(
        ok=True, detail_json='{"private": "do not leak"}', error="private error"
    )
    environment._stub.Observe.return_value = SimpleNamespace(
        timestamp=1.0,
        cameras=[
            SimpleNamespace(name="main", width=8, height=8, png=stream.getvalue())
        ],
        privileged_json=json.dumps(
            {
                "vessels": {"beaker": {"color": "colorless", "ph": 1}},
                "findings": [],
            }
        ),
    )
    return environment


def set_truth(env: ChemistryBenchEnvironment, color: str, findings: list[str]) -> None:
    env._stub.Observe.return_value.privileged_json = json.dumps(
        {
            "vessels": {"beaker": {"color": color, "ph": 14}},
            "findings": findings,
        }
    )


@pytest.mark.parametrize(
    "color,findings,success",
    [
        ("colorless", [], False),
        ("pink", [], False),
        ("colorless", ["pink"], False),
        ("pink", ["observed pink"], True),
    ],
)
def test_authoritative_success_and_privacy(env, color, findings, success):
    observation = env.reset(TASK_ID)
    assert set(observation) == {"head_rgb", "available_skills", "timestamp"}
    set_truth(env, color, findings)
    result = env.execute("record finding: beaker is pink")
    assert result["task_success"] is success
    assert result["last_action_success"] is True
    assert "privileged" not in repr(result)
    assert "private" not in repr(result)
    assert "ph" not in result["observation"]


def test_primitive_mapping_and_fresh_observation(env):
    env.reset(TASK_ID)
    env.execute("pour 15 ml into beaker")
    request = env._stub.Act.call_args.args[0]
    assert request.kind == "primitive" and request.primitive == "pour"
    assert json.loads(request.params_json) == {"target": "beaker", "volume_ml": 15}
    assert env._stub.Observe.call_count == 2


def test_invalid_skill_does_not_reach_worker(env):
    env.reset(TASK_ID)
    result = env.execute({"primitive": "pour", "volume_ml": 100000})
    env._stub.Act.assert_not_called()
    assert not result["last_action_success"]
    assert env._stub.Observe.call_count == 2


def test_failed_primitive_is_verified(env):
    env.reset(TASK_ID)
    env._stub.Act.return_value.ok = False
    result = env.execute("pick naoh_bottle")
    assert not result["last_action_success"]
    assert not result["done"]
    assert env._stub.Observe.call_count == 2


def test_reset_uses_original_scene_not_empty_snapshot(env):
    env.reset(TASK_ID)
    env.execute("pour 30 ml into beaker")
    env.reset({"task_id": TASK_ID})
    loads = env._stub.LoadScene.call_args_list
    assert len(loads) == 2 and loads[0] == loads[1]
    env._stub.Reset.assert_not_called()
    assert env._steps == 0


def test_action_timeout_closes_without_replay(env):
    env.reset(TASK_ID)
    channel = env._channel
    env._stub.Act.side_effect = TimeoutError("secret remote payload")
    with pytest.raises(EnvironmentError, match="No automatic replay") as error:
        env.execute("pour 30 ml into beaker")
    assert "secret" not in str(error.value)
    assert env._stub.Act.call_count == 1
    channel.close.assert_called_once()
    with pytest.raises(EnvironmentError):
        env.execute("pour 30 ml into beaker")
    env.close()
    channel.close.assert_called_once()


@pytest.mark.parametrize("truth", ["", "null", "[]", "{}", '{"vessels": {}}'])
def test_missing_truth_fails_closed(env, truth):
    env._stub.Observe.return_value.privileged_json = truth
    with pytest.raises(EnvironmentError, match="observation or task truth"):
        env.reset(TASK_ID)
    assert env._closed


def test_bad_image_fails_closed(env):
    env._stub.Observe.return_value.cameras[0].png = b"not png"
    with pytest.raises(EnvironmentError):
        env.reset(TASK_ID)


def test_lifecycle_and_horizon(env):
    with pytest.raises(EnvironmentError):
        env.execute("observe beaker")
    with pytest.raises(EnvironmentError):
        env.reset("other_task")
    env.max_steps = 1
    env.reset(TASK_ID)
    with pytest.raises(EnvironmentError, match="full execution"):
        env.execute("observe beaker", execute_steps=1)
    result = env.execute("observe beaker")
    assert result["done"] and not result["task_success"]
    with pytest.raises(EnvironmentError):
        env.execute("observe beaker")


def test_runtime_closed_loop(env: ChemistryBenchEnvironment, tmp_path: Path):
    class ScriptedPlanner(Planner):
        def plan(self, inputs: dict[str, Any]) -> dict[str, Any]:
            # Only the fake worker has privileged state; the planner receives pixels.
            assert "privileged_json" not in inputs["observation"]
            return {"skill": "record finding: beaker is pink"}

    def act(request, timeout):
        set_truth(env, "pink", ["observed pink"])
        return SimpleNamespace(ok=True)

    env._stub.Act.side_effect = act
    agent = DefaultAgent(
        planner=ScriptedPlanner(),
        verifier=EnvironmentVerifier(),
        memory=InMemoryMemory(),
        skill_backend=LanguageSkillBackend(),
    )
    result = SyncRuntime(output_dir=tmp_path).run(
        agent, DirectPipeline(), env, {"task_id": TASK_ID, "instruction": "Titrate"}
    )
    assert result["success"] and result["termination_reason"] == "task_success"
    assert result["steps"] == 1 and env._closed
    assert "privileged_json" not in Path(result["trace_path"]).read_text()
