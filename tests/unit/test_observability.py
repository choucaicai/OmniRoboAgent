import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from omniroboagent.observability import LocalEpisodeRecorder


def _fake_ffmpeg(tmp_path: Path) -> Path:
    path = tmp_path / "fake_ffmpeg.py"
    path.write_text(
        """#!/usr/bin/env python3
import pathlib
import sys

sys.stdin.buffer.read()
pathlib.Path(sys.argv[-1]).write_bytes(b\"fake-mp4\")
""",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def test_local_recorder_writes_structured_trace_video_and_manifest(
    tmp_path: Path,
) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    recorder = LocalEpisodeRecorder(
        record_video=True,
        video_camera_keys=["front", "wrist"],
        video_fps=4,
        ffmpeg_path=str(_fake_ffmpeg(tmp_path)),
    )
    observation = {
        "front": Image.new("RGB", (16, 12), "red"),
        "wrist": Image.new("RGB", (8, 12), "blue"),
    }

    recorder.start(session_dir, "session", {"instruction": "pick mug"})
    recorder.record_observation(observation, step=0)
    recorder.record_step(
        1,
        {
            "planner_output": {
                "skill": "Pick_Place",
                "subtask": "pick up the mug",
                "reasoning": "the mug is visible",
                "expected_outcome": "mug is grasped",
                "raw_response": {
                    "choices": [{"message": {"content": "raw provider output"}}],
                    "_backend": {"model": "test-model", "latency_seconds": 0.1},
                },
            },
            "skill": "Pick_Place",
            "subtask": "pick up the mug",
            "verification": {
                "execution_status": "in_progress",
                "reason": "gripper is approaching",
                "confidence": 0.8,
            },
            "environment_result": {
                "task_success": False,
                "task_progress": 0.2,
                "last_action_success": True,
                "done": False,
                "executed_steps": 16,
                "environment_steps": 16,
                "env_feedback": "action_chunk_executed",
                "observation": observation,
            },
            "action": Image.new("RGB", (2, 2), "black"),
            "decision": "continue",
            "event_type": "transition",
        },
        observation,
    )
    artifacts = recorder.finish(
        {"success": False, "steps": 1, "termination_reason": "step_limit"}
    )

    trace_text = Path(artifacts["agent_trace_path"]).read_text(encoding="utf-8")
    events = [json.loads(line) for line in trace_text.splitlines()]
    assert [event["event"] for event in events] == [
        "episode_start",
        "agent_step",
        "episode_end",
    ]
    assert events[1]["planner"]["skill"] == "Pick_Place"
    assert events[1]["planner"]["backend"]["model"] == "test-model"
    assert events[1]["verification"]["execution_status"] == "in_progress"
    assert "raw provider output" not in trace_text
    assert Path(artifacts["video_path"]).read_bytes() == b"fake-mp4"
    assert artifacts["video_frames"] == 2

    manifest = json.loads(
        Path(artifacts["artifact_manifest_path"]).read_text(encoding="utf-8")
    )
    assert manifest["artifacts"]["video"] == "episode.mp4"
    assert manifest["video"] == {
        "frames": 2,
        "fps": 4,
        "camera_keys": ["front", "wrist"],
    }
    assert manifest["errors"] == []


def test_local_recorder_reports_missing_video_frames(tmp_path: Path) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    recorder = LocalEpisodeRecorder(
        record_video=True,
        video_camera_keys=["head_rgb"],
        ffmpeg_path=str(_fake_ffmpeg(tmp_path)),
    )

    recorder.start(session_dir, "session", "task")
    artifacts = recorder.finish(
        {"success": False, "steps": 0, "termination_reason": "exception"}
    )

    assert artifacts["video_path"] is None
    assert artifacts["video_frames"] == 0
    assert artifacts["observability_errors"] == [
        "no configured camera frames were found"
    ]


def test_local_recorder_resets_after_start_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = LocalEpisodeRecorder(record_video=False)
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    original_append = recorder._append

    def fail_once(event: dict[str, Any]) -> None:
        monkeypatch.setattr(recorder, "_append", original_append)
        raise OSError("trace unavailable")

    monkeypatch.setattr(recorder, "_append", fail_once)
    with pytest.raises(OSError, match="trace unavailable"):
        recorder.start(session_dir, "failed", "task")

    recorder.start(session_dir, "reused", "task")
    artifacts = recorder.finish({"success": True, "steps": 0})

    assert Path(artifacts["agent_trace_path"]).is_file()


def test_local_recorder_rejects_empty_camera_keys() -> None:
    with pytest.raises(ValueError, match="video_camera_keys"):
        LocalEpisodeRecorder(video_camera_keys=[])


def test_local_recorder_closes_video_when_terminal_trace_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_dir = tmp_path / "session"
    session_dir.mkdir()
    recorder = LocalEpisodeRecorder(
        record_video=True,
        video_camera_keys=["front"],
        ffmpeg_path=str(_fake_ffmpeg(tmp_path)),
    )
    recorder.start(session_dir, "session", "task")
    recorder.record_observation(
        {"front": Image.new("RGB", (16, 12), "red")},
        step=0,
    )
    writer = recorder.video_writer
    assert writer is not None

    def fail_append(event: dict[str, Any]) -> None:
        raise OSError("terminal trace unavailable")

    monkeypatch.setattr(recorder, "_append", fail_append)
    with pytest.raises(OSError, match="terminal trace unavailable"):
        recorder.finish({"success": False, "steps": 0})

    assert writer.process is not None
    assert writer.process.poll() == 0
    assert recorder.session_dir is None
