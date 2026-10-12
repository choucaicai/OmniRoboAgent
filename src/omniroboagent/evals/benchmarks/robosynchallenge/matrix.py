"""Independent sequential GPU queues and artifact-based matrix aggregation."""

import json
import subprocess
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
from threading import Lock
from typing import Any

from omniroboagent.evals.benchmarks.robosynchallenge.evaluator import write_json
from omniroboagent.serialization import to_jsonable


def group_tasks(
    tasks: list[dict[str, Any]], queue_count: int
) -> list[list[dict[str, Any]]]:
    if queue_count <= 0:
        raise ValueError("queue_count must be positive")
    return [tasks[index::queue_count] for index in range(queue_count)]


def task_command(
    command: list[str],
    manifest: dict[str, Any],
    task: dict[str, Any],
    output_dir: Path,
    *,
    resume: bool,
    gpu: int | None,
) -> list[str]:
    args = [
        *command,
        "--task",
        task["name"],
        "--checkpoint",
        task["checkpoint_path"],
        "--policy",
        manifest.get("policy", "act"),
        "--setting",
        manifest.get("setting", "random"),
        "--output",
        str(output_dir / task["name"]),
        "--seeds",
        *map(str, manifest.get("seeds", list(range(100)))),
    ]
    if task.get("checkpoint_revision"):
        args.extend(["--checkpoint-revision", task["checkpoint_revision"]])
    agent_config = task.get("agent_config", manifest.get("agent_config"))
    if agent_config:
        args.extend(["--agent-config", agent_config])
    if resume:
        args.append("--resume")
    if gpu is not None:
        args.extend(["--gpu", str(gpu), "--device", f"cuda:{gpu}"])
    return args


def summarize_matrix(
    manifest: dict[str, Any],
    output_dir: Path,
    process_returncodes: dict[str, int],
) -> dict[str, Any]:
    tasks = manifest["tasks"]
    seeds = manifest.get("seeds", list(range(100)))
    rows: list[dict[str, Any]] = []
    for task in tasks:
        name = task["name"]
        path = output_dir / name / "summary.json"
        row = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.exists()
            else {
                "task": name,
                "seeds": seeds,
                "requested_episodes": len(seeds),
                "attempted_episodes": 0,
                "evaluated_episodes": 0,
                "execution_errors": 0,
                "successes": 0,
                "complete": False,
                "error": "Task process has not produced a summary",
            }
        )
        if seeds == list(range(100)) and row.get("seeds") == to_jsonable(seeds):
            row["seeds"] = seeds
        if row.get("task") != name or row.get("seeds", seeds) != seeds:
            raise ValueError(f"Task summary does not match manifest: {path}")
        requested = row["requested_episodes"]
        attempted = row["attempted_episodes"]
        evaluated = row["evaluated_episodes"]
        if (
            requested != len(seeds)
            or not 0 <= evaluated <= attempted <= requested
            or not 0 <= row["successes"] <= evaluated
            or row["execution_errors"] != attempted - evaluated
        ):
            raise ValueError(f"Invalid task coverage in summary: {path}")
        row["process_returncode"] = process_returncodes.get(name)
        row["complete"] = bool(
            row["complete"]
            and evaluated == requested
            and row["execution_errors"] == 0
            and process_returncodes.get(name) == 0
        )
        rows.append(row)
    evaluated = sum(row["evaluated_episodes"] for row in rows)
    successes = sum(row["successes"] for row in rows)
    return {
        "benchmark": "RoboSynChallenge",
        "policy": manifest.get("policy", "act"),
        "setting": manifest.get("setting", "random"),
        "seed_protocol": "explicit_unfiltered",
        "requested_tasks": len(tasks),
        "attempted_tasks": sum(
            row["attempted_episodes"] > 0 or row["process_returncode"] is not None
            for row in rows
        ),
        "requested_episodes": len(tasks) * len(seeds),
        "attempted_episodes": sum(row["attempted_episodes"] for row in rows),
        "evaluated_episodes": evaluated,
        "execution_errors": sum(row["execution_errors"] for row in rows),
        "process_errors": sum(code != 0 for code in process_returncodes.values()),
        "successes": successes,
        "success_rate": successes / evaluated if evaluated else None,
        "complete": all(row["complete"] for row in rows),
        "pending_tasks": [
            row["task"] for row in rows if row["process_returncode"] is None
        ],
        "tasks": rows,
    }


