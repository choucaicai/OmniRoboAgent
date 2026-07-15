from abc import ABC, abstractmethod
from typing import Any

from omniroboagent.agent_core.agents.base import BaseAgent
from omniroboagent.environments.base import Environment


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
