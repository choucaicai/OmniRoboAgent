from abc import ABC, abstractmethod
from typing import Any


class SkillBackend(ABC):
    """Generate an action payload without executing it."""

    @abstractmethod
    def predict(self, inputs: dict[str, Any]) -> Any:
        """Return an action payload for the current pipeline step."""
        raise NotImplementedError

    def healthcheck(self) -> dict[str, Any]:
        return {"healthy": True}

    def close(self) -> None:
        return None
