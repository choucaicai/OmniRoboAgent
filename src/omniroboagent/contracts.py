from abc import ABC, abstractmethod
from typing import Any


class LLMBackend(ABC):
    @abstractmethod
    def complete(self, inputs: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def healthcheck(self) -> dict[str, Any]:
        return {"healthy": True}

    def close(self) -> None:
        return None


class Planner(ABC):
    @abstractmethod
    def plan(self, inputs: dict[str, Any]) -> Any:
        raise NotImplementedError

    def healthcheck(self) -> dict[str, Any]:
        return {"healthy": True}

    def close(self) -> None:
        return None


class Verifier(ABC):
    @abstractmethod
    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class Memory(ABC):
    @abstractmethod
    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        raise NotImplementedError

    def close(self) -> None:
        return None


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


class Pipeline(ABC):
    @abstractmethod
    def step(
        self,
        agent: BaseAgent,
        environment: Environment,
        state: dict[str, Any],
    ) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def is_terminal(self, output: dict[str, Any], state: dict[str, Any]) -> bool:
        raise NotImplementedError


class Runtime(ABC):
    @abstractmethod
    def run(
        self,
        agent: BaseAgent,
        pipeline: Pipeline,
        environment: Environment,
        task: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        raise NotImplementedError
