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
    expected_outcome: str = "the mug is on the tray",
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
            "expected_outcome": expected_outcome,
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


def succeed(
    memory: ReflectiveMemory,
    step: int,
    *,
    session_id: str = "session",
    **kwargs: Any,
) -> None:
    memory.update(
        state(step, session_id), event(event_type="subtask_completed", **kwargs)
    )


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
        "object_state",
        "procedures",
    }
    assert recalled["lessons"] == []
    assert recalled["object_state"] == []
    assert recalled["procedures"] == []


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


def test_reflective_memory_records_confirmed_object_state() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], track_object_state=True)
    memory.reset("session")

    succeed(memory, 4)

    entries = memory.recall({"phase": "plan"})["object_state"]

    assert [entry["object"] for entry in entries] == ["mug", "tray"]
    assert entries[0]["state"] == "the mug is on the tray"
    assert entries[0]["confirmed_step"] == 4
    assert entries[0]["slot"] == "object"
    assert entries[1]["slot"] == "target"
    assert entries[0]["revision"] == 1
    assert entries[0]["superseded_step"] is None
    assert "confirmed_step=4" in entries[0]["text"]


def test_reflective_memory_is_not_tracking_object_state_by_default() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"])
    memory.reset("session")

    succeed(memory, 0)

    assert memory.object_states == {}
    assert memory.recall({"phase": "plan"})["object_state"] == []


def test_reflective_memory_supersedes_stale_object_state() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], track_object_state=True)
    memory.reset("session")

    succeed(memory, 2)
    succeed(
        memory,
        7,
        grounded_arguments={"object": "mug"},
        expected_outcome="the mug is in the sink",
    )

    entry = memory.object_states["mug"]

    assert entry["state"] == "the mug is in the sink"
    assert entry["confirmed_step"] == 7
    assert entry["superseded_step"] == 2
    assert entry["revision"] == 2
    assert len(memory.object_states) == 2


def test_reflective_memory_marks_objects_disturbed_by_a_later_failure() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], track_object_state=True)
    memory.reset("session")

    succeed(memory, 1)
    fail(memory, 6, grounded_arguments={"object": "mug"})

    entry = memory.object_states["mug"]

    assert entry["confirmed_step"] == 1
    assert entry["state"] == "the mug is on the tray"
    assert entry["disturbed_step"] == 6
    assert "disturbed_step=6" in entry["text"]
    assert memory.object_states["tray"]["disturbed_step"] is None


def test_reflective_memory_clears_object_state_on_reset_but_keeps_lessons() -> None:
    memory = ReflectiveMemory(
        camera_keys=["camera"],
        track_object_state=True,
        lesson_min_support=1,
    )
    memory.reset("first")
    succeed(memory, 0, session_id="first")
    fail(memory, 1, session_id="first")

    assert memory.object_states != {}

    memory.reset("second")

    assert memory.object_states == {}
    assert [lesson["lesson_id"] for lesson in memory.lessons] == ["lesson:1"]


def test_reflective_memory_suppresses_object_state_during_verification() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], track_object_state=True)
    memory.reset("session")

    succeed(memory, 0)

    assert memory.recall({"phase": "plan"})["object_state"] != []
    assert memory.recall({"phase": "verify"})["object_state"] == []


def test_reflective_memory_bounds_the_object_state_ledger() -> None:
    memory = ReflectiveMemory(
        camera_keys=["camera"],
        track_object_state=True,
        object_state_limit=2,
    )
    memory.reset("session")

    for step, name in enumerate(("kettle", "bowl", "pan")):
        succeed(
            memory,
            step,
            grounded_arguments={"object": name},
            expected_outcome=f"the {name} is on the counter",
        )

    assert list(memory.object_states) == ["bowl", "pan"]


def test_reflective_memory_ignores_object_state_without_an_outcome() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], track_object_state=True)
    memory.reset("session")

    memory.update(
        state(0),
        {
            **event(event_type="subtask_completed", expected_outcome=""),
            "subtask": "",
        },
    )

    assert memory.object_states == {}


def execution(
    skill: str,
    subtask: str,
    grounded_arguments: dict[str, Any],
) -> dict[str, Any]:
    return {
        "skill": skill,
        "subtask": subtask,
        "grounded_arguments": grounded_arguments,
    }


def finish(
    memory: ReflectiveMemory,
    step: int,
    *,
    task: Any = "put the mug on the tray",
    completed: list[dict[str, Any]] | None = None,
    session_id: str = "session",
) -> None:
    payload = state(step, session_id)
    payload["task"] = task
    payload["completed_executions"] = (
        [
            execution("OpenDoor", "open the cabinet", {"object": "cabinet"}),
            execution(
                "PickPlace",
                "place the mug on the tray",
                {"object": "mug", "target": "tray", "x": 0.3},
            ),
        ]
        if completed is None
        else completed
    )
    memory.update(payload, event(event_type="task_success"))


