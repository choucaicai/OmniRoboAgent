import importlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from omniroboagent.contracts import BaseAgent, Environment, Pipeline, Runtime
from omniroboagent.exceptions import EnvironmentError
from omniroboagent.serialization import to_jsonable


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


class EBAlfredBenchmark:
    def __init__(
        self,
        environment: EBAlfredEnvironment,
        output_dir: str | Path,
    ) -> None:
        self.environment = environment
        self.output_dir = Path(output_dir)

    def run(
        self,
        agent: BaseAgent,
        pipeline: Pipeline,
        runtime: Runtime,
    ) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        episodes_path = self.output_dir / "episodes.jsonl"
        episodes_path.write_text("", encoding="utf-8")
        results: list[dict[str, Any]] = []
        try:
            for position, task in enumerate(self.environment.tasks):
                original_index = (
                    self.environment.selected_indexes[position]
                    if self.environment.selected_indexes
                    else position
                )
                result = runtime.run(
                    agent,
                    pipeline,
                    self.environment,
                    task,
                    session_id=f"eb-alfred-{self.environment.eval_set}-{original_index}",
                    close_resources=False,
                )
                episode = {
                    **result,
                    "eval_set": self.environment.eval_set,
                    "episode_index": original_index,
                    "instruction": (
                        task.get("instruction", "")
                        if isinstance(task, dict)
                        else str(task)
                    ),
                }
                results.append(episode)
                with episodes_path.open("a", encoding="utf-8") as file:
                    file.write(
                        json.dumps(to_jsonable(episode), ensure_ascii=False) + "\n"
                    )
        finally:
            self.environment.close()
            agent.close()

        count = len(results)
        summary = {
            "benchmark": "EB-ALFRED",
            "eval_set": self.environment.eval_set,
            "episodes": count,
            "success_rate": (
                sum(bool(item["success"]) for item in results) / count if count else 0.0
            ),
            "mean_progress": (
                sum(float(item["task_progress"]) for item in results) / count
                if count
                else 0.0
            ),
            "mean_steps": (
                sum(int(item["steps"]) for item in results) / count if count else 0.0
            ),
            "invalid_actions": sum(int(item["invalid_actions"]) for item in results),
            "replans": sum(int(item["replans"]) for item in results),
            "latency_seconds": sum(float(item["latency_seconds"]) for item in results),
            "termination_reasons": {
                reason: sum(item["termination_reason"] == reason for item in results)
                for reason in sorted(
                    {str(item["termination_reason"]) for item in results}
                )
            },
        }
        (self.output_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return {"summary": summary, "episodes": results}
