import json
from pathlib import Path
from typing import Any

from omniroboagent.agent_core import (
    DefaultAgent,
    InMemoryMemory,
    Planner,
    Verifier,
)
from omniroboagent.backends.skills import LanguageSkillBackend
from omniroboagent.environments import Environment
from omniroboagent.pipelines import DirectPipeline, Pipeline
from omniroboagent.runtimes import SyncRuntime


class FakePlanner(Planner):
    def __init__(self, skill: str = "find a Mug") -> None:
        self.skill = skill

    def plan(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"skill": self.skill, "received": inputs}


class FakeVerifier(Verifier):
    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        result = inputs["environment_result"]
        return {
            "task_success": result["task_success"],
            "task_progress": result["task_progress"],
            "last_action_success": result["last_action_success"],
            "environment_done": result["done"],
            "env_feedback": result.get("env_feedback", ""),
        }


class FakeEnvironment(Environment):
    def __init__(self, outcomes: list[dict[str, Any]]) -> None:
        self.outcomes = outcomes
        self.calls = 0
        self.closed = False
        self.execute_steps: list[int | None] = []

    def reset(self, task: Any) -> dict[str, Any]:
        return {"frame": 0, "available_skills": ["find a Mug"]}

    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.execute_steps.append(execute_steps)
        self.calls += 1
        return {
            "observation": {
                "frame": self.calls,
                "available_skills": ["find a Mug"],
            },
            "env_feedback": "feedback",
            **outcome,
        }

    def close(self) -> None:
        self.closed = True


def make_agent(skill: str = "find a Mug") -> DefaultAgent:
    return DefaultAgent(
        planner=FakePlanner(skill),
        verifier=FakeVerifier(),
        memory=InMemoryMemory(),
        skill_backend=LanguageSkillBackend(),
    )


def test_runtime_success_writes_trace(tmp_path: Path) -> None:
    environment = FakeEnvironment(
        [
            {
                "task_success": True,
                "task_progress": 1.0,
                "last_action_success": True,
                "done": True,
            }
        ]
    )
    runtime = SyncRuntime(output_dir=tmp_path)

    result = runtime.run(
        make_agent(), DirectPipeline(), environment, {"instruction": "find mug"}
    )

    assert result["success"] is True
    assert result["termination_reason"] == "task_success"
    assert result["steps"] == 1
    assert environment.closed is True
    trace = Path(result["trace_path"])
    assert trace.exists()
    assert [json.loads(line)["event"] for line in trace.read_text().splitlines()] == [
        "episode_start",
        "step",
        "episode_end",
    ]


def test_runtime_replans_after_failed_action(tmp_path: Path) -> None:
    environment = FakeEnvironment(
        [
            {
                "task_success": False,
                "task_progress": 0.0,
                "last_action_success": False,
                "done": False,
            },
            {
                "task_success": True,
                "task_progress": 1.0,
                "last_action_success": True,
                "done": True,
            },
        ]
    )

    result = SyncRuntime(output_dir=tmp_path).run(
        make_agent(), DirectPipeline(), environment, "find mug"
    )

    assert result["success"] is True
    assert result["steps"] == 2
    assert result["invalid_actions"] == 1
    assert result["replans"] == 1


def test_runtime_stops_at_step_limit(tmp_path: Path) -> None:
    environment = FakeEnvironment(
        [
            {
                "task_success": False,
                "task_progress": 0.5,
                "last_action_success": True,
                "done": False,
            }
        ]
    )

    result = SyncRuntime(max_steps=2, output_dir=tmp_path).run(
        make_agent(), DirectPipeline(), environment, "find mug"
    )

    assert result["termination_reason"] == "step_limit"
    assert result["steps"] == 2


def test_runtime_stops_at_retry_limit(tmp_path: Path) -> None:
    environment = FakeEnvironment(
        [
            {
                "task_success": False,
                "task_progress": 0.0,
                "last_action_success": False,
                "done": False,
            }
        ]
    )

    result = SyncRuntime(max_retries=2, output_dir=tmp_path).run(
        make_agent(), DirectPipeline(), environment, "find mug"
    )

    assert result["termination_reason"] == "retry_limit"
    assert result["steps"] == 2


def test_receding_horizon_passes_execute_steps(tmp_path: Path) -> None:
    environment = FakeEnvironment(
        [
            {
                "task_success": True,
                "task_progress": 1.0,
                "last_action_success": True,
                "done": True,
            }
        ]
    )

    SyncRuntime(output_dir=tmp_path).run(
        make_agent(),
        DirectPipeline(action_execution_mode="receding_horizon", execute_steps=4),
        environment,
        "task",
    )

    assert environment.execute_steps == [4]


def test_invalid_planner_output_is_verified_and_retried(tmp_path: Path) -> None:
    environment = FakeEnvironment([])

    result = SyncRuntime(max_retries=1, output_dir=tmp_path).run(
        make_agent("not available"), DirectPipeline(), environment, "find mug"
    )

    assert result["termination_reason"] == "retry_limit"
    assert result["invalid_actions"] == 1
    assert environment.calls == 0


class CustomTerminalPipeline(Pipeline):
    def step(
        self, agent: Any, environment: Any, state: dict[str, Any]
    ) -> dict[str, Any]:
        return {"custom_terminal": True, "success": True}

    def is_terminal(self, output: dict[str, Any], state: dict[str, Any]) -> bool:
        return bool(output["custom_terminal"])


def test_runtime_uses_pipeline_terminal_semantics(tmp_path: Path) -> None:
    environment = FakeEnvironment([])

    result = SyncRuntime(output_dir=tmp_path).run(
        make_agent(), CustomTerminalPipeline(), environment, "task"
    )

    assert result["termination_reason"] == "pipeline_terminal"
    assert result["success"] is True


class FailingEnvironment(FakeEnvironment):
    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        raise RuntimeError("environment failed")


def test_runtime_records_exception_termination(tmp_path: Path) -> None:
    result = SyncRuntime(output_dir=tmp_path).run(
        make_agent(), DirectPipeline(), FailingEnvironment([]), "task"
    )

    assert result["termination_reason"] == "exception"
    assert result["error_type"] == "RuntimeError"
    assert result["error"] == "environment failed"