def test_reflective_memory_induces_a_procedure_from_a_task_success() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], track_procedures=True)
    memory.reset("session")

    finish(memory, 9)

    procedures = memory.recall({"phase": "plan", "task": "put the mug on the tray"})[
        "procedures"
    ]

    assert len(procedures) == 1
    procedure = procedures[0]
    assert procedure["procedure_id"] == "procedure:1"
    assert [step["signature"] for step in procedure["steps"]] == [
        "OpenDoor|object=cabinet",
        "PickPlace|object=mug,target=tray",
    ]
    assert procedure["support_count"] == 1
    assert procedure["task"] == "put the mug on the tray"
    assert "1) OpenDoor|object=cabinet -> 2) PickPlace" in procedure["text"]


def test_reflective_memory_is_not_tracking_procedures_by_default() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"])
    memory.reset("session")

    finish(memory, 0)

    assert memory.procedures == []
    recalled = memory.recall({"phase": "plan", "task": "put the mug on the tray"})
    assert recalled["procedures"] == []


def test_reflective_memory_counts_repeated_successes_of_the_same_procedure() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], track_procedures=True)
    memory.reset("first")
    finish(memory, 3, session_id="first")

    memory.reset("second")
    finish(memory, 8, session_id="second")

    assert len(memory.procedures) == 1
    procedure = memory.procedures[0]
    assert procedure["support_count"] == 2
    assert procedure["session_ids"] == ["first", "second"]
    assert procedure["first_seen_step"] == 3
    assert procedure["last_seen_step"] == 8


def test_reflective_memory_keeps_alternative_procedures_for_one_task() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], track_procedures=True)
    memory.reset("session")

    finish(memory, 1)
    finish(
        memory,
        5,
        completed=[
            execution("PickPlace", "place the mug on the tray", {"object": "mug"}),
        ],
    )

    assert [procedure["support_count"] for procedure in memory.procedures] == [1, 1]
    assert len(memory.procedures) == 2


def test_reflective_memory_keeps_procedures_but_clears_object_state_on_reset() -> None:
    memory = ReflectiveMemory(
        camera_keys=["camera"],
        track_procedures=True,
        track_object_state=True,
    )
    memory.reset("first")
    succeed(memory, 0, session_id="first")
    finish(memory, 1, session_id="first")

    memory.reset("second")

    assert memory.object_states == {}
    assert [procedure["procedure_id"] for procedure in memory.procedures] == [
        "procedure:1"
    ]


def test_reflective_memory_suppresses_procedures_during_verification() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], track_procedures=True)
    memory.reset("session")

    finish(memory, 0)

    query = {"task": "put the mug on the tray"}
    assert memory.recall({**query, "phase": "plan"})["procedures"] != []
    assert memory.recall({**query, "phase": "verify"})["procedures"] == []


def test_reflective_memory_skips_procedures_for_an_unrelated_task() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], track_procedures=True)
    memory.reset("session")

    finish(memory, 0)

    recalled = memory.recall({"phase": "plan", "task": "turn on the stove"})

    assert recalled["procedures"] == []


def test_reflective_memory_reads_the_task_instruction_field() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], track_procedures=True)
    memory.reset("session")

    finish(memory, 0, task={"instruction": "Put The Mug  on the Tray"})

    assert memory.procedures[0]["task"] == "put the mug on the tray"


def test_reflective_memory_ignores_task_success_without_completed_executions() -> None:
    memory = ReflectiveMemory(camera_keys=["camera"], track_procedures=True)
    memory.reset("session")

    finish(memory, 0, completed=[])
    finish(memory, 1, task="")

    assert memory.procedures == []


def test_reflective_memory_bounds_the_procedure_store() -> None:
    memory = ReflectiveMemory(
        camera_keys=["camera"],
        track_procedures=True,
        procedure_limit=2,
    )
    memory.reset("session")

    finish(memory, 0)
    finish(memory, 1)
    for index, skill in enumerate(("MoveTo", "OpenDoor"), start=2):
        finish(
            memory,
            index,
            completed=[execution(skill, "do it", {"object": "mug"})],
        )

    assert [procedure["support_count"] for procedure in memory.procedures] == [2, 1]
    assert len(memory.procedures) == 2


def test_reflective_memory_rejects_invalid_lesson_configuration() -> None:
    with pytest.raises(ValueError):
        ReflectiveMemory(lesson_recall_limit=0)
    with pytest.raises(ValueError):
        ReflectiveMemory(lesson_min_support=0)
    with pytest.raises(ValueError):
        ReflectiveMemory(lesson_recall_limit=4, lesson_limit=2)
    with pytest.raises(ValueError, match="lesson_reload"):
        ReflectiveMemory(lesson_reload=True)
    with pytest.raises(ValueError, match="object_state_limit"):
        ReflectiveMemory(object_state_limit=0)
    with pytest.raises(ValueError, match="procedure_recall_limit"):
        ReflectiveMemory(procedure_recall_limit=0)
    with pytest.raises(ValueError, match="procedure_min_support"):
        ReflectiveMemory(procedure_min_support=0)
    with pytest.raises(ValueError, match="procedure_limit"):
        ReflectiveMemory(procedure_recall_limit=4, procedure_limit=2)
