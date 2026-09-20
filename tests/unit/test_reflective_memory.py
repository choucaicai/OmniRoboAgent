import json
from pathlib import Path
from typing import Any

import pytest

from omniroboagent.agent_core import ReflectiveMemory


def event(
    *,
    event_type: str,
    skill: str = "PickPlace",
    subtask: str = "place mug on tray",
    grounded_arguments: dict[str, Any] | None = None,
    reason: str = "gripper slipped off the mug",
    control_failure: str | None = None,
) -> dict[str, Any]:
    environment_result: dict[str, Any] = {"observation": {"camera": "image"}}
    if control_failure is not None:
        environment_result["control_failure"] = control_failure
    return {
        "event_type": event_type,
        "execution_id": "execution-1",
        "attempt_id": "attempt-1",
        "skill": skill,
        "subtask": subtask,
        "planner_output": {
            "expected_outcome": "the mug is on the tray",
            "grounded_arguments": (
                {"object": "mug", "target": "tray"}
                if grounded_arguments is None
                else grounded_arguments
            ),
        },
        "environment_result": environment_result,
        "verification": {"confidence": 0.8},
        "next_status": "failed",
        "transition_reason": reason,
        "verifier_evidence": ["evidence"],
        "recovery_action": None,
    }


def state(step: int, session_id: str = "session") -> dict[str, Any]:
    return {"session_id": session_id, "step": step}


def fail(
    memory: ReflectiveMemory,
    step: int,
    *,
    session_id: str = "session",
    **kwargs: Any,
) -> None:
    memory.update(state(step, session_id), event(event_type="subtask_failed", **kwargs))


def test_reflective_memory_keeps_the_stable_recall_partitions() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"])
    memory.reset("session")

    recalled = memory.recall({})

    assert set(recalled) == {
        "working_frames",
        "recent_events",
        "key_events",
        "summary",
        "lessons",
    }
    assert recalled["lessons"] == []


def test_reflective_memory_aggregates_volatile_grounding_into_one_lesson() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"])
    memory.reset("session")

    fail(
        memory,
        0,
        grounded_arguments={"object": "mug", "target": "tray", "x": 0.12, "y": 0.44},
    )
    fail(
        memory,
        1,
        grounded_arguments={"object": "Mug", "target": " tray ", "x": 0.31, "y": 0.02},
    )

    assert len(memory.lessons) == 1
    lesson = memory.lessons[0]
    assert lesson["signature"] == "PickPlace|object=mug,target=tray"
    assert lesson["support_count"] == 2
    assert lesson["failure_class"] == "grasp_failed"


def test_reflective_memory_withholds_lessons_until_support_threshold() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], lesson_min_support=2)
    memory.reset("session")

    fail(memory, 0)
    assert memory.lessons[0]["status"] == "candidate"
    assert memory.recall({"phase": "plan"})["lessons"] == []

    fail(memory, 1)
    assert memory.lessons[0]["status"] == "active"
    recalled = memory.recall({"phase": "plan"})["lessons"]
    assert [lesson["lesson_id"] for lesson in recalled] == ["lesson:1"]
    assert "failures=2" in recalled[0]["text"]


def test_reflective_memory_retires_lessons_refuted_by_later_success() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], lesson_min_support=2)
    memory.reset("session")

    fail(memory, 0)
    fail(memory, 1)
    assert memory.lessons[0]["status"] == "active"

    for step in (2, 3):
        memory.update(state(step), event(event_type="subtask_completed"))

    lesson = memory.lessons[0]
    assert lesson["refutation_count"] == 2
    assert lesson["status"] == "retired"
    assert lesson["revision"] == 4
    assert memory.recall({"phase": "plan"})["lessons"] == []


def test_reflective_memory_suppresses_lessons_during_verification() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], lesson_min_support=1)
    memory.reset("session")

    fail(memory, 0)

    assert memory.recall({"phase": "plan"})["lessons"] != []
    assert memory.recall({"phase": "verify"})["lessons"] == []


def test_reflective_memory_classifies_control_failures() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], lesson_min_support=1)
    memory.reset("session")

    fail(memory, 0, control_failure="loop", reason="repeated execution loop detected")
    fail(memory, 1, skill="OpenDoor", reason="the drawer is still closed")
    fail(memory, 2, skill="MoveTo", reason="unknown outcome")

    assert [lesson["failure_class"] for lesson in memory.lessons] == [
        "control_loop",
        "precondition_unmet",
        "unclassified",
    ]


def test_reflective_memory_ranks_lessons_by_task_overlap_and_evidence() -> None:
    memory = ReflectiveMemory(
        camera_keys=["camera"],
        lesson_min_support=1,
        lesson_recall_limit=2,
    )
    memory.reset("session")

    fail(memory, 0, skill="OpenDoor", grounded_arguments={"object": "microwave"})
    fail(memory, 1, skill="PickPlace", grounded_arguments={"object": "kettle"})
    fail(memory, 2, skill="PickPlace", grounded_arguments={"object": "kettle"})

    recalled = memory.recall({"phase": "plan", "task": "put the kettle in the sink"})
    lessons = recalled["lessons"]

    assert len(lessons) == 2
    assert "kettle" in lessons[0]["signature"]


