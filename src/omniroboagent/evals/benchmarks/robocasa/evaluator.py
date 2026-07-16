import json
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from omniroboagent.agent_core.agents.base import BaseAgent
from omniroboagent.environments.benchmarks.robocasa import RoboCasaEnvironment
from omniroboagent.exceptions import ConfigError
from omniroboagent.pipelines.base import Pipeline
from omniroboagent.runtimes.base import Runtime
from omniroboagent.serialization import to_jsonable


def _class_path(value: Any) -> str:
    cls = type(value)
    return f"{cls.__module__}.{cls.__qualname__}"


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


class RoboCasa365Evaluator:
    def __init__(
        self,
        environment: RoboCasaEnvironment,
        task_set: str,
        split: str,
        output_dir: str | Path,
        task_names: list[str] | None = None,
        max_tasks: int | None = None,
        episodes_per_task: int = 50,
        episode_indices: list[int] | None = None,
        seed: int = 0,
    ) -> None:
        if not isinstance(task_set, str) or not task_set:
            raise ConfigError("RoboCasa task_set must be a non-empty string")
        if split not in {"pretrain", "target"}:
            raise ConfigError("RoboCasa split must be 'pretrain' or 'target'")
        if max_tasks is not None and max_tasks <= 0:
            raise ConfigError("max_tasks must be positive")
        if episodes_per_task <= 0:
            raise ConfigError("episodes_per_task must be positive")
        if episode_indices is not None and len(episode_indices) < episodes_per_task:
            raise ConfigError(
                "episode_indices must contain at least episodes_per_task values"
            )
        if episode_indices is not None and (
            any(not isinstance(index, int) or index < 0 for index in episode_indices)
            or len(set(episode_indices)) != len(episode_indices)
        ):
            raise ConfigError("episode_indices must be unique non-negative integers")
        if not isinstance(seed, int):
            raise ConfigError("seed must be an integer")
        self.environment = environment
        self.task_set = task_set
        self.split = split
        self.output_dir = Path(output_dir)
        self.task_names = task_names
        self.max_tasks = max_tasks
        self.episodes_per_task = episodes_per_task
        self.episode_indices = episode_indices
        self.seed = seed

    def run(
        self,
        agent: BaseAgent,
        pipeline: Pipeline,
        runtime: Runtime,
    ) -> dict[str, Any]:
        tasks, registered_tasks = self._resolve_tasks()
        episode_indices = self.episode_indices or list(range(self.episodes_per_task))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        episodes_path = self.output_dir / "episodes.jsonl"
        episodes_path.write_text("", encoding="utf-8")
        results: list[dict[str, Any]] = []
        try:
            project_root = Path(__file__).resolve().parents[5]
            try:
                project_commit = subprocess.run(
                    ["git", "-C", str(project_root), "rev-parse", "HEAD"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()
            except (OSError, subprocess.CalledProcessError):
                project_commit = None
            try:
                project_dirty = bool(
                    subprocess.run(
                        ["git", "-C", str(project_root), "status", "--porcelain"],
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip()
                )
            except (OSError, subprocess.CalledProcessError):
                project_dirty = None
            resolved = {
                "benchmark": "RoboCasa365",
                "task_set": self.task_set,
                "task_set_size": len(registered_tasks),
                "split": self.split,
                "task_names": tasks,
                "episodes_per_task": self.episodes_per_task,
                "episode_indices": episode_indices[: self.episodes_per_task],
                "seed": self.seed,
                "episode_index_semantics": "seed_offset",
                "robocasa": self.environment.metadata(),
                "omniroboagent": {
                    "commit": project_commit,
                    "dirty": project_dirty,
                    "version": _package_version("omniroboagent"),
                    "python": sys.version.split()[0],
                    "numpy": _package_version("numpy"),
                    "gymnasium": _package_version("gymnasium"),
                    "mujoco": _package_version("mujoco"),
                    "torch": _package_version("torch"),
                },
                "components": {
                    "agent": _class_path(agent),
                    "planner": _class_path(getattr(agent, "planner", None)),
                    "skill_backend": _class_path(getattr(agent, "skill_backend", None)),
                    "verifier": _class_path(getattr(agent, "verifier", None)),
                    "memory": _class_path(getattr(agent, "memory", None)),
                    "pipeline": _class_path(pipeline),
                    "runtime": _class_path(runtime),
                    "environment": _class_path(self.environment),
                },
                "pipeline": {
                    "action_execution_mode": getattr(
                        pipeline, "action_execution_mode", None
                    ),
                    "execute_steps": getattr(pipeline, "execute_steps", None),
                    "planner_check_interval_chunks": getattr(
                        pipeline, "planner_check_interval_chunks", None
                    ),
                    "max_chunks_per_skill": getattr(
                        pipeline, "max_chunks_per_skill", None
                    ),
                    "max_attempts_per_execution": getattr(
                        pipeline, "max_attempts_per_execution", None
                    ),
                    "max_uncertain_verifications": getattr(
                        pipeline, "max_uncertain_verifications", None
                    ),
                    "max_no_progress_steps": getattr(
                        pipeline, "max_no_progress_steps", None
                    ),
                    "max_replans": getattr(pipeline, "max_replans", None),
                },
                "verifier": {
                    "check_interval_chunks": getattr(
                        getattr(agent, "verifier", None),
                        "check_interval_chunks",
                        None,
                    ),
                },
                "memory": {
                    "visual_window_size": getattr(
                        getattr(agent, "memory", None),
                        "visual_window_size",
                        None,
                    ),
                    "recent_event_limit": getattr(
                        getattr(agent, "memory", None),
                        "recent_event_limit",
                        None,
                    ),
                    "key_event_limit": getattr(
                        getattr(agent, "memory", None),
                        "key_event_limit",
                        None,
                    ),
                    "summary_max_chars": getattr(
                        getattr(agent, "memory", None),
                        "summary_max_chars",
                        None,
                    ),
                    "save_key_event_artifacts": getattr(
                        getattr(agent, "memory", None),
                        "save_key_event_artifacts",
                        None,
                    ),
                },
                "runtime": {
                    "max_steps": getattr(runtime, "max_steps", None),
                    "max_invalid_actions": getattr(
                        runtime, "max_invalid_actions", None
                    ),
                    "max_retries": getattr(runtime, "max_retries", None),
                    "timeout_seconds": getattr(runtime, "timeout_seconds", None),
                },
                "policy_health": to_jsonable(agent.healthcheck()),
            }
            (self.output_dir / "resolved_config.json").write_text(
                json.dumps(resolved, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            for task_name in tasks:
                horizon = self.environment.get_task_horizon(task_name)
                for ordinal, episode_index in enumerate(
                    episode_indices[: self.episodes_per_task]
                ):
                    task = {
                        "name": task_name,
                        "task_set": self.task_set,
                        "split": self.split,
                        "episode_index": int(episode_index),
                        "seed": self.seed + int(episode_index),
                        "horizon": horizon,
                    }
                    result = runtime.run(
                        agent,
                        pipeline,
                        self.environment,
                        task,
                        session_id=(
                            f"robocasa-{self.split}-{task_name}-"
                            f"{int(episode_index):04d}"
                        ),
                        close_resources=False,
                    )
                    episode = {
                        **result,
                        "task_name": task_name,
                        "task_set": self.task_set,
                        "split": self.split,
                        "episode_index": int(episode_index),
                        "episode_ordinal": ordinal,
                        "seed": task["seed"],
                        "horizon": horizon,
                    }
                    results.append(episode)
                    with episodes_path.open("a", encoding="utf-8") as file:
                        file.write(
                            json.dumps(to_jsonable(episode), ensure_ascii=False) + "\n"
                        )
            resolved["policy_health"] = to_jsonable(agent.healthcheck())
            (self.output_dir / "resolved_config.json").write_text(
                json.dumps(resolved, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        finally:
            try:
                self.environment.close()
            finally:
                agent.close()

        per_task = {}
        for task_name in tasks:
            task_results = [item for item in results if item["task_name"] == task_name]
            per_task[task_name] = {
                "episodes": len(task_results),
                "successes": sum(bool(item["success"]) for item in task_results),
                "success_rate": (
                    sum(bool(item["success"]) for item in task_results)
                    / len(task_results)
                    if task_results
                    else 0.0
                ),
                "action_chunks": sum(
                    int(item.get("action_chunks", 0)) for item in task_results
                ),
                "environment_steps": sum(
                    int(item.get("environment_steps", 0)) for item in task_results
                ),
            }
        count = len(results)
        successes = sum(bool(item["success"]) for item in results)
        summary = {
            "benchmark": "RoboCasa365",
            "task_set": self.task_set,
            "split": self.split,
            "tasks": len(tasks),
            "episodes": count,
            "successes": successes,
            "failures": count - successes,
            "success_rate": successes / count if count else 0.0,
            "macro_average_success_rate": (
                sum(item["success_rate"] for item in per_task.values()) / len(per_task)
                if per_task
                else 0.0
            ),
            "mean_steps": (
                sum(int(item["steps"]) for item in results) / count if count else 0.0
            ),
            "environment_steps": sum(
                int(item.get("environment_steps", 0)) for item in results
            ),
            "action_chunks": sum(int(item.get("action_chunks", 0)) for item in results),
            "invalid_actions": sum(
                int(item.get("invalid_actions", 0)) for item in results
            ),
            "planner_calls": sum(int(item.get("planner_calls", 0)) for item in results),
            "replans": sum(int(item["replans"]) for item in results),
            "latency_seconds": sum(float(item["latency_seconds"]) for item in results),
            "mean_latency_seconds": (
                sum(float(item["latency_seconds"]) for item in results) / count
                if count
                else 0.0
            ),
            "exceptions": sum(
                item["termination_reason"] == "exception" for item in results
            ),
            "termination_reasons": {
                reason: sum(item["termination_reason"] == reason for item in results)
                for reason in sorted(
                    {str(item["termination_reason"]) for item in results}
                )
            },
            "per_task": per_task,
        }
        (self.output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"summary": summary, "episodes": results, "resolved": resolved}

    def _resolve_tasks(self) -> tuple[list[str], list[str]]:
        registered = self.environment.resolve_task_set(self.task_set)
        if self.task_names is None:
            tasks = registered
        else:
            unknown = sorted(set(self.task_names) - set(registered))
            if unknown:
                raise ConfigError(
                    f"Tasks are not in RoboCasa task_set {self.task_set!r}: {unknown}"
                )
            tasks = list(dict.fromkeys(self.task_names))
        if self.max_tasks is not None:
            tasks = tasks[: self.max_tasks]
        if not tasks:
            raise ConfigError("RoboCasa evaluation resolved no tasks")
        return tasks, registered
