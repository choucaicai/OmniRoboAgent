from typing import Any

from omniroboagent.contracts import Verifier


class EnvironmentVerifier(Verifier):
    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        result = inputs.get("environment_result")
        if not isinstance(result, dict):
            raise TypeError("EnvironmentVerifier requires an environment_result dict")
        return {
            "task_success": bool(result.get("task_success", False)),
            "task_progress": float(result.get("task_progress", 0.0)),
            "last_action_success": bool(result.get("last_action_success", False)),
            "environment_done": bool(result.get("done", False)),
            "env_feedback": result.get("env_feedback", ""),
        }
