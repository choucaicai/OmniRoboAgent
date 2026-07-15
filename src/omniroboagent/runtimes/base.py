from abc import ABC, abstractmethod
from typing import Any

from omniroboagent.agent_core.agents.base import BaseAgent
from omniroboagent.environments.base import Environment
from omniroboagent.pipelines.base import Pipeline


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
