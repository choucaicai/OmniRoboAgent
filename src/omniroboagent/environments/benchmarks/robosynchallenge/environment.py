import importlib
import importlib.util
import json
import sys
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, cast

from omniroboagent.environments.base import Environment
from omniroboagent.exceptions import ConfigError, EnvironmentError
from omniroboagent.serialization import to_jsonable

_RESET_STATE_PROTOCOL = "warmup_get_obs_get_info_v2"


def _scalar(value: Any) -> Any:
    if hasattr(value, "numel") and value.numel() != 1:
        raise EnvironmentError("RoboSynChallenge supports one environment only")
    if hasattr(value, "item"):
        return value.item()
    return value


class RoboSynChallengeEnvironment(Environment):
    """Expose native task steps without executing the expert or policy internally."""

    def __init__(
        self,
        robosyn_root: str | Path,
        embodichain_root: str | Path | None = None,
        setting: str = "clear",
        device: str = "cpu",
        headless: bool = True,
        renderer: str = "hybrid",
        gpu_id: int = 0,
        reset_sync_steps: int = 1,
        environment_factory: Callable[..., Any] | None = None,
    ) -> None:
        if reset_sync_steps < 0:
            raise ConfigError("reset_sync_steps must be non-negative")
        self.robosyn_root = Path(robosyn_root).expanduser().resolve()
        self.embodichain_root = (
            Path(embodichain_root).expanduser().resolve()
            if embodichain_root is not None
            else self.robosyn_root.parent.parent / "third_party" / "EmbodiChain"
        )
        self.setting = setting
        self.device = device
        self.headless = headless
        self.renderer = renderer
        self.gpu_id = gpu_id
        self.reset_sync_steps = reset_sync_steps
        self.environment_factory = environment_factory
        self.env: Any = None
        self._upstream: Any = None
        self._task_key: tuple[str, str] | None = None
        self._gym_config: dict[str, Any] = {}
        self.task_name = ""
        self.instruction = ""
        self.seed = 0
        self.episode_index = 0
        self.environment_steps = 0
        self.max_episode_steps = 0
        self.action_dim = 0
        self.episode_id = ""
        self.task_success = False
        self.done = False
        self.outcome = "not_started"

    def _load_sdk(self) -> None:
        if self._upstream is not None:
            return
        helper = self.robosyn_root / "scripts" / "eval_policy.py"
        if not helper.is_file():
            raise EnvironmentError(
                f"RoboSynChallenge eval entrypoint missing: {helper}"
            )
        for root in reversed((self.robosyn_root, self.embodichain_root)):
            if root.is_dir() and str(root) not in sys.path:
                sys.path.insert(0, str(root))
        spec = importlib.util.spec_from_file_location(
            "_omniroboagent_robosyn_eval_helpers", helper
        )
        if spec is None or spec.loader is None:
            raise EnvironmentError("Cannot import RoboSynChallenge eval helpers")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as error:
            raise EnvironmentError(
                f"Cannot load the optional RoboSynChallenge runtime: {error}"
            ) from error
        self._upstream = module

    def _ensure_environment(self, task: Any) -> None:
        if not isinstance(task, Mapping):
            raise EnvironmentError("RoboSynChallenge task must be a mapping")
        name = task.get("name")
        setting = task.get("setting", self.setting)
        for label, value in (("name", name), ("setting", setting)):
            if (
                not isinstance(value, str)
                or not value
                or Path(value).name != value
                or value in {".", ".."}
            ):
                raise EnvironmentError(f"Task {label} must be a directory name")
        name = cast(str, name)
        setting = cast(str, setting)
        seed = task.get("seed", 0)
        if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
            raise EnvironmentError("Task seed must be an integer in [0, 2**31)")
        task_key = (name, setting)
        if self.env is not None and task_key != self._task_key:
            # DexSim shutdown can exit Python; use a fresh process for another task.
            raise EnvironmentError("Use a new process to change task or setting")
        self.task_name = name
        self.setting = setting
        self.seed = seed
        self.episode_index = int(task.get("episode_index", 0))
        if self.env is not None:
            return

        config_dir = self.robosyn_root / "configs" / name
        gym_path = config_dir / setting / "gym_config.json"
        action_path = config_dir / "action_config.json"
        if not action_path.is_file():
            action_path = config_dir / setting / "action_config.json"
        try:
            gym_config = json.loads(gym_path.read_text())
            action_config = json.loads(action_path.read_text())
        except (OSError, ValueError) as error:
            raise EnvironmentError(
                f"Cannot load task configuration: {error}"
            ) from error
        if int(gym_config.get("num_envs", 1)) != 1:
            raise EnvironmentError("RoboSynChallenge supports one environment only")
        self._load_sdk()
        config = {
            "task_name": name,
            "setting": setting,
            "num_envs": 1,
            "device": self.device,
            "headless": self.headless,
            "renderer": self.renderer,
            "gpu_id": self.gpu_id,
            "seed": self.seed,
            "filter_dataset_saving": True,
        }
        factory = self.environment_factory or self._upstream.make_env_from_configs
        try:
            self.env, self._gym_config = factory(config, gym_config, action_config)
            self.max_episode_steps = int(self._gym_config["max_episode_steps"])
            if self.max_episode_steps <= 0:
                raise EnvironmentError("A positive native episode horizon is required")
            self.action_dim = 1
            for width in self.env.unwrapped.single_action_space.shape:
                self.action_dim *= int(width)
            self.instruction = self._upstream.extract_instruction_from_gym_config(
                self._gym_config
            ) or name.replace("_", " ")
            self.env._current_instruction = self.instruction
            self._task_key = task_key
        except Exception as error:
            raise EnvironmentError(
                f"Cannot create RoboSynChallenge task: {error}"
            ) from error

    def check_episode_feasibility(self, task: Any) -> dict[str, Any]:
        """Match the official seed filter: generate a plan, do not execute it."""
        self._ensure_environment(task)
        with self._upstream.suppress_expert_output():
            return dict(self._upstream.check_episode_feasibility(self.env, self.seed))

    def reset(self, task: Any) -> dict[str, Any]:
        self._ensure_environment(task)
        try:
            self.seed = self._upstream.prepare_episode_reset(self.env, self.seed)
            observation, _ = self.env.reset(
                seed=self.seed, options={"save_data": False}
            )
            if self.reset_sync_steps:
                target = self.env.unwrapped
                target.sim.update(target.sim_cfg.physics_dt, self.reset_sync_steps)
                observation = target.get_obs()
                target.get_info()
            self.environment_steps = 0
            self.episode_id = uuid.uuid4().hex
            self.task_success = False
            self.done = False
            self.outcome = "in_progress"
            return self._decorate_observation(observation)
        except Exception as error:
            raise EnvironmentError(f"RoboSynChallenge reset failed: {error}") from error

    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        if self.env is None or not self.episode_id or self.done:
            raise EnvironmentError("Reset RoboSynChallenge before executing actions")
        if not isinstance(action, Mapping) or "actions" not in action:
            raise EnvironmentError(
                "RoboSynChallenge action requires an 'actions' array"
            )
        if execute_steps is not None and (
            isinstance(execute_steps, bool)
            or not isinstance(execute_steps, int)
            or execute_steps <= 0
        ):
            raise EnvironmentError("execute_steps must be a positive integer")
        torch = importlib.import_module("torch")
        try:
            values = torch.as_tensor(action["actions"])
            if values.dtype == torch.bool:
                raise ValueError("Boolean values are not joint actions")
            values = values.to(dtype=torch.float32, device=self.env.unwrapped.device)
            if values.ndim == 1:
                values = values.unsqueeze(0)
            if (
                values.ndim != 2
                or values.shape[0] == 0
                or values.shape[1] != self.action_dim
                or not bool(torch.isfinite(values).all().item())
            ):
                raise ValueError(
                    f"Expected finite non-empty [T,{self.action_dim}] actions"
                )
        except (TypeError, ValueError, RuntimeError) as error:
            raise EnvironmentError(
                f"Invalid RoboSynChallenge action: {error}"
            ) from error

        count = min(len(values), execute_steps or len(values))
        observation: Any = None
        info: Any = {}
        executed = 0
        for index in range(count):
            try:
                observation, _, terminated, truncated, info = self.env.step(
                    values[index : index + 1]
                )
                executed += 1
                self.environment_steps += 1
                is_truncated = bool(_scalar(truncated))
                # The official evaluator rejects success on a truncated step.
                self.task_success = not is_truncated and bool(
                    _scalar(self.env.get_wrapper_attr("is_task_success")())
                )
                self.done = (
                    self.task_success
                    or is_truncated
                    or bool(_scalar(terminated))
                    or self.environment_steps >= self.max_episode_steps
                )
                self.outcome = (
                    "task_success"
                    if self.task_success
                    else "horizon"
                    if is_truncated or self.environment_steps >= self.max_episode_steps
                    else "environment_terminated"
                    if self.done
                    else "in_progress"
                )
                if self.done:
                    break
            except Exception as error:
                raise EnvironmentError(
                    "RoboSynChallenge step failed at frame "
                    f"{self.environment_steps}: {error}"
                ) from error
        return {
            "observation": self._decorate_observation(observation),
            "task_success": self.task_success,
            "task_progress": float(self.task_success),
            "last_action_success": True,
            "done": self.done,
            "executed_steps": executed,
            "environment_steps": self.environment_steps,
            "env_feedback": self.outcome,
            "env_info": to_jsonable(dict(info)),
        }

    def _decorate_observation(self, observation: Any) -> dict[str, Any]:
        np = importlib.import_module("numpy")
        sensors = observation.get("sensor", {})
        images = {}
        for camera_name in sensors.keys():
            color = sensors[camera_name].get("color")
            if color is None:
                continue
            if hasattr(color, "detach"):
                color = color.detach().cpu().numpy()
            color = np.asarray(color)
            if color.ndim == 4:
                color = color[0]
            color = color[..., :3]
            if color.dtype != np.uint8:
                if color.size and float(np.nanmax(color)) <= 1.5:
                    color = color * 255.0
                color = np.clip(color, 0, 255).astype(np.uint8)
            images[str(camera_name)] = np.ascontiguousarray(color).copy()
        return {
            "task_name": self.task_name,
            "annotation.human.task_description": self.instruction,
            "available_skills": [self.task_name],
            "policy_observation": {
                key: observation[key]
                for key in ("robot", "sensor")
                if key in observation
            },
            "images": list(images.values()),
            **images,
            "head_rgb": images.get("cam_high"),
            "action_dim": self.action_dim,
            "environment_steps": self.environment_steps,
            "episode_id": self.episode_id,
        }

    def metadata(self) -> dict[str, Any]:
        return {
            "root": str(self.robosyn_root),
            "embodichain_root": str(self.embodichain_root),
            "setting": self.setting,
            "device": self.device,
            "renderer": self.renderer,
            "headless": self.headless,
            "gpu_id": self.gpu_id,
            "reset_sync_steps": self.reset_sync_steps,
            "reset_state_protocol": _RESET_STATE_PROTOCOL,
            "action_schema": "native joint positions; task-configured normalization",
            "policy_observation": ["robot", "sensor"],
            "success_signal": "is_task_success() and not truncated",
            "native_gym_config": self._gym_config,
        }

    def episode_metadata(self) -> dict[str, Any]:
        return {
            "task": self.task_name,
            "setting": self.setting,
            "seed": self.seed,
            "episode_index": self.episode_index,
            "environment_steps": self.environment_steps,
            "horizon": self.max_episode_steps,
            "action_dim": self.action_dim,
            "authoritative_success": self.task_success,
            "outcome": self.outcome,
            "seed_protocol": "upstream.prepare_episode_reset + native reset",
            "reset_state_protocol": _RESET_STATE_PROTOCOL,
        }

    def close(self) -> None:
        env, self.env = self.env, None
        if env is not None:
            env.close()
