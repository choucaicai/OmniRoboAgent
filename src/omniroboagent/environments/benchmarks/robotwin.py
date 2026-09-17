import math
import uuid
from pathlib import Path
from typing import Any

from omniroboagent.environments.base import Environment


class RoboTwinEnvironment(Environment):
    """Use the existing simulator adapter beneath Omni's own Runtime/Pipeline."""

    def __init__(
        self,
        config_path: str,
        artifact_dir: str,
        available_skills: list[str] | None = None,
    ) -> None:
        self.config_path = config_path
        self.artifact_dir = Path(artifact_dir).resolve()
        self.adapter: Any = None
        self.observation: dict[str, Any] = {}
        self._captures = 0
        self._episode_id = ""
        self._instruction = ""
        self.available_skills = available_skills

    def reset(self, task: Any) -> dict[str, Any]:
        from clawvla.config import load_config  # type: ignore[import-not-found]
        from clawvla.envs.robotwin import (  # type: ignore[import-not-found]
            RoboTwinAdapter,
        )

        self.close()
        self._episode_id = uuid.uuid4().hex
        self._captures = 0
        config = load_config(self.config_path).robotwin
        config.task_name = task["task_name"]
        config.seed = int(task["seed"])
        config.now_ep_num = int(task.get("episode_index", 0))
        config.artifact_dir = str(self.artifact_dir / self._episode_id)
        config.is_test = config.eval_mode = True
        config.render_freq = 0
        self._instruction = task["instruction"]
        self.adapter = RoboTwinAdapter(config)
        bundle = self.adapter.capture_views(
            setup=True, instruction=self._instruction, artifact_prefix="obs_0000"
        )
        return self._observation(bundle)

    def _observation(self, bundle: Any) -> dict[str, Any]:
        result: dict[str, Any] = {
            "observation_id": f"{self._episode_id}:{self._captures}",
            "artifact_dir": str(Path(bundle.raw["summary_ref"]).parent),
            "annotation.human.task_description": self._instruction,
        }
        for key, camera in (
            ("head_rgb", "head_camera"),
            ("left_rgb", "left_camera"),
            ("right_rgb", "right_camera"),
        ):
            view = bundle.camera_views.get(camera)
            if view is None or not view.rgb_path:
                raise ValueError(f"Missing RoboTwin camera: {camera}")
            result[key] = view.rgb_path
        if self.available_skills is not None:
            result["available_skills"] = list(self.available_skills)
        self.observation = result
        return result

    def observe(self) -> dict[str, Any]:
        self._captures += 1
        bundle = self.adapter.capture_views(
            instruction=self._instruction,
            artifact_prefix=f"obs_{self._captures:04d}",
        )
        return self._observation(bundle)

    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        commands = action.get("commands") if isinstance(action, dict) else None
        reason = None
        if not isinstance(action, dict) or action.get("action_type") != "qpos":
            reason = "RoboTwin requires a qpos action chunk"
        elif action.get("source_observation_id") != self.observation["observation_id"]:
            reason = "Action was generated from a stale observation"
        elif not isinstance(commands, list) or not commands:
            reason = "Action chunk has no commands"
        else:
            # Validate the whole chunk before sending any command to the robot.
            try:
                if any(
                    not isinstance(row, list)
                    or len(row) != 14
                    or any(isinstance(v, bool) or not math.isfinite(v) for v in row)
                    for row in commands
                ):
                    reason = "Action commands must be finite 14D qpos vectors"
            except (TypeError, ValueError):
                reason = "Action commands must be numeric"
        if reason:
            return {
                "observation": self.observation,
                "task_success": False,
                "done": False,
                "last_action_success": False,
                "executed_steps": 0,
                "env_feedback": reason,
            }
        assert isinstance(commands, list)
        if execute_steps is not None:
            if execute_steps <= 0:
                raise ValueError("execute_steps must be positive")
            commands = commands[:execute_steps]
        from clawvla.schema import ActionChunk  # type: ignore[import-not-found]

        self._captures += 1
        chunk = ActionChunk(
            action_type="qpos",
            commands=commands,
            control_horizon=len(commands),
            metadata={"artifact_prefix": f"action_{self._captures:04d}"},
        )
        report = self.adapter.execute_action(chunk)
        task_env = self.adapter.session.task_env
        success = bool(report.get("success"))
        return {
            "observation": self._observation(self.adapter.last_observation),
            "task_success": success,
            "done": success or task_env.take_action_cnt >= task_env.step_lim,
            "last_action_success": report.get("status") == "action_executed",
            "executed_steps": report.get("executed_steps", 0),
            "env_feedback": report.get("status", ""),
        }

    def close(self) -> None:
        if self.adapter is not None:
            self.adapter.close()
            self.adapter = None