def test_reflective_memory_reset_keeps_lessons() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], lesson_min_support=1)
    memory.reset("first")
    fail(memory, 0, session_id="first")

    memory.reset("second")

    assert memory.recall({"working_frames": []})["working_frames"] == []
    assert [lesson["lesson_id"] for lesson in memory.lessons] == ["lesson:1"]
    assert memory.lessons[0]["session_ids"] == ["first"]


def test_reflective_memory_bounds_the_lesson_store() -> None:
    memory = ReflectiveMemory(
        camera_keys=["camera"],
        lesson_min_support=1,
        lesson_limit=3,
    )
    memory.reset("session")

    for step in range(5):
        fail(memory, step, skill=f"Skill{step}")

    assert len(memory.lessons) == 3
    assert [lesson["skill"] for lesson in memory.lessons] == [
        "Skill2",
        "Skill3",
        "Skill4",
    ]


def test_reflective_memory_writes_a_serializable_lesson_audit_log(
    tmp_path: Path,
) -> None:
    lesson_path = tmp_path / "lessons" / "lessons.jsonl"
    memory = ReflectiveMemory(
        camera_keys=["camera"],
        lesson_min_support=2,
        lesson_path=lesson_path,
    )
    memory.reset("session")

    fail(memory, 0)
    fail(memory, 1)
    memory.update(state(2), event(event_type="subtask_completed"))

    records = [
        json.loads(line)
        for line in lesson_path.read_text(encoding="utf-8").splitlines()
    ]

    assert [record["operation"] for record in records] == [
        "add",
        "upvote",
        "promote",
        "refute",
        "demote",
    ]
    assert all("image" not in json.dumps(record) for record in records)
    assert records[-1]["lesson_id"] == "lesson:1"


def test_reflective_memory_ignores_events_without_a_skill() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], lesson_min_support=1)
    memory.reset("session")

    memory.update(state(0), event(event_type="task_failed"))
    memory.update(state(1), event(event_type="subtask_failed", skill=""))

    assert memory.lessons == []


def test_reflective_memory_reloads_lessons_from_a_previous_run(tmp_path: Path) -> None:
    lesson_path = tmp_path / "lessons.jsonl"
    first = ReflectiveMemory(
        camera_keys=["camera"],
        lesson_min_support=2,
        lesson_path=lesson_path,
    )
    first.reset("first")
    fail(first, 0, session_id="first")
    fail(first, 1, session_id="first")

    second = ReflectiveMemory(
        camera_keys=["camera"],
        lesson_min_support=2,
        lesson_path=lesson_path,
        lesson_reload=True,
    )
    second.reset("second")

    carried = second.lessons[0]
    assert carried["lesson_id"] == "lesson:1"
    assert carried["carried_over"] is True
    assert carried["support_count"] == 2
    assert carried["status"] == "active"
    assert carried["session_ids"] == ["first"]
    assert second.recall({"phase": "plan"})["lessons"] != []

    fail(second, 2, skill="OpenDoor", session_id="second")

    assert [lesson["lesson_id"] for lesson in second.lessons] == [
        "lesson:1",
        "lesson:2",
    ]
    assert second.lessons[1]["carried_over"] is False


def test_reflective_memory_drops_evicted_and_malformed_lesson_records(
    tmp_path: Path,
) -> None:
    lesson_path = tmp_path / "lessons.jsonl"
    lesson_path.write_text(
        "\n".join(
            [
                "not json",
                json.dumps({"operation": "add", "lesson_id": "lesson:7"}),
                json.dumps(
                    {
                        "operation": "add",
                        "lesson_id": "lesson:8",
                        "signature": "OpenDoor|object=microwave",
                        "support_count": 3,
                        "refutation_count": 0,
                        "revision": 3,
                    }
                ),
                json.dumps(
                    {
                        "operation": "evict",
                        "lesson_id": "lesson:8",
                        "signature": "OpenDoor|object=microwave",
                        "support_count": 3,
                        "refutation_count": 0,
                        "revision": 3,
                    }
                ),
                "",
            ]
        ),
        encoding="utf-8",
    )

    memory = ReflectiveMemory(
        camera_keys=["camera"],
        lesson_path=lesson_path,
        lesson_reload=True,
    )

    assert memory.lessons == []


def test_reflective_memory_rejects_invalid_lesson_configuration() -> None:
    with pytest.raises(ValueError):
        ReflectiveMemory(lesson_recall_limit=0)
    with pytest.raises(ValueError):
        ReflectiveMemory(lesson_min_support=0)
    with pytest.raises(ValueError):
        ReflectiveMemory(lesson_recall_limit=4, lesson_limit=2)
    with pytest.raises(ValueError, match="lesson_reload"):
        ReflectiveMemory(lesson_reload=True)