def run_matrix(
    manifest_path: Path,
    output_dir: Path,
    command: list[str],
    *,
    resume: bool = False,
    matrix_gpus: list[int] | None = None,
    matrix_scheduling: str = "fixed",
) -> dict[str, Any]:
    if matrix_scheduling not in {"fixed", "dynamic"}:
        raise ValueError("matrix_scheduling must be 'fixed' or 'dynamic'")
    if matrix_scheduling == "dynamic" and matrix_gpus is None:
        raise ValueError("Dynamic scheduling requires explicit matrix_gpus")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tasks = manifest["tasks"]
    if not tasks or len({task["name"] for task in tasks}) != len(tasks):
        raise ValueError("Matrix must contain unique task names")
    if any(
        not isinstance(task["name"], str)
        or not task["name"]
        or Path(task["name"]).name != task["name"]
        or task["name"] in {".", ".."}
        for task in tasks
    ):
        raise ValueError("Task names must be single directory names")
    seeds = manifest.get("seeds", list(range(100)))
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("Matrix must contain unique seeds")
    if any(type(seed) is not int or not 0 <= seed < 2**31 for seed in seeds):
        raise ValueError("Seeds must be integers in [0, 2**31)")
    if matrix_gpus is not None and (
        not matrix_gpus
        or len(set(matrix_gpus)) != len(matrix_gpus)
        or any(type(gpu) is not int or gpu < 0 for gpu in matrix_gpus)
    ):
        raise ValueError("matrix_gpus must contain unique non-negative GPU IDs")
    output_dir.mkdir(parents=True, exist_ok=True)
    saved_manifest = output_dir / "manifest.json"
    if saved_manifest.exists():
        if not resume:
            raise FileExistsError(f"Use --resume or a fresh output: {output_dir}")
        previous = json.loads(saved_manifest.read_text(encoding="utf-8"))
        if seeds == list(range(100)) and previous.get("seeds") == to_jsonable(seeds):
            previous["seeds"] = seeds
        if previous != manifest:
            raise ValueError("Resume matrix manifest changed")
    write_json(saved_manifest, manifest)
    process_returncodes: dict[str, int] = {}
    lock = Lock()
    gpus: list[int | None] = list(matrix_gpus) if matrix_gpus is not None else [None]
    queues = group_tasks(tasks, len(gpus))
    assignments: dict[str, int] = {}
    unassigned: deque[dict[str, Any]] = deque()
    allocation_path = output_dir / "gpu_allocation.json"
    if matrix_scheduling == "dynamic":
        if allocation_path.exists():
            if not resume:
                raise FileExistsError(f"Use --resume or a fresh output: {output_dir}")
            allocations = json.loads(allocation_path.read_text(encoding="utf-8"))
            assignments = allocations["task_gpu_assignment"]
            if not isinstance(assignments, dict):
                raise ValueError(
                    "GPU allocation must contain task_gpu_assignment mapping"
                )
        task_names = {task["name"] for task in tasks}
        for name, gpu in assignments.items():
            if name not in task_names or type(gpu) is not int or gpu not in gpus:
                raise ValueError(f"Invalid saved GPU allocation: {name} -> {gpu}")
        if resume:
            for task in tasks:
                path = output_dir / task["name"] / "metadata.json"
                if not path.exists():
                    continue
                metadata = json.loads(path.read_text(encoding="utf-8"))
                gpu = metadata.get("gpu_id")
                if type(gpu) is not int or gpu not in gpus:
                    raise ValueError(f"Invalid metadata GPU allocation: {path}")
                if task["name"] in assignments and assignments[task["name"]] != gpu:
                    raise ValueError(
                        f"Conflicting saved and metadata GPU allocation: {path}"
                    )
                assignments[task["name"]] = gpu
        write_json(allocation_path, {"task_gpu_assignment": assignments})
        queues = [
            [task for task in tasks if assignments.get(task["name"]) == gpu]
            for gpu in gpus
        ]
        unassigned.extend(task for task in tasks if task["name"] not in assignments)

    def publish() -> dict[str, Any]:
        with lock:
            summary = summarize_matrix(manifest, output_dir, process_returncodes)
            summary["matrix_scheduling"] = matrix_scheduling
            if matrix_scheduling == "dynamic":
                summary["task_gpu_assignment"] = dict(assignments)
            write_json(output_dir / "summary.json", summary)
            return summary

    def run_queue(queue: list[dict[str, Any]], gpu: int | None) -> None:
        allocated = deque(queue)
        while True:
            if allocated:
                task = allocated.popleft()
            elif matrix_scheduling == "dynamic":
                with lock:
                    if not unassigned:
                        return
                    task = unassigned.popleft()
                    assert gpu is not None
                    assignments[task["name"]] = gpu
                    write_json(allocation_path, {"task_gpu_assignment": assignments})
            else:
                return
            args = task_command(
                command, manifest, task, output_dir, resume=resume, gpu=gpu
            )
            process = subprocess.run(args, check=False)
            with lock:
                process_returncodes[task["name"]] = process.returncode
            publish()

    publish()
    if len(gpus) == 1:
        run_queue(queues[0], gpus[0])
    else:
        with ThreadPoolExecutor(max_workers=len(gpus)) as executor:
            pending = {
                executor.submit(run_queue, queue, gpu)
                for queue, gpu in zip(queues, gpus, strict=True)
            }
            while pending:
                finished, pending = wait(
                    pending, timeout=10, return_when=FIRST_COMPLETED
                )
                for future in finished:
                    future.result()
                publish()
    return publish()
