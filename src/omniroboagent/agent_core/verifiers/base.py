from abc import ABC, abstractmethod
from typing import Any


class Verifier(ABC):
    @abstractmethod
    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError
