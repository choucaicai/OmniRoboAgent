from typing import Any

from omniroboagent.agent_core.memories.base import Memory


class InMemoryMemory(Memory):
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        self.events.append(dict(event))
