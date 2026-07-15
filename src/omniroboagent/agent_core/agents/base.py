from abc import ABC, abstractmethod
from typing import Any

from omniroboagent.agent_core.memories.base import Memory
from omniroboagent.agent_core.planners.base import Planner
from omniroboagent.agent_core.verifiers.base import Verifier
from omniroboagent.backends.skills.base import SkillBackend


class BaseAgent(ABC):
    def __init__(
        self,
        planner: Planner,
        verifier: Verifier,
        memory: Memory,
        skill_backend: SkillBackend,
    ) -> None:
        self.planner = planner
        self.verifier = verifier
        self.memory = memory
        self.skill_backend = skill_backend
        self._closed = False

    @abstractmethod
    def plan(self, inputs: dict[str, Any]) -> Any:
        raise NotImplementedError

    @abstractmethod
    def predict_action(self, inputs: dict[str, Any]) -> Any:
        raise NotImplementedError

    @abstractmethod
    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        self.memory.update(state, event)

    def healthcheck(self) -> dict[str, Any]:
        planner = self.planner.healthcheck()
        verifier = self.verifier.healthcheck()
        skill_backend = self.skill_backend.healthcheck()
        return {
            "healthy": bool(planner.get("healthy"))
            and bool(verifier.get("healthy"))
            and bool(skill_backend.get("healthy")),
            "planner": planner,
            "verifier": verifier,
            "skill_backend": skill_backend,
        }

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        errors: list[str] = []
        for name, component in (
            ("planner", self.planner),
            ("verifier", self.verifier),
            ("skill_backend", self.skill_backend),
            ("memory", self.memory),
        ):
            try:
                component.close()
            except Exception as error:
                errors.append(f"{name}: {type(error).__name__}: {error}")
        if errors:
            raise RuntimeError("Failed to close Agent components: " + "; ".join(errors))
