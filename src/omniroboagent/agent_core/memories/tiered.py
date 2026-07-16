import io
import json
import re
from collections import deque
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from omniroboagent.agent_core.memories.base import Memory

KEY_EVENT_TYPES = {
    "subtask_completed",
    "subtask_failed",
    "recovery_started",
    "fallback_used",
    "execution_aborted",
    "task_success",
    "task_failed",
}


class TieredMemory(Memory):
    """Bounded working memory with persistent structured key events."""

    def __init__(
        self,
        visual_window_size: int = 4,
        recent_event_limit: int = 20,
        key_event_limit: int = 20,
        summary_max_chars: int = 4096,
        camera_keys: list[str] | None = None,
        event_path: str | Path | None = None,
        save_key_event_artifacts: bool = False,
    ) -> None:
        if visual_window_size <= 0:
            raise ValueError("visual_window_size must be positive")
        if recent_event_limit <= 0:
            raise ValueError("recent_event_limit must be positive")
        if key_event_limit <= 0:
            raise ValueError("key_event_limit must be positive")
        if summary_max_chars <= 0:
            raise ValueError("summary_max_chars must be positive")
        resolved_camera_keys = (
            ["images", "head_rgb"] if camera_keys is None else camera_keys
        )
        if not isinstance(resolved_camera_keys, list) or any(
            not isinstance(key, str) or not key for key in resolved_camera_keys
        ):
            raise ValueError("camera_keys must contain non-empty strings")
        if len(set(resolved_camera_keys)) != len(resolved_camera_keys):
            raise ValueError("camera_keys must be unique")

        self.visual_window_size = visual_window_size
        self.recent_event_limit = recent_event_limit
        self.key_event_limit = key_event_limit
        self.summary_max_chars = summary_max_chars
        self.camera_keys = list(resolved_camera_keys)
        self.event_path = Path(event_path) if event_path is not None else None
        self.save_key_event_artifacts = save_key_event_artifacts
        if self.event_path is not None:
            self.event_path.parent.mkdir(parents=True, exist_ok=True)

        self.session_id: str | None = None
        self.working_frames: deque[dict[str, Any]] = deque(maxlen=visual_window_size)
        self.recent_events: deque[dict[str, Any]] = deque(maxlen=recent_event_limit)
        self.key_events: list[dict[str, Any]] = []
        self.event_memory = self.key_events
        self._summary_lines: deque[str] = deque()
        self._key_event_sequence = 0

    def reset(self, session_id: str) -> None:
        self.session_id = session_id
        self.working_frames.clear()
        self.recent_events.clear()
        self._summary_lines.clear()

    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        environment_result = event.get("environment_result")
        observation = (
            environment_result.get("observation")
            if isinstance(environment_result, Mapping)
            else state.get("observation")
        )
        if isinstance(observation, Mapping):
            cameras = {
                key: observation[key]
                for key in self.camera_keys
                if observation.get(key) is not None
            }
            if cameras:
                self.working_frames.append(
                    {
                        "session_id": state.get("session_id", self.session_id),
                        "step": state.get("step"),
                        "execution_id": event.get("execution_id"),
                        "attempt_id": event.get("attempt_id"),
                        "cameras": cameras,
                    }
                )

        verification = event.get("verification")
        confidence = (
            verification.get("confidence")
            if isinstance(verification, Mapping)
            else None
        )
        task_progress = (
            verification.get("task_progress")
            if isinstance(verification, Mapping)
            else None
        )
        evidence = event.get(
            "verifier_evidence",
            verification.get("evidence", [])
            if isinstance(verification, Mapping)
            else [],
        )
        if not isinstance(evidence, list):
            evidence = [str(evidence)]
        event_type = event.get("event_type", "transition")
        if not isinstance(event_type, str) or not event_type:
            raise ValueError("event_type must be a non-empty string")
        artifact_refs: list[str] = []
        if isinstance(environment_result, Mapping):
            value = environment_result.get("artifact_refs", [])
            if isinstance(value, list):
                artifact_refs = [str(item) for item in value]
        record = {
            "session_id": state.get("session_id", self.session_id),
            "step": state.get("step"),
            "execution_id": event.get("execution_id"),
            "attempt_id": event.get("attempt_id"),
            "event_type": event_type,
            "skill": event.get("skill"),
            "subtask": event.get("subtask"),
            "status": event.get("next_status", event.get("decision")),
            "reason": event.get("transition_reason")
            or (
                verification.get("reason")
                if isinstance(verification, Mapping)
                else None
            ),
            "confidence": confidence,
            "task_progress": task_progress,
            "evidence_summary": [str(item)[:256] for item in evidence[:3]],
            "recovery_action": event.get("recovery_action"),
            "artifact_refs": artifact_refs,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.recent_events.append(record)
        if self.event_path is not None:
            with self.event_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")

        if event_type not in KEY_EVENT_TYPES:
            return

        self._key_event_sequence += 1
        event_id = f"{record['session_id']}:key-event:{self._key_event_sequence}"
        planner_output = event.get("planner_output")
        expected_outcome = (
            planner_output.get("expected_outcome")
            if isinstance(planner_output, Mapping)
            else None
        )
        text_summary = self._key_event_text(record)[: self.summary_max_chars]
        key_record = {
            **record,
            "event_id": event_id,
            "expected_outcome": expected_outcome,
            "text_summary": text_summary,
        }
        if self.save_key_event_artifacts:
            artifact_dir = state.get("artifact_dir")
            if not isinstance(artifact_dir, (str, Path)):
                raise ValueError(
                    "save_key_event_artifacts requires state['artifact_dir']"
                )
            key_event_dir = Path(artifact_dir) / "key_events"
            frame_dir = key_event_dir / (
                f"step-{int(state.get('step', 0)):06d}-"
                f"{self._key_event_sequence:04d}-{event_type}"
            )
            if isinstance(observation, Mapping):
                key_record["artifact_refs"] = [
                    *artifact_refs,
                    *self._save_frames(observation, frame_dir),
                ]
            key_event_dir.mkdir(parents=True, exist_ok=True)
            with (key_event_dir / "events.jsonl").open("a", encoding="utf-8") as file:
                file.write(json.dumps(key_record, ensure_ascii=False) + "\n")

        self.key_events.append(key_record)
        self._summary_lines.append(text_summary)
        while len("\n".join(self._summary_lines)) > self.summary_max_chars:
            self._summary_lines.popleft()

    def recall(self, query: dict[str, Any]) -> dict[str, Any]:
        recent_events = list(self.recent_events)
        key_events = self.key_events
        session_id = query.get("session_id", self.session_id)
        if query.get("scope", "session") == "session" and session_id is not None:
            recent_events = [
                event for event in recent_events if event["session_id"] == session_id
            ]
            key_events = [
                event for event in key_events if event["session_id"] == session_id
            ]
        return {
            "working_frames": [
                {**frame, "cameras": dict(frame["cameras"])}
                for frame in self.working_frames
            ],
            "recent_events": [dict(event) for event in recent_events],
            "key_events": [
                dict(event) for event in key_events[-self.key_event_limit :]
            ],
            "summary": "\n".join(self._summary_lines),
        }

    @staticmethod
    def _key_event_text(record: Mapping[str, Any]) -> str:
        return (
            f"step={record.get('step')} event={record.get('event_type')} "
            f"skill={record.get('skill')} subtask={record.get('subtask')} "
            f"reason={record.get('reason')}"
        )

    def _save_frames(
        self, observation: Mapping[str, Any], frame_dir: Path
    ) -> list[str]:
        refs: list[str] = []
        for camera_key in self.camera_keys:
            value = observation.get(camera_key)
            if value is None:
                continue
            frames = value if isinstance(value, list) else [value]
            for index, frame in enumerate(frames):
                suffix = f"-{index}" if len(frames) > 1 else ""
                filename = re.sub(r"[^A-Za-z0-9_.-]+", "_", camera_key)
                path = frame_dir / f"{filename}{suffix}.png"
                self._save_frame(frame, path)
                refs.append(str(path))
        return refs

    @staticmethod
    def _save_frame(frame: Any, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(frame, Image.Image):
            image = frame
        elif isinstance(frame, (bytes, bytearray)):
            with Image.open(io.BytesIO(bytes(frame))) as loaded:
                image = loaded.copy()
        elif isinstance(frame, (str, Path)):
            source = Path(frame)
            if not source.is_file():
                raise TypeError(f"Unsupported frame artifact source: {frame!r}")
            with Image.open(source) as loaded:
                image = loaded.copy()
        else:
            try:
                image = Image.fromarray(frame)
            except Exception as error:
                raise TypeError(
                    f"Unsupported frame artifact type: {type(frame).__name__}"
                ) from error
        image.save(path, format="PNG")
