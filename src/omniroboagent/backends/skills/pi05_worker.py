import json
import socket
from typing import Any

from omniroboagent.backends.skills.base import SkillBackend
from omniroboagent.exceptions import BackendError


class Pi05WorkerBackend(SkillBackend):
    """Client for the existing resident pi0.5 JSON-line worker, without restarts."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 9665,
        horizon: int = 32,
        num_steps: int = 10,
        prompt_mode: str = "subtask",
        timeout_seconds: float = 180,
    ) -> None:
        if prompt_mode not in {"subtask", "task_skill_subtask"}:
            raise ValueError("Unknown prompt_mode")
        if min(port, horizon, num_steps, timeout_seconds) <= 0:
            raise ValueError("Worker port, budgets and timeout must be positive")
        self.host, self.port = host, port
        self.horizon, self.num_steps = horizon, num_steps
        self.prompt_mode = prompt_mode
        self.timeout_seconds = timeout_seconds

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            with socket.create_connection(
                (self.host, self.port), timeout=self.timeout_seconds
            ) as connection:
                connection.sendall((json.dumps(payload) + "\n").encode())
                with connection.makefile("rb") as stream:
                    line = stream.readline(8 * 1024 * 1024)
                result = json.loads(line)
        except (OSError, ValueError) as error:
            raise BackendError(f"pi0.5 worker request failed: {error}") from error
        if not isinstance(result, dict):
            raise BackendError("pi0.5 worker response must be a dict")
        return result

    def healthcheck(self) -> dict[str, Any]:
        try:
            result = self._request({"op": "health"})
            return {"healthy": result.get("status") == "ok"}
        except BackendError as error:
            return {"healthy": False, "error": str(error)}

    def predict(self, inputs: dict[str, Any]) -> Any:
        observation = inputs["observation"]
        prompt = inputs["subtask"]
        if not isinstance(prompt, str) or not prompt.strip():
            raise BackendError("A non-empty subtask is required")
        task_context = inputs.get("task")
        if isinstance(task_context, dict):
            # Keep the public Omni task envelope while excluding scheduler-only
            # identifiers and budgets from the VLA worker boundary.
            task_context = {
                key: value
                for key, value in task_context.items()
                if key not in {"chunk_budgets", "episode_index", "seed", "schedule_id"}
            }
        elif task_context is None:
            task_context = observation.get("annotation.human.task_description")
        if self.prompt_mode == "task_skill_subtask":
            task = observation["annotation.human.task_description"]
            prompt = f"Task: {task}\nSkill: {inputs['skill']}\nSubtask: {prompt}"
        response = self._request(
            {
                "artifact_dir": observation["artifact_dir"],
                "motion_plan": {"vla_prompt": prompt},
                # Keep the Omni-style skill envelope on the worker boundary.  The
                # pi0.5 policy still consumes only motion_plan.vla_prompt; these
                # fields make the execution trace and alternate skill backends
                # protocol-compatible without changing action semantics.
                "omni_context": {
                    "task": task_context,
                    "skill": inputs.get("skill"),
                    "skill_id": inputs.get("skill_id"),
                    "subtask": inputs.get("subtask"),
                    "grounded_arguments": inputs.get("grounded_arguments", {}),
                    "expected_outcome": inputs.get("expected_outcome"),
                    "execution_id": inputs.get("execution_id"),
                    "attempt_id": inputs.get("attempt_id"),
                },
                "num_steps": self.num_steps,
                "horizon": self.horizon,
            }
        )
        chunk = response.get("action_chunk")
        if response.get("success") is not True or not isinstance(chunk, dict):
            raise BackendError(f"pi0.5 inference failed: {response.get('errors')}")
        return {
            **chunk,
            "source_observation_id": observation["observation_id"],
            "vla_prompt": prompt,
        }
