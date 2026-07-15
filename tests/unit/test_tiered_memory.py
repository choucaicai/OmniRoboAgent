import json
from pathlib import Path
from typing import Any

from omniroboagent.agent_core import InMemoryMemory, TieredMemory


def event(step: int, image: Any, *, status: str = "in_progress") -> dict[str, Any]:
    return {
        "execution_id": "execution-1",
        "attempt_id": "attempt-1",
        "skill": "PickPlace",
        "subtask": "place mug on tray",
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
    memory = TieredMemory(visual_window_size=2, camera_keys=["camera"])
    memory.reset("session")

    for step in range(3):
        memory.update(state(step), event(step, f"image-{step}"))

    recalled = memory.recall({})

    assert [item["step"] for item in recalled["working_frames"]] == [1, 2]
    assert recalled["working_frames"][1]["cameras"]["camera"] == "image-2"
    assert len(recalled["recent_events"]) == 3


def test_tiered_memory_reset_keeps_long_term_events() -> None:
    memory = TieredMemory(camera_keys=["camera"])
    memory.reset("first")
    memory.update(state(0, "first"), event(0, "image"))

    memory.reset("second")
    recalled = memory.recall({})

    assert recalled["working_frames"] == []
    assert recalled["summary"] == ""
    assert len(recalled["recent_events"]) == 1
    assert recalled["recent_events"][0]["session_id"] == "first"
    assert memory.recall({"session_id": "second"})["recent_events"] == []


def test_tiered_memory_persists_summary_only_event_records(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    memory = TieredMemory(camera_keys=["camera"], event_path=path)
    memory.reset("session")
    memory.update(state(0), event(0, {"raw": "image"}, status="completed"))

    record = json.loads(path.read_text(encoding="utf-8"))

    assert record["status"] == "completed"
    assert record["artifact_refs"] == ["frame-0.png"]
    assert "environment_result" not in record
    assert "observation" not in record
    assert "raw" not in json.dumps(record)


def test_tiered_memory_bounds_deterministic_summary() -> None:
    memory = TieredMemory(summary_max_chars=80, camera_keys=["camera"])
    memory.reset("session")

    for step in range(5):
        memory.update(state(step), event(step, "image"))

    summary = memory.recall({})["summary"]

    assert len(summary) <= 80
    assert "step=4" in summary


def test_in_memory_memory_reset_and_recall_are_compatible() -> None:
    memory = InMemoryMemory()
    memory.update({}, {"event": 1})

    assert memory.recall({})["recent_events"] == [{"event": 1}]

    memory.reset("session")

    assert memory.recall({})["recent_events"] == []
