#!/usr/bin/env python3
"""Build a local LeRobot v3 LIBERO dataset relabeled by executable subtask.

The source contains successful expert trajectories. For the nine composite
LIBERO-Long tasks, the first sustained gripper-close interval ends when the
first semantic subtask releases its object. We split at that release so a
PI0.5 action chunk cannot cross from one subtask prompt into the next. Atomic
episodes remain byte-for-byte hard links to the source parquet files.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

# Keys here are task_index values from HuggingFaceVLA/libero, not LIBERO suite IDs.
COMPOSITE_SUBTASKS: dict[int, tuple[str, str]] = {
    0: (
        "Put the white mug on the left plate.",
        "Put the yellow and white mug on the right plate.",
    ),
    1: (
        "Put the white mug on the plate.",
        "Put the chocolate pudding to the right of the plate.",
    ),
    2: (
        "Put the yellow and white mug in the microwave.",
        "Close the microwave.",
    ),
    3: ("Turn on the stove.", "Put the moka pot on the stove."),
    4: (
        "Put the alphabet soup in the basket.",
        "Put the cream cheese box in the basket.",
    ),
    5: (
        "Put the alphabet soup in the basket.",
        "Put the tomato sauce in the basket.",
    ),
    # The expert demonstrations execute the initially right pot first.
    6: (
        "Put the right moka pot on the stove.",
        "Put the left moka pot on the stove.",
    ),
    7: (
        "Put the cream cheese box in the basket.",
        "Put the butter in the basket.",
    ),
    8: (
        "Put the black bowl in the bottom drawer of the cabinet.",
        "Close the bottom drawer of the cabinet.",
    ),
}

FEATURE_RENAMES = {
    "image": "observation.images.image",
    "wrist_image": "observation.images.image2",
    "state": "observation.state",
    "actions": "action",
}


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    ]


def first_release_cut(table: pa.Table, min_closed_frames: int) -> int:
    gripper = np.asarray(table["actions"].to_pylist(), dtype=np.float32)[:, 6]
    closed = gripper > 0.5
    start: int | None = None
    for index, is_closed in enumerate(closed):
        if is_closed and start is None:
            start = index
        elif not is_closed and start is not None:
            if index - start >= min_closed_frames:
                # Include this first release command in the first segment.
                return index + 1
            start = None
    raise ValueError("No sustained grasp/release interval found")


def replace_column(table: pa.Table, name: str, values: np.ndarray) -> pa.Table:
    column_index = table.schema.get_field_index(name)
    field_type = table.schema.field(name).type
    return table.set_column(column_index, name, pa.array(values, type=field_type))


def relabel_segment(
    table: pa.Table,
    *,
    episode_index: int,
    task_index: int,
    reset_time: bool,
    fps: int,
) -> pa.Table:
    length = len(table)
    table = replace_column(
        table, "episode_index", np.full(length, episode_index, dtype=np.int64)
    )
    table = replace_column(
        table, "task_index", np.full(length, task_index, dtype=np.int64)
    )
    if reset_time:
        table = replace_column(table, "frame_index", np.arange(length, dtype=np.int64))
        table = replace_column(
            table, "timestamp", np.arange(length, dtype=np.float32) / float(fps)
        )
    return table


def data_path(root: Path, episode_index: int, pattern: str) -> Path:
    return root / pattern.format(
        episode_chunk=episode_index // 1000,
        episode_index=episode_index,
        chunk_index=episode_index // 1000,
        file_index=episode_index % 1000,
    )


def write_table(table: pa.Table, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="snappy", use_dictionary=True)


def build(args: argparse.Namespace) -> None:
    source = args.source.resolve()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")
    output.mkdir(parents=True)

    source_info = json.loads((source / "meta/info.json").read_text(encoding="utf-8"))
    source_episodes = load_jsonl(source / "meta/episodes.jsonl")
    source_tasks = load_jsonl(source / "meta/tasks.jsonl")
    source_pattern = source_info["data_path"]
    fps = int(source_info["fps"])
    source_task_to_index = {row["task"]: int(row["task_index"]) for row in source_tasks}

    task_strings = [
        row["task"] for row in sorted(source_tasks, key=lambda row: row["task_index"])
    ]
    subtask_to_index: dict[str, int] = {}
    for pair in COMPOSITE_SUBTASKS.values():
        for prompt in pair:
            if prompt not in subtask_to_index:
                subtask_to_index[prompt] = len(task_strings)
                task_strings.append(prompt)

    output_pattern = "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet"
    output_episodes: list[dict] = []
    appended_segments: list[tuple[int, int, str]] = []
    cut_manifest: list[dict] = []
    dataset_offset = 0

    for source_meta in source_episodes:
        source_episode = int(source_meta["episode_index"])
        source_path = data_path(source, source_episode, source_pattern)
        task_index = source_task_to_index[source_meta["tasks"][0]]
        destination = data_path(output, source_episode, output_pattern)

        if task_index not in COMPOSITE_SUBTASKS:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.link(source_path, destination)
            length = int(source_meta["length"])
            task_names = list(source_meta["tasks"])
        else:
            table = pq.read_table(source_path)
            cut = first_release_cut(table, args.min_closed_frames)
            first_prompt, second_prompt = COMPOSITE_SUBTASKS[task_index]
            first_table = relabel_segment(
                table.slice(0, cut),
                episode_index=source_episode,
                task_index=subtask_to_index[first_prompt],
                reset_time=False,
                fps=fps,
            )
            second_table = table.slice(cut)
            write_table(first_table, destination)
            length = len(first_table)
            task_names = [first_prompt]
            appended_segments.append((source_episode, cut, second_prompt))
            cut_manifest.append(
                {
                    "source_episode_index": source_episode,
                    "source_task_index": task_index,
                    "source_length": len(table),
                    "cut_exclusive": cut,
                    "first_length": len(first_table),
                    "second_length": len(second_table),
                    "first_prompt": first_prompt,
                    "second_prompt": second_prompt,
                }
            )

        output_episodes.append(
            {
                "episode_index": source_episode,
                "tasks": task_names,
                "length": length,
                "data/chunk_index": source_episode // 1000,
                "data/file_index": source_episode % 1000,
                "dataset_from_index": dataset_offset,
                "dataset_to_index": dataset_offset + length,
                "meta/episodes/chunk_index": 0,
                "meta/episodes/file_index": 0,
            }
        )
        dataset_offset += length

    next_episode = len(source_episodes)
    for source_episode, cut, second_prompt in appended_segments:
        new_episode = next_episode
        next_episode += 1
        source_path = data_path(source, source_episode, source_pattern)
        second_table = pq.read_table(source_path).slice(cut)
        second_table = relabel_segment(
            second_table,
            episode_index=new_episode,
            task_index=subtask_to_index[second_prompt],
            reset_time=True,
            fps=fps,
        )
        destination = data_path(output, new_episode, output_pattern)
        write_table(second_table, destination)
        length = len(second_table)
        output_episodes.append(
            {
                "episode_index": new_episode,
                "tasks": [second_prompt],
                "length": length,
                "data/chunk_index": new_episode // 1000,
                "data/file_index": new_episode % 1000,
                "dataset_from_index": dataset_offset,
                "dataset_to_index": dataset_offset + length,
                "meta/episodes/chunk_index": 0,
                "meta/episodes/file_index": 0,
                "source_episode_index": source_episode,
            }
        )
        dataset_offset += length

    if dataset_offset != int(source_info["total_frames"]):
        source_frames = source_info["total_frames"]
        raise AssertionError(
            f"Frame count changed: source={source_frames}, output={dataset_offset}"
        )

    info = dict(source_info)
    info["codebase_version"] = "v3.0"
    info["total_episodes"] = len(output_episodes)
    info["total_frames"] = dataset_offset
    info["total_tasks"] = len(task_strings)
    info["splits"] = {"train": f"0:{len(output_episodes)}"}
    info.pop("total_chunks", None)
    info.pop("total_videos", None)
    info["data_files_size_in_mb"] = 512
    info["video_files_size_in_mb"] = 512
    info["data_path"] = output_pattern
    info["video_path"] = None
    info["features"] = {
        FEATURE_RENAMES.get(key, key): value for key, value in info["features"].items()
    }
    for feature in info["features"].values():
        feature["fps"] = fps

    meta = output / "meta"
    meta.mkdir(parents=True, exist_ok=True)
    (meta / "info.json").write_text(json.dumps(info, indent=4) + "\n", encoding="utf-8")
    source_stats = json.loads((source / "meta/stats.json").read_text(encoding="utf-8"))
    output_stats = {
        FEATURE_RENAMES.get(key, key): value for key, value in source_stats.items()
    }
    (meta / "stats.json").write_text(
        json.dumps(output_stats, indent=4) + "\n", encoding="utf-8"
    )

    task_frame = pd.DataFrame(
        {"task_index": range(len(task_strings))},
        index=pd.Index(task_strings, name="task"),
    )
    task_frame.to_parquet(meta / "tasks.parquet")

    episodes_dir = meta / "episodes/chunk-000"
    episodes_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(output_episodes).to_parquet(
        episodes_dir / "file-000.parquet", index=False
    )
    (meta / "subtask_cuts.jsonl").write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in cut_manifest),
        encoding="utf-8",
    )
    (output / "README.md").write_text(
        "# LIBERO subtask PI0.5 dataset\n\n"
        "Derived locally from the official HuggingFaceVLA/libero expert "
        "demonstrations. Atomic episodes are hard-linked; composite LIBERO-Long "
        "demonstrations are split at the first verified object release and "
        "relabeled with one executable subtask.\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "source_episodes": len(source_episodes),
                "composite_source_episodes": len(appended_segments),
                "output_episodes": len(output_episodes),
                "frames": dataset_offset,
                "task_labels": len(task_strings),
                "output": str(output),
            },
            indent=2,
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-closed-frames", type=int, default=30)
    return parser.parse_args()


if __name__ == "__main__":
    build(parse_args())
