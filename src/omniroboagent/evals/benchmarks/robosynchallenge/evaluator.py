"""Seeded framework rollouts with persistent, resumable episode records."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from omniroboagent.agent_core.agents.base import BaseAgent
from omniroboagent.pipelines.base import Pipeline
from omniroboagent.runtimes.base import Runtime
from omniroboagent.serialization import to_jsonable

if TYPE_CHECKING:
    from omniroboagent.environments.benchmarks.robosynchallenge import (
        RoboSynChallengeEnvironment,
    )


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            to_jsonable(value, max_sequence_items=sys.maxsize),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def summarize(episodes: list[dict[str, Any]], seeds: list[int]) -> dict[str, Any]:
    by_seed: dict[int, dict[str, Any]] = {}
    for episode in episodes:
        seed = episode["seed"]
        if seed not in seeds or seed in by_seed:
            raise ValueError(f"Unexpected or duplicate episode seed: {seed}")
        if type(episode.get("success")) is not bool:
            raise ValueError(f"Missing authoritative boolean success for seed {seed}")
        if not isinstance(episode.get("termination_reason"), str):
            raise ValueError(f"Missing termination reason for seed {seed}")
        by_seed[seed] = episode
    evaluated = [
        episode for episode in episodes if episode["termination_reason"] != "exception"
    ]
    successes = sum(episode["success"] for episode in evaluated)
    return {
        "requested_episodes": len(seeds),
        "attempted_episodes": len(episodes),
        "evaluated_episodes": len(evaluated),
        "execution_errors": len(episodes) - len(evaluated),
        "successes": successes,
        "success_rate": successes / len(evaluated) if evaluated else None,
        "complete": len(evaluated) == len(seeds),
        "missing_seeds": sorted(set(seeds) - by_seed.keys()),
        "error_seeds": [
            episode["seed"]
            for episode in episodes
            if episode["termination_reason"] == "exception"
        ],
        "mean_environment_steps": (
            sum(episode["environment_steps"] for episode in evaluated) / len(evaluated)
            if evaluated
            else None
        ),
        "mean_latency_seconds": (
            sum(episode["latency_seconds"] for episode in evaluated) / len(evaluated)
            if evaluated
            else None
        ),
    }


class RoboSynChallengeEvaluator:
    def __init__(
        self,
        environment: "RoboSynChallengeEnvironment",
        output_dir: str | Path,
        task_name: str,
        seeds: list[int],
        *,
        setting: str = "random",
        resume: bool = False,
        run_metadata: dict[str, Any] | None = None,
    ) -> None:
        if not seeds or len(set(seeds)) != len(seeds):
            raise ValueError("Provide at least one unique seed")
        if any(type(seed) is not int or not 0 <= seed < 2**31 for seed in seeds):
            raise ValueError("Seeds must be integers in [0, 2**31)")
        self.environment = environment
        self.output_dir = Path(output_dir).resolve()
        self.task_name = task_name
        self.seeds = list(seeds)
        self.setting = setting
        self.resume = resume
        self.run_metadata = run_metadata or {}

    def run(
        self, agent: BaseAgent, pipeline: Pipeline, runtime: Runtime
    ) -> dict[str, Any]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            **self.environment.metadata(),
            **self.run_metadata,
            "benchmark": "RoboSynChallenge",
            "task": self.task_name,
            "setting": self.setting,
            "seeds": self.seeds,
            "seed_protocol": "explicit_unfiltered",
            "expert_feasibility_filter": False,
            "protocol_scope": "Custom framework evaluation; not paper reproduction",
            "agent_class": f"{type(agent).__module__}.{type(agent).__name__}",
            "pipeline_class": f"{type(pipeline).__module__}.{type(pipeline).__name__}",
            "components": {
                name: f"{type(component).__module__}.{type(component).__name__}"
                for name, component in (
                    ("planner", agent.planner),
                    ("verifier", agent.verifier),
                    ("memory", agent.memory),
                    ("skill_backend", agent.skill_backend),
                )
            },
        }
        metadata["source_commits"] = {}
        for name in ("root", "embodichain_root"):
            if metadata.get(name):
                revision = subprocess.run(
                    ["git", "-C", metadata[name], "rev-parse", "HEAD"],
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
                metadata["source_commits"][name] = revision
        metadata["task_config_sha256"] = {}
        resolved_configs = {}
        if metadata.get("root"):
            config_dir = Path(metadata["root"]) / "configs" / self.task_name
            action_path = config_dir / "action_config.json"
            if not action_path.is_file():
                action_path = config_dir / self.setting / "action_config.json"
            for name, path in (
                ("gym_config", config_dir / self.setting / "gym_config.json"),
                ("action_config", action_path),
            ):
                if path.is_file():
                    content = path.read_bytes()
                    metadata["task_config_sha256"][name] = hashlib.sha256(
                        content
                    ).hexdigest()
                    resolved_configs[name] = json.loads(content)
        project_root = Path(__file__).resolve().parents[5]
        for name, arguments in (
            ("framework_commit", ["rev-parse", "HEAD"]),
            ("framework_dirty", ["status", "--porcelain"]),
        ):
            value = subprocess.run(
                ["git", "-C", str(project_root), *arguments],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            metadata[name] = bool(value) if name == "framework_dirty" else value
        metadata_path = self.output_dir / "metadata.json"
        if metadata_path.exists():
            if not self.resume:
                raise FileExistsError(
                    f"Use --resume or a fresh output: {self.output_dir}"
                )
            previous = json.loads(metadata_path.read_text(encoding="utf-8"))
            if self.seeds == list(range(100)) and previous.get("seeds") == to_jsonable(
                self.seeds
            ):
                # The initial runner used trace summarization for persistent metadata.
                previous["seeds"] = self.seeds
            changed = [
                key
                for key in metadata
                if key != "framework_dirty" and previous.get(key) != metadata[key]
            ]
            if changed:
                raise ValueError(f"Resume configuration changed: {', '.join(changed)}")
        write_json(metadata_path, metadata)
        for name, config in resolved_configs.items():
            write_json(self.output_dir / f"resolved_{name}.json", config)
        latest: dict[int, dict[str, Any]] = {}
        attempts: dict[int, int] = {}
        prefix = f"robosyn-{self.task_name}-{self.setting}-seed-"
        for directory in sorted(self.output_dir.glob("robosyn-*")):
            if not directory.is_dir() or not directory.name.startswith(prefix):
                raise ValueError(f"Foreign episode in output: {directory}")
            seed_text, separator, attempt_text = directory.name[
                len(prefix) :
            ].partition("-attempt-")
            if (
                not separator
                or not seed_text.isdecimal()
                or not attempt_text.isdecimal()
            ):
                raise ValueError(f"Invalid episode directory: {directory}")
            seed, attempt = int(seed_text), int(attempt_text)
            if seed not in self.seeds or attempt <= 0:
                raise ValueError(f"Foreign episode in output: {directory}")
            attempts[seed] = max(attempts.get(seed, 0), attempt)
            path = directory / "episode.json"
            if not path.exists():
                continue
            episode = json.loads(path.read_text(encoding="utf-8"))
            if (
                episode.get("task") != self.task_name
                or episode.get("setting") != self.setting
                or episode.get("seed") != seed
                or episode.get("attempt") != attempt
            ):
                raise ValueError(f"Foreign episode in output: {path}")
            if attempt > latest.get(seed, {}).get("attempt", 0):
                latest[seed] = episode

        def save_progress() -> dict[str, Any]:
            episodes = [latest[seed] for seed in self.seeds if seed in latest]
            temporary = self.output_dir / "episodes.jsonl.tmp"
            temporary.write_text(
                "".join(json.dumps(to_jsonable(row)) + "\n" for row in episodes),
                encoding="utf-8",
            )
            temporary.replace(self.output_dir / "episodes.jsonl")
            summary = {**metadata, **summarize(episodes, self.seeds)}
            write_json(self.output_dir / "summary.json", summary)
            return summary

        summary = save_progress()
        try:
            for index, seed in enumerate(self.seeds):
                if seed in latest and latest[seed]["termination_reason"] != "exception":
                    continue
                attempt = attempts.get(seed, 0) + 1
                session_id = (
                    f"robosyn-{self.task_name}-{self.setting}-seed-{seed}"
                    f"-attempt-{attempt}"
                )
                result = runtime.run(
                    agent,
                    pipeline,
                    self.environment,
                    {
                        "name": self.task_name,
                        "setting": self.setting,
                        "seed": seed,
                        "episode_index": index,
                    },
                    session_id=session_id,
                    close_resources=False,
                )
                episode = {
                    **result,
                    **self.environment.episode_metadata(),
                    "task": self.task_name,
                    "setting": self.setting,
                    "seed": seed,
                    "attempt": attempt,
                    "seed_protocol": "explicit_unfiltered",
                    "reset_protocol": "upstream.prepare_episode_reset + native reset",
                    "termination_reason": result["termination_reason"],
                    "success": bool(result["success"]),
                }
                if result["termination_reason"] == "exception":
                    episode["success"] = False
                elif "authoritative_success" in episode:
                    episode["success"] = bool(episode["authoritative_success"])
                episode.setdefault("environment_steps", 0)
                write_json(self.output_dir / session_id / "episode.json", episode)
                latest[seed] = episode
                attempts[seed] = attempt
                summary = save_progress()
                print(
                    json.dumps(
                        {
                            "task": self.task_name,
                            "seed": seed,
                            "success": episode["success"],
                            "termination_reason": episode["termination_reason"],
                            "environment_steps": episode["environment_steps"],
                            "evaluated_episodes": summary["evaluated_episodes"],
                        }
                    ),
                    flush=True,
                )
                if result["termination_reason"] == "exception":
                    break
            return summary
        finally:
            try:
                agent.close()
            finally:
                self.environment.close()
