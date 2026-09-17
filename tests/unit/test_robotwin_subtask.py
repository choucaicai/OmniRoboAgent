import json
import socketserver
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from omniroboagent.agent_core.planners.subtask_plan import SubtaskPlanPlanner
from omniroboagent.backends.llm.base import LLMBackend
from omniroboagent.backends.skills.pi05_worker import Pi05WorkerBackend
from omniroboagent.config import build_agent, build_run_components, load_yaml
from omniroboagent.environments.benchmarks.robotwin import RoboTwinEnvironment
from omniroboagent.exceptions import BackendError, PlannerOutputError


@pytest.fixture
def plan_path(tmp_path: Path) -> Path:
    path = tmp_path / "plan.json"
    path.write_text(
        json.dumps(
            {
                "subtasks": [
                    {
                        "instruction": "Pick up the cup.",
                        "success_condition": "The cup is held.",
                    },
                    {
                        "instruction": "Place the cup on the plate.",
                        "success_condition": "The cup rests on the plate.",
                    },
                ]
            }
        )
    )
    return path


def test_plan_keeps_pending_subtask_until_verified(plan_path: Path) -> None:
    planner = SubtaskPlanPlanner(str(plan_path))
    inputs: dict[str, Any] = {"step": 0, "completed_executions": []}
    first = planner.plan(inputs)
    assert first["subtask"] == "Pick up the cup."
    assert first["grounded_arguments"] == {}
    inputs.update(step=1, failed_executions=[{"subtask": first["subtask"]}])
    assert planner.plan(inputs) == first
    inputs.update(step=2, completed_executions=[first])
    second = planner.plan(inputs)
    assert second["subtask"] == "Place the cup on the plate."
    inputs.update(step=3, completed_executions=[first, second])
    assert planner.plan(inputs) == {"plan_complete": True}
    # A second runtime episode must start from its first subtask.
    assert planner.plan({"step": 0}) == first


class RecordingModel(LLMBackend):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def complete(self, inputs: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(inputs)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "subtasks": [
                                    {
                                        "instruction": "Put the cup on the plate.",
                                        "success_condition": "The cup is on the plate.",
                                    },
                                ]
                            }
                        )
                    }
                }
            ]
        }


def test_replan_uses_current_images_history_and_completed_offset(
    plan_path: Path,
) -> None:
    model = RecordingModel()
    planner = SubtaskPlanPlanner(str(plan_path), backend=model)
    first = planner.plan({"step": 0})
    result = planner.plan(
        {
            "task": "Put the cup on the plate.",
            "step": 4,
            "completed_executions": [first],
            "failed_executions": [{"subtask": "place", "reason": "missed plate"}],
            "history": [{"step": n} for n in range(25)],
            "observation": {"head_rgb": "new.png", "grounding": {"cup": [1, 2, 3, 4]}},
        }
    )
    assert result["plan_index"] == 0
    assert result["subtask"] == "Put the cup on the plate."
    content = model.calls[0]["messages"][1]["content"]
    context = json.loads(content[0]["text"])
    assert context["completed_subtasks"] == [first]
    assert context["recent_history"] == [{"step": n} for n in range(5, 25)]
    assert context["grounding"]["cup"] == [1, 2, 3, 4]
    assert content[1]["image_url"]["url"] == "new.png"
    assert planner.plan(
        {"step": 5, "completed_executions": [first, result], "failed_executions": [{}]}
    ) == {"plan_complete": True}


@pytest.mark.parametrize(
    "payload", [{}, {"subtasks": []}, {"subtasks": [{"instruction": "Pick up"}]}]
)
def test_invalid_plan_is_rejected(tmp_path: Path, payload: Any) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(PlannerOutputError):
        SubtaskPlanPlanner(str(path)).plan({"step": 0})


def test_pi05_worker_protocol_keeps_prompt_and_observation() -> None:
    requests: list[dict[str, Any]] = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self) -> None:
            request = json.loads(self.rfile.readline())
            requests.append(request)
            result = (
                {"status": "ok"}
                if request.get("op") == "health"
                else {
                    "success": True,
                    "action_chunk": {"action_type": "qpos", "commands": [[0.0] * 14]},
                }
            )
            self.wfile.write((json.dumps(result) + "\n").encode())

    with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            backend = Pi05WorkerBackend(port=server.server_address[1])
            assert backend.healthcheck()["healthy"]
            inputs = {
                "observation": {
                    "artifact_dir": "/tmp/current",
                    "observation_id": "1:2",
                    "annotation.human.task_description": "Set the table.",
                },
                "subtask": "Pick up the cup.",
                "skill": "PickPlace",
            }
            action = backend.predict(inputs)
            assert action["source_observation_id"] == "1:2"
            assert requests[-1]["motion_plan"]["vla_prompt"] == "Pick up the cup."
            assert requests[-1]["artifact_dir"] == "/tmp/current"
            assert requests[-1]["horizon"] == 32
            assert requests[-1]["omni_context"]["task"] == "Set the table."
            assert requests[-1]["omni_context"]["subtask"] == "Pick up the cup."
            assert requests[-1]["omni_context"]["skill"] == "PickPlace"
            backend.prompt_mode = "task_skill_subtask"
            backend.predict(inputs)
            assert requests[-1]["motion_plan"]["vla_prompt"] == (
                "Task: Set the table.\nSkill: PickPlace\nSubtask: Pick up the cup."
            )
        finally:
            server.shutdown()
            thread.join(timeout=2)


