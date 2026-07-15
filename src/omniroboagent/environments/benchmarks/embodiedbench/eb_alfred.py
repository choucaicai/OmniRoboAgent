import importlib
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from omniroboagent.environments.base import Environment
from omniroboagent.exceptions import EnvironmentError


class EBAlfredEnvironment(Environment):
    def __init__(
        self,
        eval_set: str = "base",
        selected_indexes: list[int] | None = None,
        down_sample_ratio: float = 1.0,
        detection_box: bool = False,
        resolution: int = 500,
        exp_name: str = "omniroboagent",
        display: int = 1,
        embodiedbench_root: str | Path | None = None,
        env_factory: Callable[..., Any] | None = None,
    ) -> None:
        kwargs = {
            "eval_set": eval_set,
            "selected_indexes": selected_indexes or [],
            "down_sample_ratio": down_sample_ratio,
            "detection_box": detection_box,
            "resolution": resolution,
            "exp_name": exp_name,
        }
        if env_factory is None:
            if embodiedbench_root is not None:
                root = str(Path(embodiedbench_root).resolve())
                if root not in sys.path:
                    sys.path.insert(0, root)
            generated_data_link = Path.cwd() / "data"
            data_link_existed = (
                generated_data_link.exists() or generated_data_link.is_symlink()
            )
            try:
                module = importlib.import_module(
                    "embodiedbench.envs.eb_alfred.EBAlfEnv"
                )
            except ImportError as error:
                raise EnvironmentError(
                    "EB-ALFRED requires EmbodiedBench in the current environment"
                ) from error
            finally:
                if not data_link_existed and generated_data_link.is_symlink():
                    generated_data_link.unlink()
            module.__dict__["X_DISPLAY"] = str(display)
            env_factory = module.EBAlfEnv
        self.env = env_factory(**kwargs)
        self.eval_set = eval_set
        self.selected_indexes = selected_indexes or []
        self.last_result: dict[str, Any] = {}
        self.closed = False

    @property
    def tasks(self) -> list[Any]:
        return list(self.env.dataset)

    @property
    def available_skills(self) -> list[str]:
        return list(self.env.language_skill_set or [])

    def reset(self, task: Any) -> dict[str, Any]:
        if self.closed:
            raise EnvironmentError("EBAlfredEnvironment is closed")
        observation = self.env.reset()
        if not isinstance(observation, dict):
            raise EnvironmentError("EBAlfEnv.reset() must return a dict")
        self.last_result = {
            "task_success": False,
            "task_progress": 0.0,
            "last_action_success": True,
            "done": False,
        }
        return {**observation, "available_skills": self.available_skills}

    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        if not isinstance(action, str):
            raise EnvironmentError(
                "EB-ALFRED action must be a language skill string, got "
                f"{type(action).__name__}"
            )
        if action not in self.available_skills:
            self.env._cur_invalid_actions += 1
            done = self.env._cur_invalid_actions >= self.env._max_invalid_actions
            self.last_result = {
                "observation": {
                    "head_rgb": self.env.env.last_event.frame,
                    "available_skills": self.available_skills,
                },
                "reward": -1.0,
                "done": done,
                "task_success": False,
                "task_progress": float(self.last_result.get("task_progress", 0.0)),
                "last_action_success": False,
                "env_feedback": f"Unavailable language skill: {action}",
                "action_description": action,
            }
            return self.last_result

        observation, reward, done, info = self.env.step(action)
        if not isinstance(info, dict) or not isinstance(observation, dict):
            raise EnvironmentError("EBAlfEnv.step() returned an invalid result")
        self.last_result = {
            "observation": {
                **observation,
                "available_skills": self.available_skills,
            },
            "reward": float(reward),
            "done": bool(done),
            "task_success": bool(info.get("task_success", False)),
            "task_progress": float(info.get("task_progress", 0.0)),
            "last_action_success": bool(info.get("last_action_success", False)),
            "env_feedback": info.get("env_feedback", ""),
            "env_step": info.get("env_step"),
            "episode_elapsed_seconds": info.get("episode_elapsed_seconds"),
            "action_description": info.get("action_description", action),
            "info": info,
        }
        return self.last_result

    def close(self) -> None:
        if not self.closed:
            self.env.close()
            self.closed = True
