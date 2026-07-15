from pathlib import Path
from types import SimpleNamespace
from typing import Any

from omniroboagent.agent_core import (
    DefaultAgent,
    EnvironmentVerifier,
    InMemoryMemory,
    Planner,
)
from omniroboagent.backends.skills import LanguageSkillBackend
from omniroboagent.environments.benchmarks.embodiedbench import EBAlfredEnvironment
from omniroboagent.evals.benchmarks.embodiedbench import EBAlfredBenchmark
from omniroboagent.pipelines import DirectPipeline
from omniroboagent.runtimes import SyncRuntime


class FakeEBAlfEnv:
    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        self.dataset = [{"instruction": "find the mug"}]
        self.language_skill_set = ["find a Mug"]
        self._cur_invalid_actions = 0
        self._max_invalid_actions = 2
        self.env = SimpleNamespace(
            last_event=SimpleNamespace(frame="frame-before-step")
        )
        self.closed = False

    def reset(self) -> dict[str, Any]:
        return {"head_rgb": "frame-0"}

    def step(self, action: str) -> tuple[dict[str, Any], float, bool, dict[str, Any]]:
        return (
            {"head_rgb": "frame-1"},
            1.0,
            True,
            {
                "task_success": 1.0,
                "task_progress": 1.0,
                "last_action_success": 1.0,
                "env_feedback": "success",
                "env_step": 1,
                "action_description": action,
            },
        )

    def close(self) -> None:
        self.closed = True


def test_eb_alfred_adapter_maps_observation_and_metrics() -> None:
    environment = EBAlfredEnvironment(env_factory=FakeEBAlfEnv)

    observation = environment.reset(environment.tasks[0])
    result = environment.execute("find a Mug")
    underlying = environment.env
    environment.close()

    assert observation["available_skills"] == ["find a Mug"]
    assert result["task_success"] is True
    assert result["task_progress"] == 1.0
    assert result["last_action_success"] is True
    assert underlying.closed is True


def test_eb_alfred_adapter_rejects_unavailable_skill_without_step() -> None:
    environment = EBAlfredEnvironment(env_factory=FakeEBAlfEnv)
    environment.reset(environment.tasks[0])

    result = environment.execute("find a Plate")

    assert result["last_action_success"] is False
    assert result["done"] is False
    assert "Unavailable language skill" in result["env_feedback"]


class StaticPlanner(Planner):
    def plan(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"skill": "find a Mug"}


def test_eb_alfred_benchmark_writes_summary(tmp_path: Path) -> None:
    environment = EBAlfredEnvironment(env_factory=FakeEBAlfEnv)
    agent = DefaultAgent(
        planner=StaticPlanner(),
        verifier=EnvironmentVerifier(),
        memory=InMemoryMemory(),
        skill_backend=LanguageSkillBackend(),
    )
    benchmark = EBAlfredBenchmark(environment, tmp_path / "benchmark")

    result = benchmark.run(
        agent,
        DirectPipeline(),
        SyncRuntime(output_dir=tmp_path / "traces"),
    )

    assert result["summary"]["episodes"] == 1
    assert result["summary"]["success_rate"] == 1.0
    assert (tmp_path / "benchmark" / "episodes.jsonl").is_file()
    assert (tmp_path / "benchmark" / "summary.json").is_file()
