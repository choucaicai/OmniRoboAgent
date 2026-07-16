from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class EpisodeRecorder(ABC):
    @abstractmethod
    def start(self, session_dir: Path, session_id: str, task: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def record_observation(
        self,
        observation: Any,
        *,
        step: int,
        labels: list[str] | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def record_step(
        self,
        step: int,
        output: dict[str, Any],
        observation: Any,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def record_exception(self, step: int, error: Exception) -> None:
        raise NotImplementedError

    @abstractmethod
    def finish(self, result: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
