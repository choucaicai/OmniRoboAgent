import json
from pathlib import Path
from typing import Any

from omniroboagent.agent_core.agents.base import BaseAgent
from omniroboagent.environments.benchmarks.embodiedbench import EBAlfredEnvironment
from omniroboagent.pipelines.base import Pipeline
from omniroboagent.runtimes.base import Runtime
from omniroboagent.serialization import to_jsonable


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
