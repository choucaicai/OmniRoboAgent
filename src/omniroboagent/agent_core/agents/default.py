from typing import Any

from omniroboagent.agent_core.agents.base import BaseAgent
from omniroboagent.agent_core.memories.base import Memory
from omniroboagent.agent_core.planners.base import Planner
from omniroboagent.agent_core.verifiers.base import Verifier
from omniroboagent.backends.skills.base import SkillBackend


class DefaultAgent(BaseAgent):
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

    def plan(self, inputs: dict[str, Any]) -> Any:
        return self.planner.plan(inputs)

    def predict_action(self, inputs: dict[str, Any]) -> Any:
        return self.skill_backend.predict(inputs)

    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.verifier.verify(inputs)

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
        self.planner.close()
        self.verifier.close()
        self.skill_backend.close()
        self.memory.close()
