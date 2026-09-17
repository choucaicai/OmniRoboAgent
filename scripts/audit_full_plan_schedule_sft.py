"""Independently audit full-plan explicit-progress schedule SFT data."""

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def expected_plan(
    episode: dict[str, Any], metadata: dict[str, Any]
) -> list[dict[str, Any]]:
    budgets = episode["task"]["chunk_budgets"]
    return [
        {
            "subtask_index": index,
            "skill": segment["skill"],
            "instruction": segment["subtask_instruction"],
            "success_condition": segment["completion_criteria"],
            "chunk_budget": budgets[index],
        }
        for index, segment in enumerate(metadata["segments"])
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args()
    root = args.dataset.resolve()

    summary = read_json(root / "summary.json")
    catalog = read_json(root / "schedule_catalog.json")
    assert summary["status"] == "complete"
    assert summary["meaning"].startswith("initial full-plan generation")
    assert len(catalog) == 54

    episodes: dict[str, dict[str, Any]] = {}
    metadata: dict[str, dict[str, Any]] = {}
    plans: dict[str, list[dict[str, Any]]] = {}
    split_ids = {"train": set(), "val": set()}
    for line in (root / "episodes.jsonl").open():
        row = json.loads(line)
        identity = row["id"]
        assert identity not in episodes
        schedule = catalog[row["schedule_id"]]
        scheduled = row["task"]["chunk_budgets"]
        raw = row["raw_chunk_budgets"]
        assert scheduled == schedule["max_chunk_budgets"]
        assert len(raw) == len(scheduled) == schedule["stage_count"]
        assert all(a <= b for a, b in zip(raw, scheduled, strict=True))
        source = read_json(Path(row["metadata_path"]))
        assert source["task_name"] == row["task"]["task_name"]
        assert source["episode_index"] == row["task"]["episode_index"]
        assert source["instruction"] == row["task"]["instruction"]
        episodes[identity] = row
        metadata[identity] = source
        plans[identity] = expected_plan(row, source)
        split_ids[row["split"]].add(identity)

    assert not split_ids["train"] & split_ids["val"]
    assert len(split_ids["train"]) == summary.get("train_episodes", 0)
    assert len(split_ids["val"]) == summary.get("val_episodes", 0)
    assert len(episodes) == summary["episodes"]
    if not args.allow_partial:
        assert len(split_ids["train"]) == 2236
        assert len(split_ids["val"]) == 250
        assert len(episodes) == 2486

    images: dict[str, dict[str, Any]] = {}
    for line in (root / "images.jsonl").open():
        row = json.loads(line)
        path = row["path"]
        assert path not in images
        assert Path(path).is_file()
        assert row["reused_existing_image"] is True
        images[path] = row
    assert len(images) == summary["images"]

    counts: Counter[str] = Counter()
    seen: set[str] = set()
    cursors: dict[str, dict[str, Any]] = {}
    for line in (root / "requests.jsonl").open():
        row = json.loads(line)
        assert row["id"] not in seen
        seen.add(row["id"])
        identity = ":".join(row["id"].split(":")[:2])
        episode = episodes[identity]
        plan = plans[identity]
        assert row["split"] == episode["split"]
        cursor = cursors.setdefault(
            identity,
            {"index": 0, "chunk": 0, "plan": 0, "selected": False},
        )
        request = row["request"]
        assert "episode_index" not in json.dumps(request["messages"])
        assert '"seed"' not in json.dumps(request["messages"])

        if row["kind"] == "plan":
            assert cursor == {
                "index": 0,
                "chunk": 0,
                "plan": 0,
                "selected": False,
            }
            assert request["response_format"]["json_schema"]["name"] == "subtask_plan"
            prompt = json.loads(request["messages"][1]["content"][0]["text"])
            assert prompt["task"] == episode["task"]["instruction"]
            assert prompt["image_roles"] == ["head_rgb", "left_rgb", "right_rgb"]
            assert len(prompt["available_skills"]) == summary["skill_count"]
            assert row["answer"] == {"subtasks": plan}
            assert len(
                [
                    part
                    for part in request["messages"][1]["content"]
                    if part["type"] == "image_url"
                ]
            ) == 3
            cursor["plan"] = 1
        elif row["kind"] == "planner":
            assert cursor["plan"] == 1
            assert cursor["chunk"] == 0
            assert cursor["selected"] is False
            index = cursor["index"]
            assert request["response_format"]["json_schema"]["name"] == (
                "subtask_selection"
            )
            prompt = json.loads(request["messages"][1]["content"][0]["text"])
            assert prompt["task"] == episode["task"]["instruction"]
            assert prompt["image_roles"] == ["head_rgb", "left_rgb", "right_rgb"]
            assert len(prompt["available_skills"]) == summary["skill_count"]
            assert prompt["execution_plan"] == plan
            assert prompt["progress"] == {
                "completed_subtask_count": index,
                "completed_subtask_indices": list(range(index)),
                "current_subtask_index": index,
                "current_chunk": 0,
                "current_chunk_budget": plan[index]["chunk_budget"],
                "total_subtasks": len(plan),
            }
            assert row["answer"] == plan[index]
            assert len(
                [
                    part
                    for part in request["messages"][1]["content"]
                    if part["type"] == "image_url"
                ]
            ) == 3
            cursor["selected"] = True
        else:
            assert row["kind"] == "verifier"
            assert cursor["plan"] == 1
            assert cursor["selected"] is True
            prompt = json.loads(request["messages"][1]["content"][0]["text"])
            progress = prompt["progress"]
            index = cursor["index"]
            cursor["chunk"] += 1
            chunk = cursor["chunk"]
            budget = plan[index]["chunk_budget"]
            assert prompt["execution_plan"] == plan
            assert prompt["skill"] == plan[index]["skill"]
            assert prompt["subtask"] == plan[index]["instruction"]
            assert prompt["expected_outcome"] == plan[index]["success_condition"]
            assert progress == {
                "completed_subtask_count": index,
                "completed_subtask_indices": list(range(index)),
                "current_subtask_index": index,
                "current_chunk": chunk,
                "current_chunk_budget": budget,
                "total_subtasks": len(plan),
            }
            expected_status = "completed" if chunk == budget else "in_progress"
            assert row["answer"]["execution_status"] == expected_status
            assert row["answer"]["evidence"] == [
                f"current_chunk={chunk}",
                f"chunk_budget={budget}",
            ]
            counts[expected_status] += 1
            if expected_status == "completed":
                cursor.update(index=index + 1, chunk=0, selected=False)
        counts[row["kind"]] += 1

    assert all(
        cursor["plan"] == 1 and cursor["selected"] is False
        for cursor in cursors.values()
    )
    assert all(
        cursor["index"] == len(plans[identity]) and cursor["chunk"] == 0
        for identity, cursor in cursors.items()
    )
    assert counts["plan"] == summary["plan"] == len(episodes)
    assert counts["planner"] == summary["planner"] == sum(
        len(plan) for plan in plans.values()
    )
    assert counts["verifier"] == summary.get(
        "train_verifier", 0
    ) + summary.get("val_verifier", 0)
    assert counts["in_progress"] == summary["in_progress"]
    assert counts["completed"] == summary["completed"]

    training_ids: set[str] = set()
    image_histogram: Counter[int] = Counter()
    for part in ["train", "val"]:
        for line in (root / f"{part}.jsonl").open():
            row = json.loads(line)
            assert row["id"] not in training_ids
            training_ids.add(row["id"])
            identity = ":".join(row["id"].split(":")[:2])
            assert identity in split_ids[part]
            assert [message["from"] for message in row["conversations"]] == [
                "system",
                "human",
                "gpt",
            ]
            placeholders = sum(
                message["value"].count("<image>")
                for message in row["conversations"]
            )
            assert placeholders == len(row["images"])
            assert all(path in images for path in row["images"])
            json.loads(row["conversations"][-1]["value"])
            image_histogram[len(row["images"])] += 1

    assert training_ids == seen
    assert len(seen) == summary["rows"]
    assert counts["plan"] + counts["planner"] + counts["verifier"] == len(seen)

    report = {
        "status": "PASS",
        "episodes": len(episodes),
        "tasks": summary["task_count"],
        "schedule_variants": len(catalog),
        "rows": len(seen),
        **counts,
        "unique_images": len(images),
        "images_per_request": dict(sorted(image_histogram.items())),
        "checks": [
            "exactly one initial complete plan per episode",
            "initial plan matches every source subtask, skill, condition and budget",
            "one image-conditioned Omni planner selection precedes every subtask",
            "every selected subtask exactly matches the current cached plan item",
            "the identical complete plan is reused in every verifier request",
            "completed count, current subtask and chunk progress are continuous",
            "in_progress and completed occur only at the correct budget boundary",
            "episode index and seed are absent from model messages",
            "whole-episode train/validation split isolation",
            "all image placeholders and reused image references",
        ],
    }
    (root / "audit.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
