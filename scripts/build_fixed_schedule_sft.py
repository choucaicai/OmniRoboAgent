"""Replay expert observations through Omni to distill a fixed chunk schedule."""

import argparse
import hashlib
import io
import json
import math
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import h5py
except ImportError:  # Replayed, pre-extracted images do not require HDF5.
    h5py = None
from PIL import Image

from omniroboagent.agent_core import (
    DefaultAgent,
    SubtaskPlanPlanner,
    SubtaskVerifier,
    TieredMemory,
)
from omniroboagent.backends.llm.base import LLMBackend
from omniroboagent.backends.skills.base import SkillBackend
from omniroboagent.environments.base import Environment
from omniroboagent.pipelines import SkillExecutionPipeline
from omniroboagent.runtimes import SyncRuntime

CAMERAS = {
    "head_rgb": "head_camera",
    "left_rgb": "left_camera",
    "right_rgb": "right_camera",
}


def raw_chunk_budgets(payload: dict[str, Any]) -> list[int]:
    return [
        math.ceil((segment["frame_end_exclusive"] - segment["frame_start"]) / 32)
        for segment in payload["segments"]
    ]


def schedule_signature(payload: dict[str, Any]) -> tuple[str, ...]:
    return tuple(segment["skill"] for segment in payload["segments"])


def schedule_id(task_name: str, signature: tuple[str, ...]) -> str:
    digest = hashlib.sha256(json.dumps(signature).encode()).hexdigest()[:12]
    return f"{task_name}:{digest}"


