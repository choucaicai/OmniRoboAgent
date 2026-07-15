import json
import time
import uuid
from pathlib import Path
from typing import Any

from omniroboagent.agent_core.agents.base import BaseAgent
from omniroboagent.environments.base import Environment
from omniroboagent.pipelines.base import Pipeline
from omniroboagent.runtimes.base import Runtime
from omniroboagent.serialization import to_jsonable


class SyncRuntime(Runtime):
    def __init__(
        self,
        max_steps: int = 30,
        max_invalid_actions: int = 10,
        max_retries: int = 10,
        timeout_seconds: float | None = None,
        output_dir: str | Path = "runs",
    ) -> None:
        if max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if max_invalid_actions <= 0 or max_retries <= 0:
            raise ValueError("max_invalid_actions and max_retries must be positive")
        self.max_steps = max_steps
        self.max_invalid_actions = max_invalid_actions
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds
        self.output_dir = Path(output_dir)

    def run(
        self,
        agent: BaseAgent,
        pipeline: Pipeline,
        environment: Environment,
        task: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        session_id = str(kwargs.get("session_id") or uuid.uuid4())
        close_resources = bool(kwargs.get("close_resources", True))
        session_dir = self.output_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        trace_path = session_dir / "trace.jsonl"
        result_path = session_dir / "result.json"
        trace_path.write_text("", encoding="utf-8")
        started = time.monotonic()
        invalid_actions = 0
        replans = 0
        consecutive_retries = 0
        state: dict[str, Any] = {
            "task": task,
            "observation": None,
            "step": 0,
            "session_id": session_id,
            "history": [],
        }
        result: dict[str, Any]
        close_errors: list[str] = []

        try:
            health = agent.healthcheck()
            if not health.get("healthy", False):
                raise RuntimeError(f"Agent healthcheck failed: {health}")

            state["observation"] = environment.reset(task)
            self._append_trace(
                trace_path,
                {"event": "episode_start", "session_id": session_id, "task": task},
            )

            termination_reason: str | None = None
            success = False
            last_output: dict[str, Any] = {}
            while termination_reason is None:
                if (
                    self.timeout_seconds is not None
                    and time.monotonic() - started >= self.timeout_seconds
                ):
                    termination_reason = "timeout"
                    break

                last_output = pipeline.step(agent, environment, state)
                state["step"] += 1
                if last_output.get("invalid_action"):
                    invalid_actions += 1
                    consecutive_retries += 1
                    replans += 1
                else:
                    consecutive_retries = 0
                    if last_output.get("replanned"):
                        replans += 1

                self._append_trace(
                    trace_path,
                    {
                        "event": "step",
                        "session_id": session_id,
                        "step": state["step"],
                        **last_output,
                    },
                )

                if pipeline.is_terminal(last_output, state):
                    success = bool(last_output.get("success", False))
                    termination_reason = str(
                        last_output.get("termination_reason") or "pipeline_terminal"
                    )
                elif invalid_actions >= self.max_invalid_actions:
                    termination_reason = "invalid_action_limit"
                elif consecutive_retries >= self.max_retries:
                    termination_reason = "retry_limit"
                elif state["step"] >= self.max_steps:
                    termination_reason = "step_limit"

            result = {
                "session_id": session_id,
                "success": success,
                "task_progress": float(state.get("task_progress", 0.0)),
                "steps": state["step"],
                "invalid_actions": invalid_actions,
                "replans": replans,
                "planner_calls": int(state.get("planner_calls", 0)),
                "action_chunks": int(state.get("action_chunks", state["step"])),
                "environment_steps": int(state.get("environment_steps", 0)),
                "latency_seconds": time.monotonic() - started,
                "termination_reason": termination_reason,
                "trace_path": str(trace_path),
                "last_output": last_output,
            }
        except Exception as error:
            result = {
                "session_id": session_id,
                "success": False,
                "task_progress": float(state.get("task_progress", 0.0)),
                "steps": state["step"],
                "invalid_actions": invalid_actions,
                "replans": replans,
                "planner_calls": int(state.get("planner_calls", 0)),
                "action_chunks": int(state.get("action_chunks", state["step"])),
                "environment_steps": int(state.get("environment_steps", 0)),
                "latency_seconds": time.monotonic() - started,
                "termination_reason": "exception",
                "error_type": type(error).__name__,
                "error": str(error),
                "trace_path": str(trace_path),
            }
            self._append_trace(
                trace_path,
                {
                    "event": "exception",
                    "session_id": session_id,
                    "error_type": type(error).__name__,
                    "error": str(error),
                },
            )
        finally:
            if close_resources:
                for resource in (environment, agent):
                    try:
                        resource.close()
                    except Exception as error:
                        close_errors.append(
                            f"{type(resource).__name__}: "
                            f"{type(error).__name__}: {error}"
                        )

        if close_errors:
            result["close_errors"] = close_errors

        result_path.write_text(
            json.dumps(to_jsonable(result), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._append_trace(
            trace_path,
            {"event": "episode_end", **result},
        )
        return result

    @staticmethod
    def _append_trace(path: Path, event: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(to_jsonable(event), ensure_ascii=False) + "\n")
