from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from omniroboagent.agent_core import (
    DefaultAgent,
    EnvironmentVerifier,
    InMemoryMemory,
    TaskSkillPlanner,
)
from omniroboagent.backends.skills import SkillBackend
from omniroboagent.environments import Environment
from omniroboagent.environments.benchmarks.robocasa import RoboCasaEnvironment
from omniroboagent.evals.benchmarks.robocasa import RoboCasa365Evaluator
from omniroboagent.exceptions import ConfigError, EnvironmentError
from omniroboagent.pipelines import SkillExecutionPipeline
from omniroboagent.runtimes import SyncRuntime


def action_chunk(horizon: int = 4) -> dict[str, np.ndarray]:
    return {
        "action.end_effector_position": np.zeros((horizon, 3), dtype=np.float32),
        "action.end_effector_rotation": np.zeros((horizon, 3), dtype=np.float32),
        "action.gripper_close": np.zeros((horizon, 1), dtype=np.float32),
        "action.base_motion": np.zeros((horizon, 4), dtype=np.float32),
        "action.control_mode": np.zeros((horizon, 1), dtype=np.float32),
    }


class FakeGymEnvironment:
    def __init__(self) -> None:
        self.steps = 0
        self.actions: list[dict[str, np.ndarray]] = []
        self.closed = False

    def reset(self, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
        return self._observation(), {"seed": seed}

    def step(
        self, action: dict[str, np.ndarray]
    ) -> tuple[dict[str, Any], float, bool, bool, dict[str, Any]]:
        self.actions.append(action)
        self.steps += 1
        success = self.steps == 2
        return self._observation(), float(success), False, False, {"success": success}

    def close(self) -> None:
        self.closed = True

    @staticmethod
    def _observation() -> dict[str, Any]:
        return {
            "video.robot0_agentview_left": np.zeros((256, 256, 3), dtype=np.uint8),
            "state.gripper_qpos": np.zeros(2, dtype=np.float32),
            "annotation.human.task_description": "close the blender lid",
        }


def test_robocasa_environment_executes_chunk_until_success(tmp_path: Path) -> None:
    fake = FakeGymEnvironment()
    environment = RoboCasaEnvironment(
        robocasa_root=tmp_path,
        environment_factory=lambda **kwargs: fake,
    )
    environment._robocasa = SimpleNamespace(__file__=tmp_path / "robocasa.py")

    observation = environment.reset(
        {
            "name": "CloseBlenderLid",
            "split": "pretrain",
            "seed": 0,
            "episode_index": 0,
            "horizon": 10,
        }
    )
    result = environment.execute(action_chunk())

    assert observation["available_skills"] == ["CloseBlenderLid"]
    assert result["task_success"] is True
    assert result["executed_steps"] == 2
    assert len(fake.actions) == 2
    assert fake.actions[0]["action.base_motion"].shape == (4,)


def test_robocasa_environment_rejects_out_of_range_action(tmp_path: Path) -> None:
    fake = FakeGymEnvironment()
    environment = RoboCasaEnvironment(
        robocasa_root=tmp_path,
        environment_factory=lambda **kwargs: fake,
    )
    environment._robocasa = SimpleNamespace(__file__=tmp_path / "robocasa.py")
    environment.reset(
        {
            "name": "CloseBlenderLid",
            "split": "pretrain",
            "seed": 0,
            "episode_index": 0,
            "horizon": 10,
        }
    )
    action = action_chunk()
    action["action.base_motion"][0, 0] = 1.1

    with pytest.raises(EnvironmentError, match="exceeds controller range tolerance"):
        environment.execute(action)


def test_robocasa_environment_exposes_configured_skill_catalog(
    tmp_path: Path,
) -> None:
    fake = FakeGymEnvironment()
    environment = RoboCasaEnvironment(
        robocasa_root=tmp_path,
        available_skills=["Close_Lid", "Pick_Place"],
        environment_factory=lambda **kwargs: fake,
    )
    environment._robocasa = SimpleNamespace(__file__=tmp_path / "robocasa.py")

    observation = environment.reset(
        {
            "name": "DeliverStraw",
            "split": "pretrain",
            "seed": 0,
            "episode_index": 0,
            "horizon": 10,
        }
    )

    assert observation["available_skills"] == ["Close_Lid", "Pick_Place"]
    assert observation["task_name"] == "DeliverStraw"


def test_robocasa_environment_rejects_invalid_skill_catalog(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="non-empty list of unique strings"):
        RoboCasaEnvironment(
            robocasa_root=tmp_path,
            available_skills=["Pick_Place", "Pick_Place"],
        )


class FakePolicyBackend(SkillBackend):
    def predict(self, inputs: dict[str, Any]) -> Any:
        return action_chunk(1)


class FakeEvaluationEnvironment(Environment):
    def __init__(self) -> None:
        self.task: dict[str, Any] | None = None
        self.closed = False

    def resolve_task_set(self, task_set: str) -> list[str]:
        assert task_set == "atomic_seen"
        return ["CloseBlenderLid", "OpenBlenderLid"]

    def get_task_horizon(self, task_name: str) -> int:
        return 4

    def metadata(self) -> dict[str, Any]:
        return {"commit": "test"}

    def reset(self, task: Any) -> dict[str, Any]:
        self.task = task
        return {
            "available_skills": [task["name"]],
            "annotation.human.task_description": "close the blender lid",
        }

    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        return {
            "observation": {
                "available_skills": [self.task["name"]],
                "annotation.human.task_description": "done",
            },
            "task_success": True,
            "task_progress": 1.0,
            "last_action_success": True,
            "done": True,
            "executed_steps": 1,
        }

    def close(self) -> None:
        self.closed = True


def test_robocasa_evaluator_runs_one_resolved_task(tmp_path: Path) -> None:
    environment = FakeEvaluationEnvironment()
    agent = DefaultAgent(
        planner=TaskSkillPlanner(),
        verifier=EnvironmentVerifier(),
        memory=InMemoryMemory(),
        skill_backend=FakePolicyBackend(),
    )
    evaluator = RoboCasa365Evaluator(
        environment=environment,
        task_set="atomic_seen",
        split="pretrain",
        output_dir=tmp_path / "evaluation",
        max_tasks=1,
        episodes_per_task=1,
        episode_indices=[0],
        seed=7,
    )

    result = evaluator.run(
        agent,
        SkillExecutionPipeline(),
        SyncRuntime(output_dir=tmp_path / "traces"),
    )

    assert result["summary"]["episodes"] == 1
    assert result["summary"]["success_rate"] == 1.0
    assert result["summary"]["macro_average_success_rate"] == 1.0
    assert result["summary"]["action_chunks"] == 1
    assert result["summary"]["environment_steps"] == 1
    assert result["episodes"][0]["task_name"] == "CloseBlenderLid"
    assert result["episodes"][0]["seed"] == 7
    assert (tmp_path / "evaluation" / "resolved_config.json").exists()
    assert result["resolved"]["task_set_size"] == 2
    assert result["resolved"]["episode_index_semantics"] == "seed_offset"
    assert result["resolved"]["omniroboagent"]["python"]
    assert environment.closed is True


def test_robocasa_evaluator_rejects_duplicate_episode_indexes(
    tmp_path: Path,
) -> None:
    with pytest.raises(ConfigError, match="unique non-negative integers"):
        RoboCasa365Evaluator(
            environment=FakeEvaluationEnvironment(),
            task_set="atomic_seen",
            split="pretrain",
            output_dir=tmp_path,
            episodes_per_task=2,
            episode_indices=[0, 0],
        )


def test_skill_pipeline_reuses_active_execution_until_verified(
    tmp_path: Path,
) -> None:
    class CountingPlanner(TaskSkillPlanner):
        def __init__(self) -> None:
            self.calls = 0

        def plan(self, inputs: dict[str, Any]) -> dict[str, Any]:
            self.calls += 1
            return super().plan(inputs)

    class ContinuingEnvironment(FakeEvaluationEnvironment):
        def execute(
            self, action: Any, execute_steps: int | None = None
        ) -> dict[str, Any]:
            return {
                "observation": {
                    "available_skills": [self.task["name"]],
                    "annotation.human.task_description": "continue",
                },
                "task_success": False,
                "task_progress": 0.0,
                "last_action_success": True,
                "done": False,
                "executed_steps": 1,
            }

    planner = CountingPlanner()
    environment = ContinuingEnvironment()
    agent = DefaultAgent(
        planner=planner,
        verifier=EnvironmentVerifier(),
        memory=InMemoryMemory(),
        skill_backend=FakePolicyBackend(),
    )
    result = SyncRuntime(max_steps=3, output_dir=tmp_path).run(
        agent,
        SkillExecutionPipeline(planner_check_interval_chunks=2),
        environment,
        {
            "name": "CloseBlenderLid",
            "split": "pretrain",
            "seed": 0,
            "episode_index": 0,
            "horizon": 4,
        },
    )

    assert result["termination_reason"] == "step_limit"
    assert result["planner_calls"] == 1
    assert result["environment_steps"] == 3
    assert planner.calls == 1


def test_skill_pipeline_forces_replan_at_chunk_budget(tmp_path: Path) -> None:
    class ContinuingEnvironment(FakeEvaluationEnvironment):
        def execute(
            self, action: Any, execute_steps: int | None = None
        ) -> dict[str, Any]:
            return {
                "observation": {
                    "available_skills": [self.task["name"]],
                    "annotation.human.task_description": "continue",
                },
                "task_success": False,
                "task_progress": 0.0,
                "last_action_success": True,
                "done": False,
                "executed_steps": 1,
            }

    agent = DefaultAgent(
        planner=TaskSkillPlanner(),
        verifier=EnvironmentVerifier(),
        memory=InMemoryMemory(),
        skill_backend=FakePolicyBackend(),
    )
    result = SyncRuntime(max_steps=5, output_dir=tmp_path).run(
        agent,
        SkillExecutionPipeline(
            planner_check_interval_chunks=1,
            max_chunks_per_skill=2,
        ),
        ContinuingEnvironment(),
        {
            "name": "CloseBlenderLid",
            "split": "pretrain",
            "seed": 0,
            "episode_index": 0,
            "horizon": 10,
        },
    )

    assert result["termination_reason"] == "step_limit"
    assert result["action_chunks"] == 5
    assert result["replans"] == 2
