from typing import Any

from omniroboagent.agent_core.memories.base import Memory


class InMemoryMemory(Memory):
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def reset(self, session_id: str) -> None:
        self.events.clear()

    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        self.events.append(dict(event))

    def recall(self, query: dict[str, Any]) -> dict[str, Any]:
        return {
            "working_frames": [],
            "recent_events": list(self.events),
            "summary": "",
        }
