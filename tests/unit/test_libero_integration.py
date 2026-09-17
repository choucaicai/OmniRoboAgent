import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from omniroboagent.agent_core import (
    DefaultAgent,
    InMemoryMemory,
    SubtaskVerifier,
    TaskSkillPlanner,
)
from omniroboagent.backends.skills import LiberoPi05PolicyBackend, SkillBackend
from omniroboagent.config import build_agent, build_run_components, load_yaml
from omniroboagent.environments import Environment
from omniroboagent.environments.benchmarks.libero import LiberoEnvironment
from omniroboagent.evals.benchmarks.libero import LiberoEvaluator
from omniroboagent.exceptions import EnvironmentError
from omniroboagent.pipelines import SkillExecutionPipeline
from omniroboagent.runtimes import SyncRuntime


def _install_fake_clawvla(monkeypatch: pytest.MonkeyPatch) -> type[Any]:
    class FakeActionChunk:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    class CameraView:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    class ObservationBundle:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    config = SimpleNamespace(
        environment=SimpleNamespace(params={}, task_name="", seed=0, artifact_dir=""),
        metadata={
            "action_backend": {
                "pretrained_path": "/tmp/pi05",
                "policy_kwargs": {"n_action_steps": 10},
            }
        },
    )
    clawvla = ModuleType("clawvla")
    clawvla.__path__ = []  # type: ignore[attr-defined]
    config_module = ModuleType("clawvla.config")
    config_module.load_config = lambda path: config  # type: ignore[attr-defined]
    envs = ModuleType("clawvla.envs")
    envs.__path__ = []  # type: ignore[attr-defined]
    libero = ModuleType("clawvla.envs.libero")
    libero.LiberoAdapter = object  # type: ignore[attr-defined]
    schema = ModuleType("clawvla.schema")
    schema.ActionChunk = FakeActionChunk  # type: ignore[attr-defined]
    schema.CameraView = CameraView  # type: ignore[attr-defined]
    schema.ObservationBundle = ObservationBundle  # type: ignore[attr-defined]
    action_backends = ModuleType("clawvla.action_backends")
    action_backends.__path__ = []  # type: ignore[attr-defined]
    pi05 = ModuleType("clawvla.action_backends.pi05")
    pi05.Pi05ActionBackend = object  # type: ignore[attr-defined]
    for name, module in {
        "clawvla": clawvla,
        "clawvla.config": config_module,
        "clawvla.envs": envs,
        "clawvla.envs.libero": libero,
        "clawvla.schema": schema,
        "clawvla.action_backends": action_backends,
        "clawvla.action_backends.pi05": pi05,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)
    return FakeActionChunk


def _bundle(tmp_path: Path, suffix: str) -> SimpleNamespace:
    return SimpleNamespace(
        camera_views={
            "agentview": SimpleNamespace(rgb_path=tmp_path / f"agent_{suffix}.png"),
            "wrist": SimpleNamespace(rgb_path=tmp_path / f"wrist_{suffix}.png"),
        },
        raw={
            "libero_state8": [0.0] * 8,
            "summary_ref": str(tmp_path / suffix / "observation.json"),
        },
    )


def test_libero_environment_maps_observation_and_executes_receding_horizon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    action_chunk_type = _install_fake_clawvla(monkeypatch)

    class FakeAdapter:
        def __init__(self, config: Any) -> None:
            self.config = config
            self.step_count = 0
            self.last_observation = _bundle(tmp_path, "reset")
            self.action: Any = None
            self.closed = False

        def capture_views(self, **kwargs: Any) -> Any:
            return self.last_observation

        def execute_action(self, action: Any) -> dict[str, Any]:
            self.action = action
            self.step_count += len(action.commands)
            self.last_observation = _bundle(tmp_path, "after")
            return {
                "status": "action_executed",
                "success": True,
                "done": True,
                "executed_steps": len(action.commands),
            }

        def close(self) -> None:
            self.closed = True

    config_path = tmp_path / "claw.json"
    config_path.write_text("{}", encoding="utf-8")
    environment = LiberoEnvironment(
        config_path=config_path,
        artifact_dir=tmp_path / "artifacts",
        adapter_factory=FakeAdapter,
    )
    observation = environment.reset(
        {
            "suite": "libero_spatial",
            "task_id": 0,
            "name": "pick_up_the_black_bowl",
            "instruction": "pick up the black bowl",
            "init_state_count": 50,
            "episode_index": 3,
            "seed": 7,
        }
    )
    result = environment.execute(
        {
            "action_type": "libero_ee_delta",
            "commands": [[0.0] * 7 for _ in range(8)],
            "source_observation_id": observation["observation_id"],
        },
        execute_steps=5,
    )

    assert observation["images"] == [
        str(tmp_path / "agent_reset.png"),
        str(tmp_path / "wrist_reset.png"),
    ]
    assert observation["libero_state8"] == [0.0] * 8
    assert observation["available_skills"] == ["pick_up_the_black_bowl"]
    assert result["task_success"] is True
    assert result["environment_steps"] == 5
    assert isinstance(environment.adapter.action, action_chunk_type)
    assert environment.adapter.action.control_horizon == 5


