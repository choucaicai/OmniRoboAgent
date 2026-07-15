import json
from collections import deque
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from omniroboagent.agent_core.memories.base import Memory


class TieredMemory(Memory):
    """Bounded visual working memory with durable structured event summaries."""

    def __init__(
        self,
        visual_window_size: int = 4,
        recent_event_limit: int = 20,
        summary_max_chars: int = 4096,
        camera_keys: list[str] | None = None,
        event_path: str | Path | None = None,
    ) -> None:
        if visual_window_size <= 0:
            raise ValueError("visual_window_size must be positive")
        if recent_event_limit <= 0:
            raise ValueError("recent_event_limit must be positive")
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
        self.summary_max_chars = summary_max_chars
        self.camera_keys = list(resolved_camera_keys)
        self.event_path = Path(event_path) if event_path is not None else None
        if self.event_path is not None:
            self.event_path.parent.mkdir(parents=True, exist_ok=True)

        self.session_id: str | None = None
        self.working_frames: deque[dict[str, Any]] = deque(
            maxlen=visual_window_size
        )
        self.event_memory: list[dict[str, Any]] = []
        self._summary_lines: deque[str] = deque()

    def reset(self, session_id: str) -> None:
        self.session_id = session_id
        self.working_frames.clear()
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
        evidence = event.get("verifier_evidence", [])
        if not isinstance(evidence, list):
            evidence = [str(evidence)]
        artifact_refs = []
        if isinstance(environment_result, Mapping):
            value = environment_result.get("artifact_refs", [])
            if isinstance(value, list):
                artifact_refs = [str(item) for item in value]
        record = {
            "session_id": state.get("session_id", self.session_id),
            "step": state.get("step"),
            "execution_id": event.get("execution_id"),
            "attempt_id": event.get("attempt_id"),
            "event_type": "transition",
            "skill": event.get("skill"),
            "subtask": event.get("subtask"),
            "status": event.get("next_status", event.get("decision")),
            "reason": event.get("transition_reason"),
            "confidence": confidence,
            "evidence_summary": [str(item)[:256] for item in evidence[:3]],
            "recovery_action": event.get("recovery_action"),
            "artifact_refs": artifact_refs,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        self.event_memory.append(record)
        if self.event_path is not None:
            with self.event_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")

        line = (
            f"step={record['step']} skill={record['skill']} "
            f"status={record['status']} reason={record['reason']}"
        )
        if record["recovery_action"]:
            line += f" recovery={record['recovery_action']}"
        self._summary_lines.append(line[: self.summary_max_chars])
        while len("\n".join(self._summary_lines)) > self.summary_max_chars:
            self._summary_lines.popleft()

    def recall(self, query: dict[str, Any]) -> dict[str, Any]:
        events = self.event_memory
        session_id = query.get("session_id")
        if session_id is not None and query.get("scope", "session") == "session":
            events = [event for event in events if event["session_id"] == session_id]
        return {
            "working_frames": [
                {**frame, "cameras": dict(frame["cameras"])}
                for frame in self.working_frames
            ],
            "recent_events": [
                dict(event) for event in events[-self.recent_event_limit :]
            ],
            "summary": "\n".join(self._summary_lines),
        }
