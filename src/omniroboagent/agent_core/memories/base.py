from abc import ABC, abstractmethod
from typing import Any


class Memory(ABC):
    def reset(self, session_id: str) -> None:
        return None

    @abstractmethod
    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        raise NotImplementedError

    def recall(self, query: dict[str, Any]) -> dict[str, Any]:
        return {"working_frames": [], "recent_events": [], "summary": ""}

    def healthcheck(self) -> dict[str, Any]:
        return {"healthy": True}

    def close(self) -> None:
        return None
