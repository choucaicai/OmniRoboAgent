"""Run real RoboTwin episodes with Qwen scheduling and a resident pi0.5 worker."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from omniroboagent.agent_core import (
    DefaultAgent,
    SubtaskPlanPlanner,
    SubtaskVerifier,
    TieredMemory,
)
from omniroboagent.backends.llm import OpenAICompatibleLLMBackend
from omniroboagent.backends.skills.pi05_worker import Pi05WorkerBackend
from omniroboagent.environments.benchmarks.robotwin import RoboTwinEnvironment
from omniroboagent.pipelines import SkillExecutionPipeline
from omniroboagent.runtimes import SyncRuntime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = (
    PROJECT_ROOT / "runs/data/omni_full_plan_select_schedule_sft_2486_20260913"
)
DEFAULT_CONFIG = PROJECT_ROOT / "configs/examples/robotwin_omni_pi05.example.json"
SKILLS = [
    "gripper control",
    "handover",
    "hang",
    "open",
    "pick and place",
    "pour",
    "press",
    "rotate",
    "scan",
    "shake",
    "tool use",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument(
        "--seed-manifest",
        type=Path,
        default=None,
        help=(
            "RoboTwin valid-seed JSON. When set, evaluate its live simulator seeds "
            "without reading dataset episodes or expert segment annotations."
        ),
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task-name", default="adjust_bottle")
    parser.add_argument("--episode-index", type=int, action="append", default=[])
    parser.add_argument("--qwen-url", default="http://127.0.0.1:8001")
    parser.add_argument("--qwen-model", default="qwen_schedule")
    parser.add_argument(
        "--qwen-direct",
        action="store_true",
        help=(
            "Load the local Qwen LoRA in this process instead of using an HTTP server."
        ),
    )
    parser.add_argument(
        "--qwen-base-model",
        type=Path,
        default=(
            Path(os.environ["QWEN35_BASE_MODEL"])
            if "QWEN35_BASE_MODEL" in os.environ
            else None
        ),
    )
    parser.add_argument(
        "--qwen-adapter",
        type=Path,
        default=Path(
            "runs/sft/qwen35_9b_omni_full_plan_select_3gpu_20260913/"
            "checkpoints/checkpoint-3500"
        ),
    )
    parser.add_argument("--pi-host", default="127.0.0.1")
    parser.add_argument("--pi-port", type=int, default=9965)
    parser.add_argument("--max-steps", type=int, default=50)
    parser.add_argument("--timeout-seconds", type=float, default=1800)
    parser.add_argument("--resume", action="store_true")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def load_candidates(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.seed_manifest is None:
        return [
            row
            for row in read_jsonl(args.dataset.resolve() / "episodes.jsonl")
            if row["task"]["task_name"] == args.task_name
        ]

    manifest = json.loads(args.seed_manifest.resolve().read_text(encoding="utf-8"))
    task_name = manifest.get("task_name")
    if task_name != args.task_name:
        raise ValueError(
            f"Seed manifest task_name={task_name!r} does not match {args.task_name!r}"
        )
    valid = manifest.get("valid")
    if not isinstance(valid, list) or not valid:
        raise ValueError("Seed manifest requires a non-empty valid list")
    candidates = []
    for position, item in enumerate(valid):
        if not isinstance(item, dict):
            raise ValueError(f"Invalid seed manifest row {position}")
        eval_index = int(item.get("eval_index", position))
        seed = int(item["seed"])
        instruction = str(item["instruction"]).strip()
        if not instruction:
            raise ValueError(f"Seed {seed} has an empty instruction")
        candidates.append(
            {
                "id": f"{task_name}:heldout_seed{seed}",
                "split": "test",
                "task": {
                    "task_name": task_name,
                    "episode_index": eval_index,
                    "seed": seed,
                    "instruction": instruction,
                },
            }
        )
    return candidates


def load_direct_qwen(args: argparse.Namespace) -> Any:
    from eval_omni_schedule_lora import TransformersBackend

    if args.qwen_base_model is None:
        raise ValueError(
            "--qwen-base-model or QWEN35_BASE_MODEL is required with --qwen-direct"
        )
    return TransformersBackend(
        args.qwen_base_model.resolve(),
        args.qwen_adapter.resolve(),
        temperature=0.2,
        top_p=0.9,
        top_k=20,
        max_new_tokens=1024,
        attn_implementation="sdpa",
    )


def build_agent(args: argparse.Namespace, direct_backend: Any = None) -> DefaultAgent:
    def qwen() -> Any:
        if args.qwen_direct:
            if direct_backend is None:
                raise RuntimeError("Direct Qwen backend was not initialized")
            return direct_backend
        return OpenAICompatibleLLMBackend(
            base_url=args.qwen_url,
            model=args.qwen_model,
            timeout_seconds=300,
            max_retries=1,
        )

    return DefaultAgent(
        planner=SubtaskPlanPlanner(
            backend=qwen(),
            camera_keys=["head_rgb", "left_rgb", "right_rgb"],
            scheduled_chunks=True,
        ),
        verifier=SubtaskVerifier(
            backend=qwen(),
            camera_keys=["head_rgb", "left_rgb", "right_rgb"],
            check_interval_chunks=1,
            planned_chunk_schedule=True,
        ),
        memory=TieredMemory(
            visual_window_size=4,
            recent_event_limit=20,
            key_event_limit=20,
            summary_max_chars=4096,
            save_key_event_artifacts=False,
            camera_keys=["head_rgb", "left_rgb", "right_rgb"],
        ),
        skill_backend=Pi05WorkerBackend(
            host=args.pi_host,
            port=args.pi_port,
            horizon=32,
            num_steps=10,
            prompt_mode="task_skill_subtask",
            timeout_seconds=300,
        ),
    )


def plan_from_trace(path: Path) -> list[dict[str, Any]] | None:
    if not path.is_file():
        return None
    for row in read_jsonl(path):
        output = row.get("planner_output")
        plan = output.get("plan") if isinstance(output, dict) else None
        if isinstance(plan, list):
            return plan
    return None


def load_completed(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    return {str(row["id"]): row for row in read_jsonl(path)}


def write_summary(
    path: Path, selected: list[dict[str, Any]], completed: dict[str, dict[str, Any]]
) -> None:
    rows = [completed[row["id"]] for row in selected if row["id"] in completed]
    by_split = {}
    for split in sorted({row["split"] for row in rows}):
        split_rows = [row for row in rows if row["split"] == split]
        successes = sum(bool(row["success"]) for row in split_rows)
        by_split[split] = {
            "completed": len(split_rows),
            "successes": successes,
            "accuracy": successes / len(split_rows) if split_rows else None,
        }
    successes = sum(bool(row["success"]) for row in rows)
    payload = {
        "target": len(selected),
        "completed": len(rows),
        "successes": successes,
        "accuracy": successes / len(rows) if rows else None,
        "by_split": by_split,
        "success_definition": "RoboTwin task_env.check_success()",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "episodes": rows,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def main() -> None:
    args = parse_args()
    candidates = load_candidates(args)
    requested = set(args.episode_index)
    selected = [
        row
        for row in candidates
        if not requested or int(row["task"]["episode_index"]) in requested
    ]
    selected.sort(key=lambda row: int(row["task"]["episode_index"]))
    if requested and requested != {
        int(row["task"]["episode_index"]) for row in selected
    }:
        missing = sorted(
            requested - {int(row["task"]["episode_index"]) for row in selected}
        )
        raise ValueError(f"Missing episode indices: {missing}")
    if not selected:
        raise ValueError("No episodes selected")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    episodes_path = args.output.parent / f"{args.output.stem}_episodes.jsonl"
    completed = load_completed(episodes_path) if args.resume else {}
    if not args.resume:
        episodes_path.write_text("")
    direct_backend = load_direct_qwen(args) if args.qwen_direct else None

    for position, episode in enumerate(selected, start=1):
        identity = episode["id"]
        if identity in completed:
            continue
        task = dict(episode["task"])
        task.pop("chunk_budgets", None)
        session_id = identity.replace(":", "_")
        environment = RoboTwinEnvironment(
            config_path=str(args.config.resolve()),
            artifact_dir=str(args.output.parent / "observations" / session_id),
            available_skills=SKILLS,
        )
        result = SyncRuntime(
            max_steps=args.max_steps,
            timeout_seconds=args.timeout_seconds,
            output_dir=args.output.parent / "traces",
        ).run(
            build_agent(args, direct_backend),
            SkillExecutionPipeline(
                reobserve_on_uncertain=True,
                max_chunks_per_skill=50,
                max_attempts_per_execution=2,
                max_uncertain_verifications=3,
                max_replans=2,
            ),
            environment,
            task,
            session_id=session_id,
        )
        row = {
            "id": identity,
            "split": episode["split"],
            "task": task,
            "success": bool(result.get("success")),
            "termination_reason": result.get("termination_reason"),
            "steps": result.get("steps"),
            "action_chunks": result.get("action_chunks"),
            "planner_calls": result.get("planner_calls"),
            "latency_seconds": result.get("latency_seconds"),
            "error_type": result.get("error_type"),
            "error": result.get("error"),
            "plan": plan_from_trace(Path(result["trace_path"])),
            "trace_path": result.get("trace_path"),
            "success_source": "RoboTwin.task_env.check_success()",
        }
        with episodes_path.open("a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        completed[identity] = row
        write_summary(args.output, selected, completed)
        print(
            json.dumps(
                {
                    "episode": f"{position}/{len(selected)}",
                    "id": identity,
                    "split": episode["split"],
                    "success": row["success"],
                    "termination_reason": row["termination_reason"],
                    "chunks": row["action_chunks"],
                    "plan": row["plan"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    write_summary(args.output, selected, completed)


if __name__ == "__main__":
    main()