def test_libero_environment_rejects_stale_action(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_clawvla(monkeypatch)

    class FakeAdapter:
        step_count = 0

        def __init__(self, config: Any) -> None:
            self.last_observation = _bundle(tmp_path, "reset")

        def capture_views(self, **kwargs: Any) -> Any:
            return self.last_observation

        def close(self) -> None:
            pass

    config_path = tmp_path / "claw.json"
    config_path.write_text("{}", encoding="utf-8")
    environment = LiberoEnvironment(config_path, tmp_path, adapter_factory=FakeAdapter)
    environment.reset(
        {
            "suite": "libero_goal",
            "task_id": 0,
            "name": "task",
            "instruction": "do the task",
            "init_state_count": 50,
        }
    )
    result = environment.execute(
        {
            "action_type": "libero_ee_delta",
            "commands": [[0.0] * 7],
            "source_observation_id": "old-observation",
        }
    )

    assert result["last_action_success"] is False
    assert result["executed_steps"] == 0
    assert "stale observation" in result["env_feedback"]


def test_libero_pi05_backend_passes_subtask_and_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_clawvla(monkeypatch)

    class SerializedChunk:
        def to_dict(self) -> dict[str, Any]:
            return {"action_type": "libero_ee_delta", "commands": [[0.0] * 7]}

    class FakeBackend:
        def __init__(self, config: dict[str, Any]) -> None:
            self.config = config
            self.call: dict[str, Any] | None = None

        def diagnose(self, load_policy: bool = False) -> dict[str, Any]:
            return {
                "pretrained_path": self.config["pretrained_path"],
                "policy_summary": {"checkpoint_format": "lerobot"},
                "lerobot_adapter": {"compatible_for_execution": True},
            }

        def build_action_chunk(self, **kwargs: Any) -> SimpleNamespace:
            self.call = kwargs
            return SimpleNamespace(success=True, action_chunk=SerializedChunk())

    config_path = tmp_path / "claw.json"
    config_path.write_text("{}", encoding="utf-8")
    backend = LiberoPi05PolicyBackend(
        config_path=config_path,
        pretrained_path=tmp_path / "checkpoint",
        horizon=50,
        tokenizer_name=tmp_path / "tokenizer.model",
        backend_factory=FakeBackend,
    )
    action = backend.predict(
        {
            "skill": "pick_up_the_black_bowl",
            "subtask": "pick up the black bowl",
            "observation": {
                "observation_id": "episode:0",
                "agentview_rgb": str(tmp_path / "agent.png"),
                "wrist_rgb": str(tmp_path / "wrist.png"),
                "libero_state8": [0.0] * 8,
                "suite": "libero_spatial",
                "task_id": 0,
                "task_name": "pick_up_the_black_bowl",
            },
        }
    )

    assert backend.healthcheck()["healthy"] is True
    assert action["source_observation_id"] == "episode:0"
    assert action["vla_prompt"] == "pick up the black bowl"
    assert backend.backend.config["policy_kwargs"]["n_action_steps"] == 50
    assert backend.backend.config["tokenizer_name"] == str(
        (tmp_path / "tokenizer.model").resolve()
    )
    request = backend.backend.call["request"]
    assert request["motion_plan"]["vla_prompt"] == "pick up the black bowl"
    observation = backend.backend.call["observation"]
    assert observation.raw["libero_state8"] == [0.0] * 8
    assert set(observation.camera_views) == {"agentview", "wrist"}


class _ImmediatePolicy(SkillBackend):
    def predict(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {
            "action_type": "libero_ee_delta",
            "commands": [[0.0] * 7],
            "source_observation_id": inputs["observation"]["observation_id"],
        }


class _ImmediateLiberoEnvironment(Environment):
    def __init__(self) -> None:
        self.task: dict[str, Any] = {}
        self.closed = False

    def resolve_suite(self, suite: str) -> list[dict[str, Any]]:
        assert suite == "libero_spatial"
        return [
            {
                "task_id": 0,
                "name": "pick_up_the_black_bowl",
                "instruction": "pick up the black bowl",
                "init_state_count": 50,
            }
        ]

    def get_suite_horizon(self, suite: str) -> int:
        return 220

    def metadata(self) -> dict[str, Any]:
        return {"benchmark": "LIBERO"}

    def reset(self, task: Any) -> dict[str, Any]:
        self.task = task
        return {
            "observation_id": "episode:0",
            "available_skills": [task["name"]],
            "annotation.human.task_description": task["instruction"],
        }

    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        return {
            "observation": {
                "observation_id": "episode:1",
                "available_skills": [self.task["name"]],
                "annotation.human.task_description": self.task["instruction"],
            },
            "task_success": True,
            "task_progress": 1.0,
            "last_action_success": True,
            "done": True,
            "executed_steps": 1,
            "environment_steps": 1,
            "env_feedback": "task_success",
        }

    def close(self) -> None:
        self.closed = True


def test_libero_evaluator_records_official_success(tmp_path: Path) -> None:
    environment = _ImmediateLiberoEnvironment()
    agent = DefaultAgent(
        planner=TaskSkillPlanner(),
        verifier=SubtaskVerifier(),
        memory=InMemoryMemory(),
        skill_backend=_ImmediatePolicy(),
    )
    evaluator = LiberoEvaluator(
        environment=environment,  # type: ignore[arg-type]
        suite="libero_spatial",
        output_dir=tmp_path / "evaluation",
        task_ids=[0],
        episodes_per_task=1,
        episode_indices=[3],
    )
    result = evaluator.run(
        agent,
        SkillExecutionPipeline(
            action_execution_mode="receding_horizon", execute_steps=5
        ),
        SyncRuntime(max_steps=3, output_dir=tmp_path / "traces"),
    )

    assert result["summary"]["success_rate"] == 1.0
    assert result["summary"]["per_task"]["0"]["successes"] == 1
    assert result["episodes"][0]["success_source"] == "LIBERO env.check_success()"
    assert result["resolved"]["episode_index_semantics"] == (
        "official_fixed_init_state_index"
    )
    assert environment.task["episode_index"] == 3
    assert environment.closed is True
    assert (tmp_path / "evaluation" / "summary.json").is_file()


def test_libero_configs_instantiate_without_loading_model() -> None:
    root = Path(__file__).resolve().parents[2]
    agent = build_agent(load_yaml(root / "configs/agents/libero_pi05_atomic.yaml"))
    pipeline, runtime, environment = build_run_components(
        load_yaml(root / "configs/runs/libero_spatial_pi05_smoke.yaml")
    )
    try:
        assert isinstance(agent.skill_backend, LiberoPi05PolicyBackend)
        assert isinstance(environment, LiberoEnvironment)
        assert pipeline.action_execution_mode == "receding_horizon"
        assert pipeline.execute_steps == 5
        assert runtime.max_steps == 50
    finally:
        agent.close()
        if environment is not None:
            environment.close()


def test_libero_environment_rejects_unknown_task_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_clawvla(monkeypatch)
    environment = LiberoEnvironment(tmp_path / "claw.json", tmp_path)
    monkeypatch.setattr(
        environment,
        "resolve_suite",
        lambda suite: [
            {
                "task_id": 0,
                "name": "task",
                "instruction": "do task",
                "init_state_count": 50,
            }
        ],
    )

    with pytest.raises(EnvironmentError, match="outside suite"):
        environment.reset({"suite": "libero_spatial", "task_id": 4, "episode_index": 0})
