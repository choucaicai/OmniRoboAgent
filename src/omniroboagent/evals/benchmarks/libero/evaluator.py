import json
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from omniroboagent.agent_core.agents.base import BaseAgent
from omniroboagent.environments.benchmarks.libero import LiberoEnvironment
from omniroboagent.exceptions import ConfigError
from omniroboagent.pipelines.base import Pipeline
from omniroboagent.runtimes.base import Runtime
from omniroboagent.serialization import to_jsonable


def _class_path(value: Any) -> str | None:
    if value is None:
        return None
    cls = type(value)
    return f"{cls.__module__}.{cls.__qualname__}"


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


class LiberoEvaluator:
    """Run an official LIBERO suite over its fixed initial-state episodes."""

    def __init__(
        self,
        environment: LiberoEnvironment,
        suite: str,
        output_dir: str | Path,
        task_ids: list[int] | None = None,
        max_tasks: int | None = None,
        episodes_per_task: int = 50,
        episode_indices: list[int] | None = None,
        seed: int = 7,
    ) -> None:
        if not isinstance(suite, str) or not suite:
            raise ConfigError("LIBERO suite must be a non-empty string")
        if task_ids is not None and (
            any(type(task_id) is not int or task_id < 0 for task_id in task_ids)
            or len(set(task_ids)) != len(task_ids)
        ):
            raise ConfigError("task_ids must be unique non-negative integers")
        if max_tasks is not None and max_tasks <= 0:
            raise ConfigError("max_tasks must be positive")
        if episodes_per_task <= 0:
            raise ConfigError("episodes_per_task must be positive")
        if episode_indices is not None and len(episode_indices) < episodes_per_task:
            raise ConfigError(
                "episode_indices must contain at least episodes_per_task values"
            )
        if episode_indices is not None and (
            any(type(index) is not int or index < 0 for index in episode_indices)
            or len(set(episode_indices)) != len(episode_indices)
        ):
            raise ConfigError("episode_indices must be unique non-negative integers")
        if type(seed) is not int:
            raise ConfigError("seed must be an integer")
        self.environment = environment
        self.suite = suite
        self.output_dir = Path(output_dir)
        self.task_ids = task_ids
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
        registered = self.environment.resolve_suite(self.suite)
        tasks = self._resolve_tasks(registered)
        episode_indices = self.episode_indices or list(range(self.episodes_per_task))
        for task in tasks:
            if any(
                index >= int(task["init_state_count"])
                for index in episode_indices[: self.episodes_per_task]
            ):
                raise ConfigError(
                    "Requested episode index exceeds the official initial states for "
                    f"LIBERO task {task['task_id']}"
                )

        self.output_dir.mkdir(parents=True, exist_ok=True)
        episodes_path = self.output_dir / "episodes.jsonl"
        episodes_path.write_text("", encoding="utf-8")
        results: list[dict[str, Any]] = []
        resolved = self._resolved(agent, pipeline, runtime, registered, tasks)
        (self.output_dir / "resolved_config.json").write_text(
            json.dumps(resolved, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        try:
            horizon = self.environment.get_suite_horizon(self.suite)
            for task in tasks:
                for ordinal, episode_index in enumerate(
                    episode_indices[: self.episodes_per_task]
                ):
                    episode_task = {
                        **task,
                        "suite": self.suite,
                        "episode_index": episode_index,
                        "seed": self.seed,
                        "horizon": horizon,
                    }
                    result = runtime.run(
                        agent,
                        pipeline,
                        self.environment,
                        episode_task,
                        session_id=(
                            f"libero-{self.suite}-{task['task_id']:02d}-"
                            f"{episode_index:02d}"
                        ),
                        close_resources=False,
                    )
                    episode = {
                        **result,
                        "benchmark": "LIBERO",
                        "suite": self.suite,
                        "task_id": task["task_id"],
                        "task_name": task["name"],
                        "instruction": task["instruction"],
                        "episode_index": episode_index,
                        "episode_ordinal": ordinal,
                        "seed": self.seed,
                        "horizon": horizon,
                        "success_source": "LIBERO env.check_success()",
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

        per_task: dict[str, dict[str, Any]] = {}
        for task in tasks:
            task_results = [
                item for item in results if item["task_id"] == task["task_id"]
            ]
            successes = sum(bool(item["success"]) for item in task_results)
            per_task[str(task["task_id"])] = {
                "task_name": task["name"],
                "instruction": task["instruction"],
                "episodes": len(task_results),
                "successes": successes,
                "success_rate": successes / len(task_results) if task_results else 0.0,
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
            "benchmark": "LIBERO",
            "suite": self.suite,
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
            "environment_steps": sum(
                int(item.get("environment_steps", 0)) for item in results
            ),
            "action_chunks": sum(int(item.get("action_chunks", 0)) for item in results),
            "invalid_actions": sum(
                int(item.get("invalid_actions", 0)) for item in results
            ),
            "planner_calls": sum(int(item.get("planner_calls", 0)) for item in results),
            "replans": sum(int(item.get("replans", 0)) for item in results),
            "latency_seconds": sum(
                float(item.get("latency_seconds", 0.0)) for item in results
            ),
            "exceptions": sum(
                item.get("termination_reason") == "exception" for item in results
            ),
            "termination_reasons": {
                reason: sum(
                    item.get("termination_reason") == reason for item in results
                )
                for reason in sorted(
                    {str(item.get("termination_reason")) for item in results}
                )
            },
            "per_task": per_task,
        }
        (self.output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"summary": summary, "episodes": results, "resolved": resolved}

    def _resolve_tasks(self, registered: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.task_ids is None:
            tasks = list(registered)
        else:
            by_id = {int(task["task_id"]): task for task in registered}
            unknown = [task_id for task_id in self.task_ids if task_id not in by_id]
            if unknown:
                raise ConfigError(
                    f"Task IDs are not in LIBERO suite {self.suite!r}: {unknown}"
                )
            tasks = [by_id[task_id] for task_id in self.task_ids]
        if self.max_tasks is not None:
            tasks = tasks[: self.max_tasks]
        if not tasks:
            raise ConfigError("LIBERO evaluation resolved no tasks")
        return tasks

    def _resolved(
        self,
        agent: BaseAgent,
        pipeline: Pipeline,
        runtime: Runtime,
        registered: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        project_root = Path(__file__).resolve().parents[5]
        try:
            commit = subprocess.run(
                ["git", "-C", str(project_root), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            commit = None
        return {
            "benchmark": "LIBERO",
            "suite": self.suite,
            "suite_size": len(registered),
            "task_ids": [task["task_id"] for task in tasks],
            "task_names": [task["name"] for task in tasks],
            "episodes_per_task": self.episodes_per_task,
            "episode_indices": (
                self.episode_indices or list(range(self.episodes_per_task))
            )[: self.episodes_per_task],
            "seed": self.seed,
            "episode_index_semantics": "official_fixed_init_state_index",
            "success_source": "LIBERO env.check_success()",
            "libero": self.environment.metadata(),
            "omniroboagent": {
                "commit": commit,
                "version": _package_version("omniroboagent"),
                "python": sys.version.split()[0],
                "numpy": _package_version("numpy"),
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
            },
            "runtime": {
                "max_steps": getattr(runtime, "max_steps", None),
                "timeout_seconds": getattr(runtime, "timeout_seconds", None),
            },
            "policy_health": to_jsonable(agent.healthcheck()),
        }
