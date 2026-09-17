import importlib
import math
import uuid
from collections.abc import Callable, Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from omniroboagent.environments.base import Environment
from omniroboagent.exceptions import ConfigError, EnvironmentError

_SUITE_HORIZONS = {
    "libero_spatial": 220,
    "libero_object": 280,
    "libero_goal": 300,
    "libero_10": 520,
}
_ACTION_RANGE_TOLERANCE = 0.05


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


class LiberoEnvironment(Environment):
    """Expose official LIBERO tasks through OmniRoboAgent's Environment contract."""

    def __init__(
        self,
        config_path: str | Path,
        artifact_dir: str | Path,
        available_skills: list[str] | None = None,
        adapter_factory: Callable[[Any], Any] | None = None,
    ) -> None:
        if available_skills is not None and (
            not available_skills
            or any(not isinstance(item, str) or not item for item in available_skills)
            or len(set(available_skills)) != len(available_skills)
        ):
            raise ConfigError(
                "available_skills must be a non-empty list of unique strings"
            )
        self.config_path = Path(config_path).expanduser().resolve()
        self.artifact_dir = Path(artifact_dir).expanduser().resolve()
        self.available_skills = (
            list(available_skills) if available_skills is not None else None
        )
        self.adapter_factory = adapter_factory
        self.adapter: Any = None
        self.observation: dict[str, Any] = {}
        self._episode_id = ""
        self._captures = 0
        self._suite = ""
        self._task_id = -1
        self._task_name = ""
        self._instruction = ""
        self._max_environment_steps = 0

    def reset(self, task: Any) -> dict[str, Any]:
        if not isinstance(task, Mapping):
            raise EnvironmentError("LIBERO task must be a mapping")
        suite = task.get("suite")
        task_id = task.get("task_id")
        episode_index = task.get("episode_index", 0)
        seed = task.get("seed", 7)
        if not isinstance(suite, str) or suite not in _SUITE_HORIZONS:
            raise EnvironmentError(
                f"LIBERO suite must be one of {sorted(_SUITE_HORIZONS)}"
            )
        if type(task_id) is not int or task_id < 0:
            raise EnvironmentError("LIBERO task_id must be a non-negative integer")
        if type(episode_index) is not int or episode_index < 0:
            raise EnvironmentError(
                "LIBERO episode_index must be a non-negative integer"
            )
        if type(seed) is not int:
            raise EnvironmentError("LIBERO seed must be an integer")

        supplied_instruction = task.get("instruction")
        supplied_name = task.get("name")
        init_state_count = task.get("init_state_count")
        if (
            not isinstance(supplied_instruction, str)
            or not supplied_instruction
            or not isinstance(supplied_name, str)
            or not supplied_name
            or type(init_state_count) is not int
        ):
            specs = self.resolve_suite(suite)
            if task_id >= len(specs):
                raise EnvironmentError(
                    f"LIBERO task_id is outside suite {suite!r}: "
                    f"{task_id}>={len(specs)}"
                )
            spec = specs[task_id]
            supplied_instruction = spec["instruction"]
            supplied_name = spec["name"]
            init_state_count = spec["init_state_count"]
        if episode_index >= init_state_count:
            raise EnvironmentError(
                "LIBERO episode_index is outside the official initial-state set: "
                f"{episode_index}>={init_state_count}"
            )

        self.close()
        self._episode_id = uuid.uuid4().hex
        self._captures = 0
        self._suite = suite
        self._task_id = task_id
        self._task_name = supplied_name
        self._instruction = supplied_instruction
        horizon = task.get("horizon", _SUITE_HORIZONS[suite])
        if type(horizon) is not int or horizon <= 0:
            raise EnvironmentError("LIBERO horizon must be a positive integer")
        self._max_environment_steps = horizon

        try:
            from clawvla.config import load_config  # type: ignore[import-not-found]
            from clawvla.envs.libero import (  # type: ignore[import-not-found]
                LiberoAdapter,
            )

            config = load_config(self.config_path).environment
            config.task_name = suite
            config.seed = seed
            config.artifact_dir = str(self.artifact_dir / self._episode_id)
            config.params = {
                **dict(config.params),
                "suite": suite,
                "task_id": task_id,
                "episode_index": episode_index,
            }
            factory = self.adapter_factory or LiberoAdapter
            self.adapter = factory(config)
            bundle = self.adapter.capture_views(
                setup=True,
                instruction=self._instruction,
                artifact_prefix="obs_0000",
            )
        except Exception as error:
            self.close()
            raise EnvironmentError(
                f"Failed to reset LIBERO {suite}[{task_id}]: {error}"
            ) from error
        return self._observation(bundle)

    def observe(self) -> dict[str, Any]:
        if self.adapter is None:
            raise EnvironmentError("LIBERO environment must be reset before observe")
        self._captures += 1
        bundle = self.adapter.capture_views(
            instruction=self._instruction,
            artifact_prefix=f"obs_{self._captures:04d}",
        )
        return self._observation(bundle)

    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        reason = self._validate_action(action, execute_steps)
        if reason is not None:
            return {
                "observation": self.observation,
                "task_success": False,
                "task_progress": 0.0,
                "last_action_success": False,
                "done": False,
                "executed_steps": 0,
                "environment_steps": self._environment_steps(),
                "env_feedback": reason,
            }

        commands = action["commands"]
        if execute_steps is not None:
            commands = commands[:execute_steps]
        try:
            from clawvla.schema import ActionChunk  # type: ignore[import-not-found]

            self._captures += 1
            chunk = ActionChunk(
                action_type="libero_ee_delta",
                commands=[[float(value) for value in row] for row in commands],
                control_horizon=len(commands),
                metadata={"artifact_prefix": f"action_{self._captures:04d}"},
            )
            report = self.adapter.execute_action(chunk)
        except Exception as error:
            raise EnvironmentError(
                f"LIBERO action execution failed: {error}"
            ) from error

        status = str(report.get("status", ""))
        action_succeeded = status == "action_executed"
        success = bool(report.get("success", False))
        environment_steps = self._environment_steps()
        done = bool(report.get("done", False)) or success
        if environment_steps >= self._max_environment_steps:
            done = True
        bundle = getattr(self.adapter, "last_observation", None)
        observation = (
            self._observation(bundle) if bundle is not None else self.observation
        )
        return {
            "observation": observation,
            "task_success": success,
            "task_progress": 1.0 if success else 0.0,
            "last_action_success": action_succeeded,
            "done": done,
            "executed_steps": int(report.get("executed_steps", 0)),
            "environment_steps": environment_steps,
            "env_feedback": (
                "task_success"
                if success
                else "episode_horizon"
                if done
                else status or "action_execution_failed"
            ),
        }

    def resolve_suite(self, suite: str) -> list[dict[str, Any]]:
        if suite not in _SUITE_HORIZONS:
            raise ConfigError(f"Unknown LIBERO suite: {suite!r}")
        try:
            benchmark = importlib.import_module("libero.libero.benchmark")
            suite_type = benchmark.get_benchmark_dict()[suite]
            task_suite = suite_type()
            result = []
            for task_id in range(int(task_suite.n_tasks)):
                task = task_suite.get_task(task_id)
                init_states = task_suite.get_task_init_states(task_id)
                result.append(
                    {
                        "task_id": task_id,
                        "name": str(task.name),
                        "instruction": str(task.language),
                        "init_state_count": len(init_states),
                    }
                )
            return result
        except Exception as error:
            raise EnvironmentError(
                f"Failed to resolve LIBERO suite {suite!r}: {error}"
            ) from error

    @staticmethod
    def get_suite_horizon(suite: str) -> int:
        if suite not in _SUITE_HORIZONS:
            raise ConfigError(f"Unknown LIBERO suite: {suite!r}")
        return _SUITE_HORIZONS[suite]

    def metadata(self) -> dict[str, Any]:
        return {
            "benchmark": "LIBERO",
            "config_path": str(self.config_path),
            "suite": self._suite or None,
            "task_id": self._task_id if self._task_id >= 0 else None,
            "task_name": self._task_name or None,
            "versions": {
                "libero": _package_version("libero"),
                "robosuite": _package_version("robosuite"),
                "mujoco": _package_version("mujoco"),
            },
        }

    def close(self) -> None:
        if self.adapter is not None:
            self.adapter.close()
        self.adapter = None
        self.observation = {}

    def _observation(self, bundle: Any) -> dict[str, Any]:
        if bundle is None:
            raise EnvironmentError("LIBERO adapter returned no observation")
        views = getattr(bundle, "camera_views", {})
        agentview = views.get("agentview")
        wrist = views.get("wrist")
        if agentview is None or not getattr(agentview, "rgb_path", None):
            raise EnvironmentError("LIBERO observation is missing agentview RGB")
        if wrist is None or not getattr(wrist, "rgb_path", None):
            raise EnvironmentError("LIBERO observation is missing wrist RGB")
        raw = getattr(bundle, "raw", {})
        state = raw.get("libero_state8") if isinstance(raw, Mapping) else None
        if (
            not isinstance(state, list)
            or len(state) != 8
            or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in state
            )
        ):
            raise EnvironmentError("LIBERO observation requires a finite 8D state")
        summary_ref = raw.get("summary_ref") if isinstance(raw, Mapping) else None
        artifact_dir = (
            str(Path(summary_ref).parent)
            if isinstance(summary_ref, str) and summary_ref
            else str(self.artifact_dir / self._episode_id)
        )
        skills = self.available_skills or [self._task_name]
        result = {
            "observation_id": f"{self._episode_id}:{self._captures}",
            "artifact_dir": artifact_dir,
            "agentview_rgb": str(agentview.rgb_path),
            "wrist_rgb": str(wrist.rgb_path),
            "images": [str(agentview.rgb_path), str(wrist.rgb_path)],
            "libero_state8": [float(value) for value in state],
            "annotation.human.task_description": self._instruction,
            "available_skills": list(skills),
            "suite": self._suite,
            "task_id": self._task_id,
            "task_name": self._task_name,
        }
        self.observation = result
        return result

    def _validate_action(self, action: Any, execute_steps: int | None) -> str | None:
        if self.adapter is None:
            return "LIBERO environment must be reset before execute"
        if not isinstance(action, Mapping):
            return "LIBERO requires an action dictionary"
        if action.get("action_type") != "libero_ee_delta":
            return "LIBERO requires a libero_ee_delta action chunk"
        if action.get("source_observation_id") != self.observation.get(
            "observation_id"
        ):
            return "Action was generated from a stale observation"
        commands = action.get("commands")
        if not isinstance(commands, list) or not commands:
            return "Action chunk has no commands"
        if execute_steps is not None and execute_steps <= 0:
            return "execute_steps must be positive"
        try:
            for row in commands:
                if (
                    not isinstance(row, list)
                    or len(row) != 7
                    or any(
                        isinstance(value, bool)
                        or not isinstance(value, (int, float))
                        or not math.isfinite(value)
                        or abs(value) > 1.0 + _ACTION_RANGE_TOLERANCE
                        for value in row
                    )
                ):
                    return "Action commands must be finite 7D values in [-1, 1]"
        except (TypeError, ValueError):
            return "Action commands must be numeric"
        return None

    def _environment_steps(self) -> int:
        return int(getattr(self.adapter, "step_count", 0)) if self.adapter else 0
