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
        super().__init__(planner, verifier, memory, skill_backend)

    def plan(self, inputs: dict[str, Any]) -> Any:
        return self.planner.plan(inputs)

    def predict_action(self, inputs: dict[str, Any]) -> Any:
        return self.skill_backend.predict(inputs)

    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return self.verifier.verify(inputs)
