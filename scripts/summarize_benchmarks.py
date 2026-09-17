#!/usr/bin/env python3
"""Create compact benchmark tables from ignored raw evaluation outputs."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIBERO_ROOT = (
    PROJECT_ROOT / "runs/eval/libero_pi05_subtasks_direct_all50_20260915"
)
DEFAULT_ROBOTWIN_ROOT = PROJECT_ROOT / "runs/eval"
DEFAULT_TASKS = PROJECT_ROOT / "configs/eval/robotwin_tasks.txt"
DEFAULT_OUTPUT = PROJECT_ROOT / "results/benchmarks"
ROBOTWIN_SUFFIX = "_heldout_qwen35_omni_shared_pi05_20260914"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--libero-root", type=Path, default=DEFAULT_LIBERO_ROOT)
    parser.add_argument("--robotwin-root", type=Path, default=DEFAULT_ROBOTWIN_ROOT)
    parser.add_argument("--robotwin-tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def aggregate_libero(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    summaries = [root / "summary.json"] + sorted(root.glob("*/summary.json"))
    results: list[dict[str, Any]] = []
    for path in summaries:
        if not path.is_file():
            continue
        payload = load_json(path)
        rows = payload.get("results")
        if not isinstance(rows, list):
            raise ValueError(f"Missing LIBERO results list: {path}")
        results.extend(rows)

    by_episode: dict[tuple[int, int], dict[str, Any]] = {}
    for row in results:
        key = (int(row["global_task_index"]), int(row["episode_index"]))
        if key in by_episode:
            raise ValueError(f"Duplicate LIBERO episode: {key}")
        by_episode[key] = row
    results = list(by_episode.values())

    task_rows: list[dict[str, Any]] = []
    suites: dict[str, dict[str, int]] = {}
    for task_index in sorted({int(row["global_task_index"]) for row in results}):
        selected = [
            row for row in results if int(row["global_task_index"]) == task_index
        ]
        successes = sum(bool(row["success"]) for row in selected)
        task = {
            "task_index": task_index,
            "suite": str(selected[0]["suite"]),
            "task_name": str(selected[0]["task_name"]),
            "episodes": len(selected),
            "successes": successes,
            "accuracy_percent": round(100 * successes / len(selected), 1),
        }
        task_rows.append(task)
        suite = suites.setdefault(task["suite"], {"episodes": 0, "successes": 0})
        suite["episodes"] += len(selected)
        suite["successes"] += successes

    suite_rows = []
    for name in ("libero_spatial", "libero_object", "libero_goal", "libero_10"):
        counts = suites.get(name, {"episodes": 0, "successes": 0})
        episodes = counts["episodes"]
        suite_rows.append(
            {
                "suite": name,
                **counts,
                "accuracy_percent": (
                    round(100 * counts["successes"] / episodes, 1) if episodes else None
                ),
            }
        )
    episodes = len(results)
    successes = sum(bool(row["success"]) for row in results)
    summary = {
        "benchmark": "LIBERO",
        "protocol": "four official suites; 50 fixed initial states per task",
        "success_definition": "LIBERO env.check_success()",
        "checkpoint_id": "libero_pi05_subtask_lora",
        "tasks": len(task_rows),
        "episodes": episodes,
        "successes": successes,
        "accuracy_percent": round(100 * successes / episodes, 2),
        "suites": suite_rows,
    }
    return summary, task_rows


def robotwin_summary_path(root: Path, task: str) -> Path | None:
    candidates = [
        root / f"{task}{ROBOTWIN_SUFFIX}" / "summary.json",
        root / f"{task}_heldout30_qwen35_omni_shared_pi05_20260914/summary.json",
    ]
    return next((path for path in candidates if path.is_file()), None)


def aggregate_robotwin(
    root: Path, task_file: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    tasks = [
        line.strip()
        for line in task_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(tasks) != 50 or len(set(tasks)) != 50:
        raise ValueError("RoboTwin task manifest must contain 50 unique tasks")

    rows: list[dict[str, Any]] = []
    for task in tasks:
        path = robotwin_summary_path(root, task)
        payload = load_json(path) if path is not None else {}
        completed = int(payload.get("completed", 0))
        target = int(payload.get("target", 30))
        successes = int(payload.get("successes", 0))
        if completed >= target and target == 30:
            status = "complete"
        elif completed:
            status = "running"
        else:
            status = "pending"
        rows.append(
            {
                "task": task,
                "status": status,
                "target": target,
                "completed": completed,
                "successes": successes,
                "accuracy_percent": (
                    round(100 * successes / completed, 1) if completed else None
                ),
            }
        )

    complete = [row for row in rows if row["status"] == "complete"]
    episodes = sum(int(row["completed"]) for row in complete)
    successes = sum(int(row["successes"]) for row in complete)
    summary = {
        "benchmark": "RoboTwin 2.0",
        "protocol": "demo_clean; 30 held-out valid seeds per task",
        "success_definition": "RoboTwin task_env.check_success()",
        "total_tasks": len(rows),
        "complete_tasks": len(complete),
        "running_tasks": sum(row["status"] == "running" for row in rows),
        "pending_tasks": sum(row["status"] == "pending" for row in rows),
        "completed_task_episodes": episodes,
        "completed_task_successes": successes,
        "completed_task_accuracy_percent": (
            round(100 * successes / episodes, 2) if episodes else None
        ),
        "is_final": len(complete) == len(rows),
    }
    return summary, rows


def markdown(
    generated_at: str,
    libero: dict[str, Any],
    robotwin: dict[str, Any],
    robotwin_rows: list[dict[str, Any]],
) -> str:
    lines = [
        "# Benchmark results",
        "",
        f"> Generated from per-episode outputs at `{generated_at}`.",
        "> Raw logs, observations, traces, datasets, optimizer states, and large",
        "> policy checkpoints are not tracked. The inference-only LIBERO Qwen",
        "> planner LoRA is packaged with Git LFS. See `checkpoints/manifest.json`.",
        "",
        "## LIBERO",
        "",
        f"Overall: **{libero['successes']}/{libero['episodes']} "
        f"({libero['accuracy_percent']:.2f}%)** across {libero['tasks']} tasks.",
        "Success is counted only from `env.check_success()`.",
        "",
        "| Suite | Successes / Episodes | Accuracy |",
        "| --- | ---: | ---: |",
    ]
    for row in libero["suites"]:
        lines.append(
            f"| {row['suite']} | {row['successes']} / {row['episodes']} | "
            f"{row['accuracy_percent']:.1f}% |"
        )
    lines.extend(
        [
            "",
            "Per-task values are in `libero_per_task.csv`.",
            "",
            "## RoboTwin 2.0",
            "",
            f"Completed snapshot: **{robotwin['complete_tasks']}/"
            f"{robotwin['total_tasks']} tasks** and "
            f"**{robotwin['completed_task_successes']}/"
            f"{robotwin['completed_task_episodes']} "
            f"({robotwin['completed_task_accuracy_percent']:.2f}%)**.",
            "Only tasks with all 30 held-out episodes contribute to this number; "
            "running and pending tasks are excluded.",
            "Success is counted only from `task_env.check_success()`.",
            "",
            "| Task | Status | Successes / Episodes | Accuracy |",
            "| --- | --- | ---: | ---: |",
        ]
    )
    for row in robotwin_rows:
        accuracy = (
            f"{row['accuracy_percent']:.1f}%"
            if row["accuracy_percent"] is not None
            else "—"
        )
        lines.append(
            f"| {row['task']} | {row['status']} | "
            f"{row['successes']} / {row['completed']} | {accuracy} |"
        )
    lines.append("")
    if robotwin["is_final"]:
        lines.append(
            "All 50 task queues are complete, so this is the final snapshot for "
            "the recorded protocol and checkpoints."
        )
    else:
        lines.append(
            "This RoboTwin table is a progress snapshot, not a final 50-task "
            "score, until `is_final` becomes true in `summary.json`."
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    libero, libero_rows = aggregate_libero(args.libero_root.resolve())
    robotwin, robotwin_rows = aggregate_robotwin(
        args.robotwin_root.resolve(), args.robotwin_tasks.resolve()
    )
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    write_csv(
        output / "libero_per_task.csv",
        libero_rows,
        [
            "task_index",
            "suite",
            "task_name",
            "episodes",
            "successes",
            "accuracy_percent",
        ],
    )
    write_csv(
        output / "robotwin_per_task.csv",
        robotwin_rows,
        [
            "task",
            "status",
            "target",
            "completed",
            "successes",
            "accuracy_percent",
        ],
    )
    payload = {
        "generated_at": generated_at,
        "libero": libero,
        "robotwin": robotwin,
    }
    (output / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output / "README.md").write_text(
        markdown(generated_at, libero, robotwin, robotwin_rows), encoding="utf-8"
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
