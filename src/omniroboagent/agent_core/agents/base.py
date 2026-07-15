from abc import ABC, abstractmethod
from typing import Any


class BaseAgent(ABC):
    @abstractmethod
    def plan(self, inputs: dict[str, Any]) -> Any:
        raise NotImplementedError

    @abstractmethod
    def predict_action(self, inputs: dict[str, Any]) -> Any:
        raise NotImplementedError

    @abstractmethod
    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        raise NotImplementedError

    def healthcheck(self) -> dict[str, Any]:
        return {"healthy": True}

    def close(self) -> None:
        return None