def build_max_schedule_catalog(
    records: list[tuple[Path, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    groups: dict[tuple[str, tuple[str, ...]], list[list[int]]] = defaultdict(list)
    for _, payload in records:
        groups[(payload["task_name"], schedule_signature(payload))].append(
            raw_chunk_budgets(payload)
        )

    catalog: dict[str, dict[str, Any]] = {}
    for (task_name, signature), episode_budgets in sorted(groups.items()):
        stage_count = len(signature)
        assert all(len(values) == stage_count for values in episode_budgets)
        minimums = [
            min(values[index] for values in episode_budgets)
            for index in range(stage_count)
        ]
        maximums = [
            max(values[index] for values in episode_budgets)
            for index in range(stage_count)
        ]
        identity = schedule_id(task_name, signature)
        catalog[identity] = {
            "schedule_id": identity,
            "task_name": task_name,
            "skill_sequence": list(signature),
            "stage_count": stage_count,
            "episode_count": len(episode_budgets),
            "observed_min_chunk_budgets": minimums,
            "max_chunk_budgets": maximums,
            "source_scope": "all source episodes",
        }
    return catalog


def resolve_max_schedule(
    payload: dict[str, Any], catalog: dict[str, dict[str, Any]]
) -> tuple[str, list[int]]:
    identity = schedule_id(payload["task_name"], schedule_signature(payload))
    budgets = catalog[identity]["max_chunk_budgets"]
    assert len(budgets) == len(payload["segments"])
    return identity, list(budgets)


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")


def sharegpt(messages: list[dict[str, Any]], answer: dict[str, Any]) -> dict[str, Any]:
    conversations, images = [], []
    for message in messages:
        content = message["content"]
        if isinstance(content, list):
            parts = []
            for item in content:
                if item["type"] == "image_url":
                    images.append(item["image_url"]["url"])
                    parts.append("<image>")
                else:
                    parts.append(item["text"])
            content = "\n".join(parts)
        conversations.append(
            {
                "from": {"system": "system", "user": "human"}[message["role"]],
                "value": content,
            }
        )
    conversations.append(
        {"from": "gpt", "value": json.dumps(answer, ensure_ascii=False)}
    )
    return {"conversations": conversations, "images": images}


class ReplayEnvironment(Environment):
    def __init__(
        self,
        payload: dict[str, Any],
        image_dir: Path,
        skills: list[str],
        budgets: list[int] | None = None,
        require_existing_images: bool = False,
        trust_reused_images: bool = False,
    ) -> None:
        self.payload = payload
        self.segments = payload["segments"]
        self.raw_budgets = raw_chunk_budgets(payload)
        self.budgets = list(self.raw_budgets if budgets is None else budgets)
        if len(self.budgets) != len(self.segments) or any(
            type(value) is not int or value <= 0 for value in self.budgets
        ):
            raise ValueError("budgets must contain one positive integer per segment")
        if any(
            budget < raw
            for budget, raw in zip(self.budgets, self.raw_budgets, strict=True)
        ):
            raise ValueError("scheduled budgets cannot truncate an expert segment")
        self.image_dir = image_dir
        self.require_existing_images = require_existing_images
        self.trust_reused_images = trust_reused_images
        if trust_reused_images and not require_existing_images:
            raise ValueError("trust_reused_images requires existing reused images")
        self.skills = skills
        self.handle: Any = None
        self.frame = 0
        self.index = 0
        self.chunk = 0
        self.image_sources: dict[str, dict[str, Any]] = {}
        self.executions: list[dict[str, Any]] = []

    def observation(self, frame: int) -> dict[str, Any]:
        result: dict[str, Any] = {
            "annotation.human.task_description": self.payload["instruction"],
            "available_skills": self.skills,
        }
        for key, camera in CAMERAS.items():
            path = self.image_dir / f"frame_{frame:06d}_{camera}.jpg"
            if str(path) not in self.image_sources:
                if self.trust_reused_images:
                    pass
                elif path.is_file():
                    with Image.open(path) as check:
                        check.verify()
                else:
                    if self.require_existing_images:
                        raise FileNotFoundError(f"missing reused image: {path}")
                    encoded = bytes(
                        self.handle[f"observation/{camera}/rgb"][frame]
                    ).rstrip(b"\0")
                    decoded = Image.open(io.BytesIO(encoded)).convert("RGB")
                    # The existing source collector encoded RGB with cv2.imencode.
                    # Match its audited replay repair: restore real-world RGB for Qwen.
                    red, green, blue = decoded.split()
                    Image.merge("RGB", (blue, green, red)).save(
                        path, quality=95, subsampling=0
                    )
                with Image.open(path) as check:
                    check.verify()
                self.image_sources[str(path)] = {
                    "path": str(path),
                    "source_hdf5": self.payload["hdf5_path"],
                    "source_frame": frame,
                    "camera": camera,
                    "color_repair": "rgb_encoded_as_bgr_v1",
                    "reused_existing_image": self.require_existing_images,
                }
            result[key] = str(path)
        self.frame = frame
        return result

    def reset(self, task: Any) -> dict[str, Any]:
        self.image_dir.mkdir(parents=True, exist_ok=True)
        if not self.trust_reused_images:
            if h5py is None:
                raise RuntimeError(
                    "h5py is required when replay images have not been pre-extracted"
                )
            self.handle = h5py.File(self.payload["hdf5_path"], "r")
            for camera in CAMERAS.values():
                assert (
                    len(self.handle[f"observation/{camera}/rgb"])
                    == self.payload["frame_count"]
                )
        return self.observation(self.segments[0]["frame_start"])

    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        assert execute_steps is None
        if self.chunk == self.budgets[self.index]:
            self.index += 1
            self.chunk = 0
        segment = self.segments[self.index]
        assert action["subtask"] == segment["subtask_instruction"]
        assert action["skill"] == segment["skill"]
        prompt = (
            f"Task: {self.payload['instruction']}\nSkill: {action['skill']}"
            f"\nSubtask: {action['subtask']}"
        )
        assert prompt == segment["omni_prompt"]
        self.chunk += 1
        frame = min(
            segment["frame_start"] + self.chunk * 32, segment["frame_end_exclusive"] - 1
        )
        self.executions.append(
            {
                "subtask_index": self.index,
                "chunk": self.chunk,
                "chunk_budget": self.budgets[self.index],
                "before_frame": self.frame,
                "after_frame": frame,
                "vla_prompt": prompt,
            }
        )
        return {
            "observation": self.observation(frame),
            "task_success": False,
            "done": False,
            "last_action_success": True,
            "executed_steps": 32,
            "env_feedback": "action_executed",
        }

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()


class ReplayPolicy(SkillBackend):
    def predict(self, inputs: dict[str, Any]) -> Any:
        return {"skill": inputs["skill"], "subtask": inputs["subtask"]}


class ScheduleTeacher(LLMBackend):
    def __init__(
        self,
        environment: ReplayEnvironment,
        identity: str,
    ) -> None:
        self.env = environment
        self.identity = identity
        self.rows: list[dict[str, Any]] = []
        self.planner_calls = 0

    def complete(self, inputs: dict[str, Any]) -> dict[str, Any]:
        role = inputs["response_format"]["json_schema"]["name"]
        content = inputs["messages"][1]["content"][0]["text"]
        if role == "subtask_plan":
            plan_input = json.loads(content)
            assert plan_input["task"] == self.env.payload["instruction"]
            assert plan_input["available_skills"] == self.env.skills
            answer = {
                "subtasks": [
                    {
                        "subtask_index": index,
                        "skill": segment["skill"],
                        "instruction": segment["subtask_instruction"],
                        "success_condition": segment["completion_criteria"],
                        "chunk_budget": self.env.budgets[index],
                    }
                    for index, segment in enumerate(self.env.segments)
                ]
            }
            self.planner_calls += 1
            kind = "plan"
            index = 0
            context = {
                "completed_subtask_count": 0,
                "current_subtask_index": 0,
                "current_chunk": 0,
                "total_subtasks": len(self.env.segments),
            }
        elif role == "subtask_selection":
            selection_input = json.loads(content)
            expected_plan = [
                {
                    "subtask_index": plan_index,
                    "skill": segment["skill"],
                    "instruction": segment["subtask_instruction"],
                    "success_condition": segment["completion_criteria"],
                    "chunk_budget": self.env.budgets[plan_index],
                }
                for plan_index, segment in enumerate(self.env.segments)
            ]
            assert selection_input["task"] == self.env.payload["instruction"]
            assert selection_input["available_skills"] == self.env.skills
            assert selection_input["execution_plan"] == expected_plan
            context = selection_input["progress"]
            index = context["current_subtask_index"]
            assert index == self.planner_calls - 1
            assert context == {
                "completed_subtask_count": index,
                "completed_subtask_indices": list(range(index)),
                "current_subtask_index": index,
                "current_chunk": 0,
                "current_chunk_budget": self.env.budgets[index],
                "total_subtasks": len(expected_plan),
            }
            answer = expected_plan[index]
            self.planner_calls += 1
            kind = "planner"
        else:
            verifier_input = json.loads(content)
            expected_plan = [
                {
                    "subtask_index": plan_index,
                    "skill": segment["skill"],
                    "instruction": segment["subtask_instruction"],
                    "success_condition": segment["completion_criteria"],
                    "chunk_budget": self.env.budgets[plan_index],
                }
                for plan_index, segment in enumerate(self.env.segments)
            ]
            assert verifier_input["execution_plan"] == expected_plan
            context = verifier_input["progress"]
            index = context["current_subtask_index"]
            count = context["current_chunk"]
            budget = context["current_chunk_budget"]
            assert context["completed_subtask_count"] == index
            assert context["completed_subtask_indices"] == list(range(index))
            assert context["total_subtasks"] == len(expected_plan)
            assert budget == self.env.budgets[index]
            assert (
                verifier_input["subtask"]
                == self.env.segments[index]["subtask_instruction"]
            )
            assert verifier_input["skill"] == self.env.segments[index]["skill"]
            assert (index, count) == (self.env.index, self.env.chunk)
            done = count >= budget
            reason = (
                f"Chunk budget {'reached' if done else 'not reached'}: "
                f"{count}/{budget}."
            )
            evidence = [f"current_chunk={count}", f"chunk_budget={budget}"]
            answer = {
                "execution_status": "completed" if done else "in_progress",
                "reason": reason,
                "confidence": 1.0,
                "evidence": evidence,
            }
            kind = "verifier"
        training = sharegpt(inputs["messages"], answer)
        for path in training["images"]:
            assert self.env.image_sources[path]["source_frame"] <= self.env.frame
        self.rows.append(
            {
                "id": f"{self.identity}:{len(self.rows):04d}:{kind}",
                "kind": kind,
                "subtask_index": index,
                "schedule_context": context,
                "request": inputs,
                "answer": answer,
                "training": training,
            }
        )
        return {"choices": [{"message": {"content": json.dumps(answer)}}]}


def replay_episode(
    payload: dict[str, Any],
    image_dir: Path,
    trace_root: Path,
    catalog: dict[str, str],
    budgets: list[int] | None = None,
    require_existing_images: bool = False,
    trust_reused_images: bool = False,
) -> tuple[ScheduleTeacher, dict[str, Any]]:
    identity = f"{payload['task_name']}:episode{payload['episode_index']:04d}"
    skills = list(catalog.values())
    env = ReplayEnvironment(
        payload,
        image_dir,
        skills,
        budgets=budgets,
        require_existing_images=require_existing_images,
        trust_reused_images=trust_reused_images,
    )
    teacher = ScheduleTeacher(env, identity)
    planner = SubtaskPlanPlanner(
        backend=teacher,
        camera_keys=list(CAMERAS),
        scheduled_chunks=True,
    )
    agent = DefaultAgent(
        planner=planner,
        verifier=SubtaskVerifier(
            backend=teacher,
            camera_keys=list(CAMERAS),
            planned_chunk_schedule=True,
        ),
        memory=TieredMemory(camera_keys=list(CAMERAS), save_key_event_artifacts=False),
        skill_backend=ReplayPolicy(),
    )
    task = {
        "task_name": payload["task_name"],
        "episode_index": payload["episode_index"],
        "seed": payload["seed"],
        "instruction": payload["instruction"],
        "chunk_budgets": env.budgets,
    }
    result = SyncRuntime(max_steps=sum(env.budgets) + 2, output_dir=trace_root).run(
        agent, SkillExecutionPipeline(), env, task, session_id=identity
    )
    assert result["termination_reason"] == "plan_exhausted", result
    assert result["success"] is False  # Replay never fabricates benchmark success.
    assert result["action_chunks"] == sum(env.budgets)
    expected_planner_calls = 1 + len(env.segments)
    assert teacher.planner_calls == expected_planner_calls
    assert len(teacher.rows) == sum(env.budgets) + expected_planner_calls
    return teacher, {
        "id": identity,
        "task": task,
        "runtime_result": result,
        "executions": env.executions,
        "raw_chunk_budgets": env.raw_budgets,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--reuse-images-from", type=Path)
    parser.add_argument("--trust-reused-images", action="store_true")
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    if args.reuse_images_from is not None:
        reuse_images_from = args.reuse_images_from.resolve()
        if not reuse_images_from.is_dir():
            raise FileNotFoundError(reuse_images_from)
        if args.trust_reused_images:
            audit_path = reuse_images_from.parent / "audit.json"
            audit = json.loads(audit_path.read_text())
            if audit.get("status") != "PASS":
                raise ValueError("Trusted reused images require a PASS audit")
        (output / "images").symlink_to(reuse_images_from, target_is_directory=True)
    elif args.trust_reused_images:
        raise ValueError("--trust-reused-images requires --reuse-images-from")
    source_summary = json.loads((source / "summary.json").read_text())
    catalog = source_summary["skill_catalog"]
    split = json.loads((source / "splits/task_stratified_seed42_val5.json").read_text())
    write_json(output / "source_split.json", split)
    write_json(output / "skill_catalog.json", catalog)
    all_files = sorted((source / "segments").glob("*/*.json"))
    all_records = [(path, json.loads(path.read_text())) for path in all_files]
    schedule_catalog = build_max_schedule_catalog(all_records)
    write_json(output / "schedule_catalog.json", schedule_catalog)
    # These specs are also used for served-model inference. The endpoint/model
    # are supplied when a trained Qwen is served, not needed by the teacher.
    llm_backend = {
        "class_path": "omniroboagent.backends.llm.OpenAICompatibleLLMBackend",
        "init_args": {
            "base_url": "http://127.0.0.1:8001",
            "model": "qwen_schedule",
        },
    }
    planner_spec = {
        "class_path": "omniroboagent.agent_core.SubtaskPlanPlanner",
        "init_args": {
            "backend": llm_backend,
            "camera_keys": list(CAMERAS),
            "scheduled_chunks": True,
        },
    }
    verifier_args = {
        "backend": llm_backend,
        "camera_keys": list(CAMERAS),
        "planned_chunk_schedule": True,
    }
    write_json(
        output / "agent_config.json",
        {
            "agent": {"class_path": "omniroboagent.agent_core.DefaultAgent"},
            "planner": planner_spec,
            "verifier": {
                "class_path": "omniroboagent.agent_core.SubtaskVerifier",
                "init_args": verifier_args,
            },
            "memory": {
                "class_path": "omniroboagent.agent_core.TieredMemory",
                "init_args": {
                    "camera_keys": list(CAMERAS),
                    "save_key_event_artifacts": False,
                },
            },
            "skill_backend": {
                "class_path": (
                    "omniroboagent.backends.skills.pi05_worker.Pi05WorkerBackend"
                ),
                "init_args": {
                    "port": 9665,
                    "prompt_mode": "task_skill_subtask",
                    "horizon": 32,
                },
            },
        },
    )
    files = all_files
    if args.limit is not None:
        files = files[: args.limit]
    streams = {
        name: (output / name).open("w")
        for name in [
            "train.jsonl",
            "val.jsonl",
            "requests.jsonl",
            "episodes.jsonl",
            "images.jsonl",
        ]
    }
    counts: Counter[str] = Counter()
    tasks: dict[str, Counter[str]] = {}
    budgets: Counter[int] = Counter()
    raw_budgets: Counter[int] = Counter()
    examples = []
    trace_root = output / "_runtime_traces"
    try:
        for position, metadata_path in enumerate(files):
            payload = json.loads(metadata_path.read_text())
            name, ep = payload["task_name"], payload["episode_index"]
            task_split = split["tasks"][name]
            assert (ep in task_split["val_episode_indices"]) != (
                ep in task_split["train_episode_indices"]
            )
            split_name = "val" if ep in task_split["val_episode_indices"] else "train"
            previous = 0
            for index, segment in enumerate(payload["segments"]):
                assert segment["segment_index"] == index
                assert segment["frame_start"] == previous
                assert segment["frame_end_exclusive"] > previous
                previous = segment["frame_end_exclusive"]
                assert catalog[segment["skill_id"]] == segment["skill"]
            assert previous == payload["frame_count"]
            episode_schedule_id, episode_budgets = resolve_max_schedule(
                payload, schedule_catalog
            )
            teacher, episode = replay_episode(
                payload,
                output / "images" / name / f"episode{ep:04d}",
                trace_root,
                catalog,
                budgets=episode_budgets,
                require_existing_images=args.reuse_images_from is not None,
                trust_reused_images=args.trust_reused_images,
            )
            episode.update(
                split=split_name,
                schedule_id=episode_schedule_id,
                metadata_path=str(metadata_path),
                metadata_sha256=hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
            )
            # Keep compact provenance; full model inputs are in requests.jsonl.
            episode["runtime_result"].pop("last_output", None)
            episode["runtime_result"].pop("trace_path", None)
            streams["episodes.jsonl"].write(json.dumps(episode) + "\n")
            for row in teacher.rows:
                training = row.pop("training")
                serialized_training = json.dumps(training)
                assert "chunk_budget" in serialized_training
                streams[f"{split_name}.jsonl"].write(
                    json.dumps({"id": row["id"], **training}) + "\n"
                )
                streams["requests.jsonl"].write(
                    json.dumps({"split": split_name, **row}) + "\n"
                )
                counts[f"{split_name}_{row['kind']}"] += 1
                default_answer_kind = "plan" if row["kind"] == "plan" else "planner"
                counts[row["answer"].get("execution_status", default_answer_kind)] += 1
                tasks.setdefault(name, Counter())[row["kind"]] += 1
                counts["rows"] += 1
            for record in teacher.env.image_sources.values():
                streams["images.jsonl"].write(json.dumps(record) + "\n")
            counts["images"] += len(teacher.env.image_sources)
            counts[f"{split_name}_episodes"] += 1
            counts["episodes"] += 1
            budgets.update(teacher.env.budgets)
            raw_budgets.update(teacher.env.raw_budgets)
            if len(examples) < 1 or (
                name == "stack_blocks_three" and len(examples) < 2
            ):
                examples.append({"episode": episode, "calls": teacher.rows})
            shutil.rmtree(trace_root / episode["id"])
            if position % 25 == 0 or position + 1 == len(files):
                for stream in streams.values():
                    stream.flush()
                write_json(
                    output / "progress.json",
                    {
                        "status": "running",
                        **counts,
                        "total_episodes": len(files),
                        "last_episode": episode["id"],
                    },
                )
                print(
                    json.dumps(
                        {
                            "episodes": counts["episodes"],
                            "total": len(files),
                            "rows": counts["rows"],
                            "last": episode["id"],
                        }
                    ),
                    flush=True,
                )
    finally:
        for stream in streams.values():
            stream.close()
    summary = {
        "status": "complete",
        "source": str(source),
        "output": str(output),
        **counts,
        "task_count": len(tasks),
        "skill_count": len(catalog),
        "per_task": tasks,
        "chunk_budget_histogram": dict(sorted(budgets.items())),
        "raw_chunk_budget_histogram": dict(sorted(raw_budgets.items())),
        "budget_policy": (
            "per task and skill-sequence variant, maximum ceil(segment_frames / 32) "
            "over all source episodes; generated by Qwen in the initial plan and "
            "reused as explicit runtime state during each planner selection"
        ),
        "label_policy": (
            "current_chunk below the initial plan's chunk_budget => in_progress; at "
            "the budget => completed"
        ),
        "image_policy": (
            "expert replay; min(segment_start + chunk*32, segment_end-1); RGB repaired"
        ),
        "meaning": (
            "initial full-plan generation, image-conditioned per-subtask planner "
            "selection, and explicit plan-progress execution; no benchmark success "
            "labels"
        ),
        "runtime": "Omni SyncRuntime + SkillExecutionPipeline + TieredMemory",
        "audit": (
            "all source ranges, splits, prompt strings, counters, order, image "
            "readability and no future image references checked"
        ),
    }
    write_json(output / "summary.json", summary)
    write_json(output / "progress.json", {"status": "complete", **counts})
    write_json(output / "examples.json", examples)
    dataset_prefix = "omni_full_plan_schedule"
    write_json(
        output / "dataset_info.json",
        {
            f"{dataset_prefix}_{part}": {
                "file_name": f"{part}.jsonl",
                "formatting": "sharegpt",
                "columns": {"messages": "conversations", "images": "images"},
                "tags": {
                    "role_tag": "from",
                    "content_tag": "value",
                    "user_tag": "human",
                    "assistant_tag": "gpt",
                    "system_tag": "system",
                },
            }
            for part in ["train", "val"]
        },
    )
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
