from abc import ABC, abstractmethod
from typing import Any


class Memory(ABC):
    @abstractmethod
    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None
