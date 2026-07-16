import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from omniroboagent.agent_core import InMemoryMemory, TieredMemory


def event(
    step: int,
    image: Any,
    *,
    status: str = "in_progress",
    event_type: str | None = None,
) -> dict[str, Any]:
    return {
        "event_type": event_type
        or (
            "subtask_completed"
            if status == "completed"
            else "subtask_failed"
            if status == "failed"
            else "transition"
        ),
        "execution_id": "execution-1",
        "attempt_id": "attempt-1",
        "skill": "PickPlace",
        "subtask": "place mug on tray",
        "planner_output": {"expected_outcome": "the mug is on the tray"},
        "environment_result": {
            "observation": {"camera": image},
            "artifact_refs": [f"frame-{step}.png"],
        },
        "verification": {"confidence": 0.8},
        "next_status": status,
        "transition_reason": status,
        "verifier_evidence": [f"evidence-{step}"],
        "recovery_action": None,
    }


def state(step: int, session_id: str = "session") -> dict[str, Any]:
    return {"session_id": session_id, "step": step}


def test_tiered_memory_bounds_visual_working_frames() -> None:
    memory = TieredMemory(
        visual_window_size=2,
        recent_event_limit=2,
        camera_keys=["camera"],
    )
    memory.reset("session")

    for step in range(3):
        memory.update(state(step), event(step, f"image-{step}"))

    recalled = memory.recall({})

    assert [item["step"] for item in recalled["working_frames"]] == [1, 2]
    assert recalled["working_frames"][1]["cameras"]["camera"] == "image-2"
    assert [item["step"] for item in recalled["recent_events"]] == [1, 2]
    assert recalled["key_events"] == []


def test_tiered_memory_reset_keeps_long_term_events() -> None:
    memory = TieredMemory(camera_keys=["camera"])
    memory.reset("first")
    memory.update(state(0, "first"), event(0, "image", status="completed"))

    memory.reset("second")
    recalled = memory.recall({"session_id": "second"})
    global_recall = memory.recall({"scope": "global"})

    assert recalled["working_frames"] == []
    assert recalled["summary"] == ""
    assert recalled["recent_events"] == []
    assert recalled["key_events"] == []
    assert len(global_recall["key_events"]) == 1
    assert global_recall["key_events"][0]["session_id"] == "first"


def test_tiered_memory_persists_summary_only_event_records(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    memory = TieredMemory(camera_keys=["camera"], event_path=path)
    memory.reset("session")
    memory.update(state(0), event(0, {"raw": "image"}, status="completed"))

    record = json.loads(path.read_text(encoding="utf-8"))

    assert record["status"] == "completed"
    assert record["event_type"] == "subtask_completed"
    assert record["artifact_refs"] == ["frame-0.png"]
    assert "environment_result" not in record
    assert "observation" not in record
    assert "raw" not in json.dumps(record)


def test_tiered_memory_event_path_keeps_non_key_transitions(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    memory = TieredMemory(camera_keys=["camera"], event_path=path)
    memory.reset("session")

    memory.update(state(0), event(0, "image"))

    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["event_type"] == "transition"
    assert memory.recall({"session_id": "session"})["key_events"] == []


def test_tiered_memory_bounds_deterministic_summary() -> None:
    memory = TieredMemory(summary_max_chars=80, camera_keys=["camera"])
    memory.reset("session")

    for step in range(5):
        memory.update(state(step), event(step, "image", status="completed"))

    summary = memory.recall({})["summary"]

    assert len(summary) <= 80
    assert "step=4" in summary


def test_tiered_memory_saves_key_event_frames_and_jsonl(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts"
    memory = TieredMemory(camera_keys=["camera"], save_key_event_artifacts=True)
    memory.reset("session")

    memory.update(
        {**state(3), "artifact_dir": str(artifact_dir)},
        event(3, Image.new("RGB", (4, 4), "red"), status="completed"),
    )

    recalled = memory.recall({"session_id": "session"})
    record = recalled["key_events"][0]
    saved_refs = [Path(ref) for ref in record["artifact_refs"] if ref != "frame-3.png"]
    persisted = json.loads(
        (artifact_dir / "key_events" / "events.jsonl").read_text(encoding="utf-8")
    )

    assert record["event_type"] == "subtask_completed"
    assert record["expected_outcome"] == "the mug is on the tray"
    assert "place mug on tray" in record["text_summary"]
    assert len(saved_refs) == 1
    assert saved_refs[0].is_file()
    assert Image.open(saved_refs[0]).size == (4, 4)
    assert persisted["artifact_refs"] == record["artifact_refs"]
    assert "raw" not in json.dumps(persisted)


def test_tiered_memory_does_not_save_non_key_event_frames(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "artifacts"
    memory = TieredMemory(camera_keys=["camera"], save_key_event_artifacts=True)
    memory.reset("session")

    memory.update(
        {**state(0), "artifact_dir": str(artifact_dir)},
        event(0, Image.new("RGB", (2, 2))),
    )

    assert memory.recall({"session_id": "session"})["key_events"] == []
    assert not artifact_dir.exists()


def test_tiered_memory_bounds_recalled_key_events() -> None:
    memory = TieredMemory(key_event_limit=2, camera_keys=["camera"])
    memory.reset("session")

    for step in range(3):
        memory.update(state(step), event(step, "image", status="completed"))

    assert [
        item["step"] for item in memory.recall({"session_id": "session"})["key_events"]
    ] == [1, 2]


def test_tiered_memory_requires_artifact_dir_when_enabled() -> None:
    memory = TieredMemory(camera_keys=["camera"], save_key_event_artifacts=True)
    memory.reset("session")

    with pytest.raises(ValueError, match="artifact_dir"):
        memory.update(state(0), event(0, "image", status="completed"))


def test_in_memory_memory_reset_and_recall_are_compatible() -> None:
    memory = InMemoryMemory()
    memory.update({}, {"event": 1})

    assert memory.recall({})["recent_events"] == [{"event": 1}]
    assert memory.recall({})["key_events"] == []

    memory.reset("session")

    assert memory.recall({})["recent_events"] == []