def test_worker_failure_never_becomes_an_empty_action(monkeypatch: Any) -> None:
    backend = Pi05WorkerBackend()
    monkeypatch.setattr(
        backend, "_request", lambda _: {"success": False, "errors": ["oom"]}
    )
    with pytest.raises(BackendError, match="oom"):
        backend.predict(
            {
                "observation": {"artifact_dir": "/tmp/current"},
                "subtask": "Pick up the cup.",
            }
        )


@pytest.mark.parametrize(
    "commands",
    [[], [[0] * 13], [[0] * 14, [float("nan")] * 14], [[True] * 14], [["0"] * 14]],
)
def test_invalid_chunk_is_rejected_before_any_motion(commands: Any) -> None:
    env = RoboTwinEnvironment("unused.json", "/tmp/unused-omni")
    env.observation = {"observation_id": "current"}
    # No optional simulator installed or adapter created: validation runs first.
    result = env.execute(
        {
            "action_type": "qpos",
            "source_observation_id": "current",
            "commands": commands,
        }
    )
    assert result["executed_steps"] == 0
    assert result["last_action_success"] is False


def test_stale_observation_is_rejected() -> None:
    env = RoboTwinEnvironment("unused.json", "/tmp/unused-omni")
    env.observation = {"observation_id": "new"}
    result = env.execute(
        {"action_type": "qpos", "source_observation_id": "old", "commands": [[0] * 14]}
    )
    assert result["executed_steps"] == 0
    assert "stale" in result["env_feedback"]


def test_environment_uses_post_action_images_and_authoritative_success(
    monkeypatch: Any,
) -> None:
    schema = ModuleType("clawvla.schema")
    schema.ActionChunk = SimpleNamespace  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "clawvla", ModuleType("clawvla"))
    monkeypatch.setitem(sys.modules, "clawvla.schema", schema)
    bundle = SimpleNamespace(
        raw={"summary_ref": "/tmp/after/raw_observation_summary.json"},
        camera_views={
            name: SimpleNamespace(rgb_path=f"/tmp/after/{name}.png")
            for name in ["head_camera", "left_camera", "right_camera"]
        },
    )
    chunks = []

    def execute(chunk: Any) -> dict[str, Any]:
        chunks.append(chunk)
        return {"success": True, "status": "action_executed", "executed_steps": 1}

    env = RoboTwinEnvironment("unused.json", "/tmp/unused-omni")
    env.adapter = SimpleNamespace(
        execute_action=execute,
        last_observation=bundle,
        session=SimpleNamespace(
            task_env=SimpleNamespace(take_action_cnt=1, step_lim=100)
        ),
    )
    env.observation = {"observation_id": "current"}
    result = env.execute(
        {
            "action_type": "qpos",
            "source_observation_id": "current",
            "commands": [[0] * 14, [1] * 14],
        },
        execute_steps=1,
    )
    assert len(chunks[0].commands) == 1
    assert result["task_success"] is True
    assert result["done"] is True
    assert result["observation"]["artifact_dir"] == "/tmp/after"
    assert result["observation"]["observation_id"] != "current"


def test_example_configs_build_without_simulator_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("ROBOTWIN_CONFIG", "/tmp/robotwin.json")
    agent = build_agent(load_yaml(root / "configs/agents/robotwin_omni.yaml"))
    pipeline, runtime, env = build_run_components(
        load_yaml(root / "configs/runs/robotwin_omni.yaml")
    )
    assert isinstance(agent.planner, SubtaskPlanPlanner)
    assert agent.planner.scheduled_chunks is True
    assert agent.verifier.planned_chunk_schedule is True
    assert isinstance(agent.skill_backend, Pi05WorkerBackend)
    assert isinstance(env, RoboTwinEnvironment)
    assert pipeline.reobserve_on_uncertain is True
    agent.close()
