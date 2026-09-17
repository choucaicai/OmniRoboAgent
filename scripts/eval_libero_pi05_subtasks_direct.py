#!/usr/bin/env python3
"""Direct LIBERO subtask execution with a fixed prompt (no Qwen/planner).

This is deliberately a VLA-only probe: each episode is reset to an official
LIBERO initial state, the prompt is taken from the corresponding expert task,
and the same prompt is sent to pi0.5 for every receding-horizon chunk.  The
only success signal is the environment's ``check_success()``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from omniroboagent.backends.skills.pi05_libero import LiberoPi05PolicyBackend
from omniroboagent.environments.benchmarks.libero import LiberoEnvironment

GLOBAL_TO_SUITE = (
    (0, 10, "libero_10"),
    (10, 20, "libero_goal"),
    (20, 30, "libero_object"),
    (30, 40, "libero_spatial"),
)


def suite_task(global_task_index: int) -> tuple[str, int]:
    for start, end, suite in GLOBAL_TO_SUITE:
        if start <= global_task_index < end:
            return suite, global_task_index - start
    raise ValueError(f"global task index must be in [0, 39], got {global_task_index}")


def load_prompts(dataset_root: Path) -> dict[int, str]:
    table = pq.read_table(dataset_root / "meta" / "tasks.parquet")
    rows = table.to_pylist()
    return {
        int(row["task_index"]): str(row["task"])
        for row in rows
        if int(row["task_index"]) < 40
    }


def resolve_task_by_prompt(
    env: LiberoEnvironment, prompt: str
) -> tuple[str, int, dict[str, Any]]:
    normalized = " ".join(prompt.lower().split())
    candidates: list[tuple[str, int, dict[str, Any]]] = []
    for suite in ("libero_10", "libero_goal", "libero_object", "libero_spatial"):
        for spec in env.resolve_suite(suite):
            if " ".join(str(spec["instruction"]).lower().split()) == normalized:
                candidates.append((suite, int(spec["task_id"]), spec))
    if len(candidates) != 1:
        raise ValueError(
            f"could not uniquely map dataset task prompt to LIBERO: {prompt!r}; "
            f"matches={[(x[0], x[1]) for x in candidates]}"
        )
    return candidates[0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--checkpoint",
        required=True,
        help="LeRobot full model directory or PEFT pretrained_model directory.",
    )
    parser.add_argument(
        "--task-indices",
        nargs="+",
        type=int,
        default=None,
        help="Original LIBERO task indices in the 0..39 dataset order.",
    )
    parser.add_argument(
        "--all-tasks",
        action="store_true",
        help="Evaluate all 40 official LIBERO tasks (four suites x ten tasks).",
    )
    parser.add_argument("--episode-index", type=int, default=0)
    parser.add_argument(
        "--episodes-per-task",
        type=int,
        default=1,
        help="Number of official initial states per task. Standard LIBERO uses 50.",
    )
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--max-chunks",
        type=int,
        default=0,
        help="Maximum chunks; 0 uses the suite horizon divided by execute-steps.",
    )
    parser.add_argument("--chunk-horizon", type=int, default=10)
    parser.add_argument("--execute-steps", type=int, default=10)
    parser.add_argument(
        "--config",
        default=os.environ.get("CLAWVLA_LIBERO_CONFIG"),
    )
    parser.add_argument(
        "--dataset-root",
        default=os.environ.get("LIBERO_SUBTASK_DATASET"),
    )
    parser.add_argument(
        "--tokenizer",
        default=os.environ.get("PALIGEMMA_TOKENIZER"),
    )
    parser.add_argument(
        "--output",
        required=True,
    )
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.config:
        raise ValueError("--config or CLAWVLA_LIBERO_CONFIG is required")
    if not args.dataset_root:
        raise ValueError("--dataset-root or LIBERO_SUBTASK_DATASET is required")
    if not args.tokenizer:
        raise ValueError("--tokenizer or PALIGEMMA_TOKENIZER is required")
    if args.all_tasks:
        task_indices = list(range(40))
    elif args.task_indices:
        task_indices = list(dict.fromkeys(args.task_indices))
    else:
        raise ValueError("provide --task-indices or --all-tasks")
    if any(index < 0 or index >= 40 for index in task_indices):
        raise ValueError("task indices must be in [0, 39]")
    if args.episodes_per_task <= 0:
        raise ValueError("episodes-per-task must be positive")
    if args.max_chunks < 0 or args.chunk_horizon <= 0 or args.execute_steps <= 0:
        raise ValueError("chunk and horizon values must be non-negative/positive")

    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    prompts = load_prompts(Path(args.dataset_root).expanduser().resolve())
    artifact_dir = output / "artifacts"
    env = LiberoEnvironment(
        config_path=args.config,
        artifact_dir=artifact_dir,
        available_skills=["subtask"],
    )
    backend = LiberoPi05PolicyBackend(
        config_path=args.config,
        pretrained_path=args.checkpoint,
        device="cuda",
        horizon=args.chunk_horizon,
        tokenizer_name=args.tokenizer,
    )

    results: list[dict[str, Any]] = []
    episodes_path = output / "episodes.jsonl"
    completed: set[str] = set()
    if args.resume and episodes_path.is_file():
        for line in episodes_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                completed.add(f"{row['global_task_index']}:{row['episode_index']}")
                results.append(row)
    all_specs: dict[str, tuple[str, int, dict[str, Any]]] = {}
    for suite in ("libero_10", "libero_goal", "libero_object", "libero_spatial"):
        for spec in env.resolve_suite(suite):
            key = " ".join(str(spec["instruction"]).lower().split())
            all_specs[key] = (suite, int(spec["task_id"]), spec)
    try:
        total = len(task_indices) * args.episodes_per_task
        case_number = len(results)
        with episodes_path.open("a", encoding="utf-8") as episodes_file:
            for global_index in task_indices:
                prompt = prompts[global_index]
                key = " ".join(prompt.lower().split())
                if key not in all_specs:
                    raise ValueError(f"no official LIBERO task matches {prompt!r}")
                suite, task_id, spec = all_specs[key]
                max_chunks = args.max_chunks or math.ceil(
                    {
                        "libero_10": 520,
                        "libero_goal": 300,
                        "libero_object": 280,
                        "libero_spatial": 220,
                    }[suite]
                    / args.execute_steps
                )
                for episode_index in range(
                    args.episode_index,
                    args.episode_index + args.episodes_per_task,
                ):
                    case_key = f"{global_index}:{episode_index}"
                    if case_key in completed:
                        continue
                    case_number += 1
                    print(
                        f"[{case_number}/{total}] {suite}[{task_id}] "
                        f"episode={episode_index} prompt={prompt!r}",
                        flush=True,
                    )
                    task = {
                        "suite": suite,
                        "task_id": task_id,
                        "name": spec["name"],
                        "instruction": spec["instruction"],
                        "init_state_count": spec["init_state_count"],
                        "episode_index": episode_index,
                        "seed": args.seed,
                        "horizon": 1000,
                    }
                    start = time.time()
                    error: str | None = None
                    chunks = 0
                    environment_steps = 0
                    success = False
                    try:
                        observation = env.reset(task)
                        for chunk_index in range(1, max_chunks + 1):
                            chunks = chunk_index
                            action = backend.predict(
                                {
                                    "skill": "subtask",
                                    "subtask": prompt,
                                    "observation": observation,
                                    "task": task,
                                }
                            )
                            execution = env.execute(
                                action, execute_steps=args.execute_steps
                            )
                            observation = execution["observation"]
                            environment_steps += int(execution.get("executed_steps", 0))
                            success = bool(execution.get("task_success", False))
                            if success or bool(execution.get("done", False)):
                                break
                    except Exception as exc:  # record one case and continue with queue
                        error = f"{type(exc).__name__}: {exc}"
                    result = {
                        "global_task_index": global_index,
                        "suite": suite,
                        "task_id": task_id,
                        "task_name": spec["name"],
                        "instruction": spec["instruction"],
                        "subtask_prompt": prompt,
                        "episode_index": episode_index,
                        "seed": args.seed,
                        "success": success,
                        "chunks": chunks,
                        "max_chunks": max_chunks,
                        "environment_steps": environment_steps,
                        "elapsed_seconds": time.time() - start,
                        "error": error,
                        "success_source": "LIBERO env.check_success()",
                        "planner": "none (fixed official task prompt)",
                    }
                    results.append(result)
                    episodes_file.write(json.dumps(result, ensure_ascii=False) + "\n")
                    episodes_file.flush()
                    print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        try:
            env.close()
        finally:
            backend.close()

    summary = {
        "benchmark": "LIBERO",
        "mode": "direct_subtask_vla_only",
        "checkpoint": str(Path(args.checkpoint).expanduser().resolve()),
        "episodes": len(results),
        "successes": sum(bool(row["success"]) for row in results),
        "success_rate": (
            sum(bool(row["success"]) for row in results) / len(results)
            if results
            else 0.0
        ),
        "results": results,
    }
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
