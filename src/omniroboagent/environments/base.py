from abc import ABC, abstractmethod
from typing import Any


class Environment(ABC):
    @abstractmethod
    def reset(self, task: Any) -> Any:
        raise NotImplementedError

    @abstractmethod
    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError
