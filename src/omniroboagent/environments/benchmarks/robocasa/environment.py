import importlib
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from omniroboagent.environments.base import Environment
from omniroboagent.exceptions import ConfigError, EnvironmentError
from omniroboagent.serialization import to_jsonable

_ACTION_DIMS = {
    "action.end_effector_position": 3,
    "action.end_effector_rotation": 3,
    "action.gripper_close": 1,
    "action.base_motion": 4,
    "action.control_mode": 1,
}
_ACTION_RANGE_TOLERANCE = 0.05


def _git_metadata(path: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        tracked_status = subprocess.run(
            ["git", "-C", str(path), "status", "--porcelain", "--untracked-files=no"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return {"commit": commit, "tracked_dirty": bool(tracked_status.strip())}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "tracked_dirty": None}


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


class RoboCasaEnvironment(Environment):
    def __init__(
        self,
        robocasa_root: str | Path | None = None,
        enable_render: bool = True,
        render_gpu_device_id: int = 0,
        camera_height: int = 256,
        camera_width: int = 256,
        available_skills: list[str] | None = None,
        environment_factory: Callable[..., Any] | None = None,
    ) -> None:
        if available_skills is not None and (
            not isinstance(available_skills, list)
            or not available_skills
            or any(
                not isinstance(skill, str) or not skill for skill in available_skills
            )
            or len(set(available_skills)) != len(available_skills)
        ):
            raise ConfigError(
                "available_skills must be a non-empty list of unique strings"
            )
        root = robocasa_root or os.environ.get(
            "OMNIROBOAGENT_ROBOCASA_ROOT", "benchmarks/RoboCasa"
        )
        self.robocasa_root = Path(root).expanduser().resolve()
        self.enable_render = enable_render
        self.render_gpu_device_id = render_gpu_device_id
        self.camera_height = camera_height
        self.camera_width = camera_width
        self.available_skills = (
            list(available_skills) if available_skills is not None else None
        )
        self.environment_factory = environment_factory
        self.env: Any = None
        self.task_name: str | None = None
        self.episode_index = 0
        self.max_episode_steps = 0
        self.environment_steps = 0
        self._robocasa: Any = None

    def reset(self, task: Any) -> dict[str, Any]:
        if not isinstance(task, Mapping):
            raise EnvironmentError("RoboCasa task must be a mapping")
        task_name = task.get("name")
        split = task.get("split")
        if not isinstance(task_name, str) or not task_name:
            raise EnvironmentError("RoboCasa task requires a non-empty name")
        if split not in {"pretrain", "target"}:
            raise EnvironmentError("RoboCasa split must be 'pretrain' or 'target'")
        seed = task.get("seed", 0)
        if not isinstance(seed, int):
            raise EnvironmentError("RoboCasa task seed must be an integer")

        self.close()
        self._load_sdk()
        try:
            if self.environment_factory is not None:
                self.env = self.environment_factory(
                    task_name=task_name,
                    split=split,
                    enable_render=self.enable_render,
                    render_gpu_device_id=self.render_gpu_device_id,
                    camera_height=self.camera_height,
                    camera_width=self.camera_width,
                )
            else:
                gym = importlib.import_module("gymnasium")
                self.env = gym.make(
                    f"robocasa/{task_name}",
                    disable_env_checker=True,
                    split=split,
                    enable_render=self.enable_render,
                    render_gpu_device_id=self.render_gpu_device_id,
                    camera_heights=self.camera_height,
                    camera_widths=self.camera_width,
                )
            observation, _ = self.env.reset(seed=seed)
        except Exception as error:
            self.close()
            raise EnvironmentError(
                f"Failed to reset RoboCasa task {task_name!r}: {error}"
            ) from error

        self.task_name = task_name
        self.episode_index = int(task.get("episode_index", 0))
        self.max_episode_steps = int(
            task.get("horizon") or self.get_task_horizon(task_name)
        )
        self.environment_steps = 0
        return self._decorate_observation(observation)

    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        if self.env is None or self.task_name is None:
            raise EnvironmentError("RoboCasa environment must be reset before execute")
        if not isinstance(action, Mapping):
            raise EnvironmentError("RoboCasa action must be a dictionary")
        try:
            import numpy as np
        except ImportError as error:
            raise EnvironmentError("RoboCasa environment requires NumPy") from error

        extra = sorted(set(action) - set(_ACTION_DIMS))
        missing = sorted(set(_ACTION_DIMS) - set(action))
        if missing or extra:
            raise EnvironmentError(
                f"Invalid RoboCasa action keys; missing={missing}, extra={extra}"
            )
        chunk: dict[str, Any] = {}
        horizons: set[int] = set()
        for key, width in _ACTION_DIMS.items():
            array = np.asarray(action[key])
            if array.ndim == 3 and array.shape[0] == 1:
                array = array[0]
            if array.ndim != 2 or array.shape[1] != width:
                raise EnvironmentError(
                    f"RoboCasa action {key!r} must be [T,{width}], got {array.shape}"
                )
            if (
                not np.issubdtype(array.dtype, np.floating)
                or not np.isfinite(array).all()
            ):
                raise EnvironmentError(
                    f"RoboCasa action {key!r} must contain finite floats"
                )
            if np.any(array < -1.0 - _ACTION_RANGE_TOLERANCE) or np.any(
                array > 1.0 + _ACTION_RANGE_TOLERANCE
            ):
                raise EnvironmentError(
                    f"RoboCasa action {key!r} exceeds controller range tolerance"
                )
            horizons.add(int(array.shape[0]))
            chunk[key] = array
        if len(horizons) != 1:
            raise EnvironmentError("RoboCasa action keys must share one chunk horizon")
        chunk_horizon = next(iter(horizons), 0)
        if chunk_horizon <= 0:
            raise EnvironmentError("RoboCasa action chunk must not be empty")
        if execute_steps is not None and execute_steps <= 0:
            raise EnvironmentError("execute_steps must be positive")
        steps_to_execute = min(chunk_horizon, execute_steps or chunk_horizon)

        task_success = False
        done = False
        observation: Any = None
        last_info: dict[str, Any] = {}
        executed_steps = 0
        for step_index in range(steps_to_execute):
            step_action = {key: value[step_index] for key, value in chunk.items()}
            try:
                observation, _, terminated, truncated, info = self.env.step(step_action)
            except Exception as error:
                raise EnvironmentError(
                    "RoboCasa action execution failed at chunk step "
                    f"{step_index}: {error}"
                ) from error
            executed_steps += 1
            self.environment_steps += 1
            last_info = dict(info) if isinstance(info, Mapping) else {}
            task_success = task_success or bool(last_info.get("success", False))
            done = bool(terminated or truncated)
            if self.environment_steps >= self.max_episode_steps:
                done = True
            if task_success or done:
                break

        return {
            "observation": self._decorate_observation(observation),
            "task_success": task_success,
            "task_progress": 1.0 if task_success else 0.0,
            "last_action_success": True,
            "done": done or task_success,
            "executed_steps": executed_steps,
            "environment_steps": self.environment_steps,
            "env_info": to_jsonable(last_info),
            "env_feedback": (
                "task_success"
                if task_success
                else "episode_horizon"
                if done
                else "action_chunk_executed"
            ),
        }

    def resolve_task_set(self, task_set: str) -> list[str]:
        self._load_sdk()
        registry_module = importlib.import_module("robocasa.utils.dataset_registry")
        registry = registry_module.TASK_SET_REGISTRY
        if task_set not in registry:
            available = ", ".join(sorted(registry))
            raise EnvironmentError(
                f"Unknown RoboCasa task_set {task_set!r}; available: {available}"
            )
        return list(dict.fromkeys(registry[task_set]))

    def get_task_horizon(self, task_name: str) -> int:
        self._load_sdk()
        module = importlib.import_module("robocasa.utils.dataset_registry_utils")
        return int(module.get_task_horizon(task_name))

    def metadata(self) -> dict[str, Any]:
        self._load_sdk()
        robocasa_git = _git_metadata(self.robocasa_root)
        robosuite = importlib.import_module("robosuite")
        robosuite_file = getattr(robosuite, "__file__", None)
        if not robosuite_file:
            raise EnvironmentError("Cannot resolve the installed robosuite module")
        robosuite_module = Path(robosuite_file).resolve()
        robosuite_root = robosuite_module.parent.parent
        return {
            "root": str(self.robocasa_root),
            "module_file": str(Path(self._robocasa.__file__).resolve()),
            **robocasa_git,
            "robosuite": {
                "root": str(robosuite_root),
                "module_file": str(robosuite_module),
                **_git_metadata(robosuite_root),
            },
            "versions": {
                "robocasa": _package_version("robocasa"),
                "robosuite": _package_version("robosuite"),
                "mujoco": _package_version("mujoco"),
            },
        }

    def close(self) -> None:
        if self.env is not None:
            self.env.close()
        self.env = None
        self.task_name = None

    def _load_sdk(self) -> None:
        if self._robocasa is not None:
            return
        if not self.robocasa_root.is_dir():
            raise EnvironmentError(
                f"RoboCasa root does not exist: {self.robocasa_root}"
            )
        root = str(self.robocasa_root)
        if root in sys.path:
            sys.path.remove(root)
        sys.path.insert(0, root)
        robosuite_root = self.robocasa_root / "robosuite"
        if (robosuite_root / "robosuite" / "__init__.py").is_file():
            robosuite_path = str(robosuite_root)
            if robosuite_path in sys.path:
                sys.path.remove(robosuite_path)
            sys.path.insert(0, robosuite_path)
        try:
            self._robocasa = importlib.import_module("robocasa")
        except ImportError as error:
            raise EnvironmentError(f"Failed to import RoboCasa: {error}") from error

    def _decorate_observation(self, observation: Any) -> dict[str, Any]:
        if not isinstance(observation, Mapping):
            raise EnvironmentError("RoboCasa observation must be a dictionary")
        result = dict(observation)
        result["available_skills"] = (
            list(self.available_skills)
            if self.available_skills is not None
            else [self.task_name]
            if self.task_name
            else []
        )
        result["task_name"] = self.task_name
        result["episode_index"] = self.episode_index
        return result
