import importlib.util
import io
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from omniroboagent.agent_core import SubtaskPlanPlanner, SubtaskVerifier
from omniroboagent.backends.llm.base import LLMBackend


class FullPlanScheduleBackend(LLMBackend):
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def complete(self, inputs: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(inputs)
        role = inputs["response_format"]["json_schema"]["name"]
        if role == "subtask_plan":
            answer = {
                "subtasks": [
                    {
                        "subtask_index": 0,
                        "skill": "press",
                        "instruction": "Press the left button.",
                        "success_condition": "The left button is pressed.",
                        "chunk_budget": 2,
                    },
                    {
                        "subtask_index": 1,
                        "skill": "press",
                        "instruction": "Press the confirm button.",
                        "success_condition": "The confirm button is pressed.",
                        "chunk_budget": 1,
                    },
                ]
            }
        elif role == "subtask_selection":
            prompt = json.loads(inputs["messages"][1]["content"][0]["text"])
            answer = prompt["execution_plan"][
                prompt["progress"]["current_subtask_index"]
            ]
        else:
            prompt = json.loads(inputs["messages"][1]["content"][0]["text"])
            progress = prompt["progress"]
            done = progress["current_chunk"] >= progress["current_chunk_budget"]
            answer = {
                "execution_status": "completed" if done else "in_progress",
                "reason": "explicit plan progress",
                "confidence": 1.0,
                "evidence": [
                    f"current_chunk={progress['current_chunk']}",
                    f"chunk_budget={progress['current_chunk_budget']}",
                ],
            }
        return {"choices": [{"message": {"content": json.dumps(answer)}}]}


def test_full_plan_is_generated_once_and_progress_is_explicit() -> None:
    model = FullPlanScheduleBackend()
    planner = SubtaskPlanPlanner(backend=model, scheduled_chunks=True)
    inputs = {
        "task": {"instruction": "Press left and confirm."},
        "step": 0,
        "completed_executions": [],
        "failed_executions": [],
        "available_skills": ["press"],
        "observation": {
            "annotation.human.task_description": "Press left and confirm.",
            "head_rgb": "initial.jpg",
        },
    }
    first = planner.plan(inputs)
    assert first["subtask"] == "Press the left button."
    assert first["plan"][0]["chunk_budget"] == 2
    assert model.calls[0]["response_format"]["json_schema"]["name"] == "subtask_plan"
    assert (
        model.calls[1]["response_format"]["json_schema"]["name"] == "subtask_selection"
    )

    verifier = SubtaskVerifier(backend=model, planned_chunk_schedule=True)
    for count, expected in [(1, "in_progress"), (2, "completed")]:
        result = verifier.verify(
            {
                "task": {
                    "instruction": "Press left and confirm.",
                    "episode_index": 12,
                    "seed": 42,
                },
                "state": {"completed_executions": []},
                "active_execution": {
                    "skill": first["skill"],
                    "subtask": first["subtask"],
                    "planner_output": first,
                    "chunk_count": count,
                },
                "environment_result": {
                    "last_action_success": True,
                    "task_success": False,
                },
            }
        )
        assert result["execution_status"] == expected
    prompt = json.loads(model.calls[-1]["messages"][1]["content"][0]["text"])
    assert prompt["execution_plan"] == first["plan"]
    assert prompt["progress"]["current_chunk"] == 2
    assert "episode_index" not in prompt["task"]
    assert "seed" not in prompt["task"]

    second = planner.plan({**inputs, "step": 3, "completed_executions": [first]})
    assert second["subtask"] == "Press the confirm button."
    assert (
        sum(
            call["response_format"]["json_schema"]["name"] == "subtask_plan"
            for call in model.calls
        )
        == 1
    )


def test_max_schedule_catalog_separates_skill_sequence_variants() -> None:
    module = _load_builder()

    def payload(episode: int, skills: list[str], lengths: list[int]) -> dict[str, Any]:
        start = 0
        segments = []
        for skill, length in zip(skills, lengths, strict=True):
            segments.append(
                {
                    "skill": skill,
                    "frame_start": start,
                    "frame_end_exclusive": start + length,
                }
            )
            start += length
        return {
            "task_name": "test_task",
            "episode_index": episode,
            "segments": segments,
        }

    records = [
        (Path("ep0.json"), payload(0, ["pick", "place"], [32, 33])),
        (Path("ep1.json"), payload(1, ["pick", "place"], [65, 97])),
        (Path("ep2.json"), payload(2, ["pick", "handover", "place"], [32, 64, 32])),
    ]
    catalog = module.build_max_schedule_catalog(records)
    assert len(catalog) == 2
    assert module.resolve_max_schedule(records[0][1], catalog)[1] == [3, 4]
    assert module.resolve_max_schedule(records[2][1], catalog)[1] == [1, 2, 1]


def _load_builder() -> Any:
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location(
        "schedule_builder", root / "scripts/build_fixed_schedule_sft.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_replay_preserves_plan_and_progress_context(tmp_path: Path) -> None:
    h5py = pytest.importorskip("h5py")
    np = pytest.importorskip("numpy")
    module = _load_builder()
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (250, 0, 0)).save(buffer, format="JPEG")
    hdf5 = tmp_path / "episode.hdf5"
    ranges = [(0, 33), (33, 40), (40, 44)]
    skills = ["pick and place", "press", "pick and place"]
    with h5py.File(hdf5, "w") as handle:
        for camera in module.CAMERAS.values():
            handle.create_dataset(
                f"observation/{camera}/rgb", data=np.array([buffer.getvalue()] * 44)
            )
    segments = []
    for (start, end), skill in zip(ranges, skills, strict=True):
        segments.append(
            {
                "frame_start": start,
                "frame_end_exclusive": end,
                "skill": skill,
                "subtask_instruction": "Move the object.",
                "completion_criteria": "Object at destination.",
                "omni_prompt": (
                    f"Task: Test.\nSkill: {skill}\nSubtask: Move the object."
                ),
            }
        )
    teacher, episode = module.replay_episode(
        {
            "task_name": "test",
            "episode_index": 0,
            "seed": 1,
            "instruction": "Test.",
            "segments": segments,
            "hdf5_path": str(hdf5),
            "frame_count": 44,
        },
        tmp_path / "images",
        tmp_path / "traces",
        {"pick_place": skills[0], "press": skills[1]},
    )
    assert episode["task"]["chunk_budgets"] == [2, 1, 1]
    assert episode["runtime_result"]["termination_reason"] == "plan_exhausted"
    assert [row["kind"] for row in teacher.rows] == [
        "plan",
        "planner",
        "verifier",
        "verifier",
        "planner",
        "verifier",
        "planner",
        "verifier",
    ]
    plan = teacher.rows[0]["answer"]["subtasks"]
    assert [item["chunk_budget"] for item in plan] == [2, 1, 1]
    final_prompt = json.loads(
        teacher.rows[-1]["request"]["messages"][1]["content"][0]["text"]
    )
    assert final_prompt["execution_plan"] == plan
    assert final_prompt["progress"]["completed_subtask_count"] == 2
    assert final_prompt["progress"]["current_subtask_index"] == 2
    assert final_prompt["progress"]["current_chunk"] == 1
    assert all(item["after_frame"] < 44 for item in episode["executions"])
