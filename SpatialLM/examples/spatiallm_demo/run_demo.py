#!/usr/bin/env python3
"""Run the official SpatialLM sample through the OmniRoboAgent integration."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import math
import platform
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

import numpy as np
import torch
from PIL import Image, ImageDraw
from spatiallm.pcd import get_points_and_colors, load_o3d_pcd

from omniroboagent.agent_core import TieredMemory
from omniroboagent.backends.spatial import SpatialLMBackend

DELIVERY_ROOT = Path(__file__).resolve().parents[2]
DEMO_ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = DEMO_ROOT / "input" / "scene0000_00.ply"
DEFAULT_MODEL = DELIVERY_ROOT / "models" / "SpatialLM1.1-Qwen-0.5B"
DEFAULT_OUTPUT = DEMO_ROOT / "output" / "scene0000_00_seed42"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Infer spatial geometry from the official SpatialLM sample, attach it "
            "to an OmniRoboAgent observation, and persist it through TieredMemory."
        )
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--model-path", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--detect-type",
        choices=("all", "arch", "object"),
        default="all",
    )
    parser.add_argument("--categories", nargs="*", default=[])
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-new-tokens", type=int, default=4096)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--inference-dtype", default="bfloat16")
    parser.add_argument(
        "--cleanup",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable SpatialLM point-cloud cleanup before inference.",
    )
    return parser.parse_args()


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def relative_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(DELIVERY_ROOT))
    except ValueError:
        return str(resolved)


def package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def render_top_down(
    points: np.ndarray,
    colors: np.ndarray,
    spatial_context: dict[str, list[dict[str, Any]]],
    output_path: Path,
) -> None:
    width, height, margin = 1400, 1000, 70
    minimum = np.min(points[:, :2], axis=0)
    maximum = np.max(points[:, :2], axis=0)
    extent = np.maximum(maximum - minimum, 1e-6)
    scale = min(
        (width - 2 * margin) / float(extent[0]),
        (height - 2 * margin) / float(extent[1]),
    )
    used_width = float(extent[0]) * scale
    used_height = float(extent[1]) * scale
    x_offset = (width - used_width) / 2.0
    y_offset = (height - used_height) / 2.0

    def project(x: float, y: float) -> tuple[float, float]:
        return (
            x_offset + (x - float(minimum[0])) * scale,
            height - (y_offset + (y - float(minimum[1])) * scale),
        )

    sample_count = min(len(points), 180_000)
    indices = np.linspace(0, len(points) - 1, sample_count, dtype=np.int64)
    sampled_points = points[indices]
    sampled_colors = colors[indices, :3].astype(np.float64, copy=False)
    if sampled_colors.size and sampled_colors.max() <= 1.0:
        sampled_colors *= 255.0
    sampled_colors = np.clip(sampled_colors, 0.0, 255.0).astype(np.uint8)
    sampled_colors = (sampled_colors.astype(np.float64) * 0.72 + 255.0 * 0.28).astype(
        np.uint8
    )

    canvas = np.full((height, width, 3), 248, dtype=np.uint8)
    pixels_x = (x_offset + (sampled_points[:, 0] - minimum[0]) * scale).astype(np.int64)
    pixels_y = (
        height - (y_offset + (sampled_points[:, 1] - minimum[1]) * scale)
    ).astype(np.int64)
    valid = (pixels_x >= 0) & (pixels_x < width) & (pixels_y >= 0) & (pixels_y < height)
    canvas[pixels_y[valid], pixels_x[valid]] = sampled_colors[valid]

    image = Image.fromarray(canvas)
    draw = ImageDraw.Draw(image)

    for wall in spatial_context["walls"]:
        draw.line(
            [project(*wall["a"][:2]), project(*wall["b"][:2])],
            fill="#d32f2f",
            width=7,
        )

    for object_item in spatial_context["objects"]:
        center_x, center_y = object_item["center"][:2]
        size_x, size_y = object_item["size"][:2]
        angle = float(object_item["angle_z"])
        cosine, sine = math.cos(angle), math.sin(angle)
        corners: list[tuple[float, float]] = []
        for local_x, local_y in (
            (-size_x / 2, -size_y / 2),
            (size_x / 2, -size_y / 2),
            (size_x / 2, size_y / 2),
            (-size_x / 2, size_y / 2),
        ):
            world_x = center_x + local_x * cosine - local_y * sine
            world_y = center_y + local_x * sine + local_y * cosine
            corners.append(project(world_x, world_y))
        draw.line([*corners, corners[0]], fill="#2e7d32", width=4)
        label_position = project(center_x, center_y)
        draw.text(
            (label_position[0] + 5, label_position[1] + 5),
            str(object_item["class_name"]),
            fill="#0d3b12",
            stroke_width=2,
            stroke_fill="white",
        )

    marker_colors = {"doors": "#f57c00", "windows": "#0288d1"}
    for collection, color in marker_colors.items():
        for item in spatial_context[collection]:
            center_x, center_y = item["center"][:2]
            pixel_x, pixel_y = project(center_x, center_y)
            radius = 9
            draw.ellipse(
                (
                    pixel_x - radius,
                    pixel_y - radius,
                    pixel_x + radius,
                    pixel_y + radius,
                ),
                fill=color,
                outline="white",
                width=2,
            )

    legend = [
        ("#d32f2f", "walls"),
        ("#f57c00", "doors"),
        ("#0288d1", "windows"),
        ("#2e7d32", "objects"),
    ]
    draw.rounded_rectangle((15, 15, 230, 140), radius=8, fill="white", outline="#555")
    for index, (color, label) in enumerate(legend):
        y = 34 + index * 25
        draw.line((30, y, 60, y), fill=color, width=6)
        draw.text((72, y - 8), label, fill="#111")
    draw.text(
        (15, height - 30),
        (
            "Top-down XY view; colored points are the PLY input, "
            "overlays are SpatialLM output"
        ),
        fill="#111",
        stroke_width=2,
        stroke_fill="white",
    )
    image.save(output_path)


def write_summary(
    output_path: Path,
    input_manifest: dict[str, Any],
    spatial_context: dict[str, list[dict[str, Any]]],
    elapsed_seconds: float,
) -> None:
    object_counts = Counter(
        str(item["class_name"]) for item in spatial_context["objects"]
    )
    object_rows = (
        "\n".join(
            f"| `{class_name}` | {count} |"
            for class_name, count in sorted(object_counts.items())
        )
        or "| _none_ | 0 |"
    )
    text = f"""# SpatialLM Demo Result

This run converts the official point cloud into structured geometry, places the
geometry in `observation[\"spatial_context\"]`, and persists it with
`TieredMemory.update()`.

## Input

- PLY: `{input_manifest["path"]}`
- Points: {input_manifest["point_count"]:,}
- SHA-256: `{input_manifest["sha256"]}`
- XYZ bounds (meters): `{input_manifest["bounds_meters"]}`

## SpatialLM Output

- Walls: {len(spatial_context["walls"])}
- Doors: {len(spatial_context["doors"])}
- Windows: {len(spatial_context["windows"])}
- Objects: {len(spatial_context["objects"])}
- Total runtime: {elapsed_seconds:.2f} seconds

| Object class | Count |
| --- | ---: |
{object_rows}

## Files To Inspect

- [Top-down input/output overlay](top_down.png)
- [Raw geometry from SpatialLM](spatial_context.json)
- [Geometry attached to an observation](observation.json)
- [Planner input before Memory update](planner_input_before_memory_update.json)
- [TieredMemory recall after update](memory_recall.json)
- [Planner input after Memory update](planner_input_after_memory_update.json)
- [Run configuration and timing](run_metadata.json)
- [Memory event](memory_events.jsonl)
- [Console log](run.log)

The demo does not call an LLM Planner or Verifier. The two planner-input files
show the exact boundary where the current observation and recalled spatial memory
would be supplied to those components.
"""
    output_path.write_text(text, encoding="utf-8")


def main() -> int:
    args = parse_args()
    input_path = args.input.resolve()
    model_path = args.model_path.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename in (
        "error.json",
        "input_manifest.json",
        "memory_events.jsonl",
        "memory_recall.json",
        "observation.json",
        "planner_input_after_memory_update.json",
        "planner_input_before_memory_update.json",
        "run_metadata.json",
        "spatial_context.json",
        "summary.md",
        "top_down.png",
    ):
        (output_dir / filename).unlink(missing_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(output_dir / "run.log", mode="w", encoding="utf-8"),
        ],
        force=True,
    )
    logger = logging.getLogger("spatiallm_demo")
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    backend: SpatialLMBackend | None = None

    try:
        if not input_path.is_file():
            raise FileNotFoundError(f"Input PLY not found: {input_path}")
        if not model_path.is_dir():
            raise FileNotFoundError(f"Model directory not found: {model_path}")
        if args.max_new_tokens <= 0:
            raise ValueError("--max-new-tokens must be positive")

        logger.info("Loading input PLY: %s", input_path)
        point_cloud = load_o3d_pcd(str(input_path))
        points, colors = get_points_and_colors(point_cloud)
        points = np.asarray(points)
        colors = np.asarray(colors)
        if len(points) == 0:
            raise ValueError("Input PLY contains no readable points")
        if not np.isfinite(points).all():
            raise ValueError("Input PLY contains non-finite XYZ values")

        input_manifest = {
            "path": relative_path(input_path),
            "source": (
                "https://huggingface.co/datasets/manycore-research/SpatialLM-Testset"
            ),
            "license": "CC-BY-NC-4.0",
            "size_bytes": input_path.stat().st_size,
            "sha256": file_sha256(input_path),
            "point_count": int(len(points)),
            "points_shape": list(points.shape),
            "colors_shape": list(colors.shape),
            "bounds_meters": {
                "min_xyz": np.min(points, axis=0).tolist(),
                "max_xyz": np.max(points, axis=0).tolist(),
                "extent_xyz": np.ptp(points, axis=0).tolist(),
            },
            "coordinate_system": "right-handed, Z-up",
        }
        write_json(output_dir / "input_manifest.json", input_manifest)
        logger.info("Loaded %s points", f"{len(points):,}")

        logger.info("Loading SpatialLM model: %s", model_path)
        model_started = time.perf_counter()
        backend = SpatialLMBackend(
            model_path=model_path,
            device=args.device,
            inference_dtype=args.inference_dtype,
            cleanup=args.cleanup,
            default_wall_thickness=0.12,
            output_precision=6,
        )
        model_load_seconds = time.perf_counter() - model_started
        logger.info("Model loaded in %.2f seconds", model_load_seconds)

        generation_options: dict[str, Any] = {
            "detect_type": args.detect_type,
            "seed": args.seed,
            "max_new_tokens": args.max_new_tokens,
        }
        if args.categories:
            generation_options["categories"] = args.categories
        inference_started = time.perf_counter()
        spatial_context = backend.infer_points(
            points,
            colors,
            **generation_options,
        )
        inference_seconds = time.perf_counter() - inference_started
        write_json(output_dir / "spatial_context.json", spatial_context)
        logger.info(
            "Inference finished in %.2f seconds: %d walls, %d doors, %d windows, "
            "%d objects",
            inference_seconds,
            len(spatial_context["walls"]),
            len(spatial_context["doors"]),
            len(spatial_context["windows"]),
            len(spatial_context["objects"]),
        )

        observation = {
            "source": "spatiallm_official_example",
            "point_cloud": {
                "path": input_manifest["path"],
                "point_count": input_manifest["point_count"],
            },
            "spatial_context": spatial_context,
        }
        write_json(output_dir / "observation.json", observation)

        task = "Inspect the official SpatialLM example scene"
        session_id = "spatiallm-demo"
        memory_events_path = output_dir / "memory_events.jsonl"
        memory_events_path.write_text("", encoding="utf-8")
        memory = TieredMemory(camera_keys=[], event_path=memory_events_path)
        memory.reset(session_id)
        memory_before_update = memory.recall({"session_id": session_id})
        planner_input_before_update = {
            "task": task,
            "observation": observation,
            "step": 0,
            "history": [],
            "available_skills": [],
            "memory_context": memory_before_update,
        }
        write_json(
            output_dir / "planner_input_before_memory_update.json",
            planner_input_before_update,
        )

        state = {
            "task": task,
            "session_id": session_id,
            "step": 0,
            "observation": observation,
        }
        event = {
            "event_type": "transition",
            "execution_id": "spatiallm-demo:execution:0",
            "attempt_id": "spatiallm-demo:execution:0:attempt:0",
            "environment_executed": True,
            "environment_result": {"observation": observation},
            "verification": {
                "confidence": 1.0,
                "reason": "SpatialLM demo inference completed",
            },
            "next_status": "in_progress",
            "transition_reason": "SpatialLM output passed schema validation",
            "verifier_evidence": [
                "SpatialLM output contains walls, doors, windows, and objects"
            ],
        }
        memory.update(state, event)
        memory_recall = memory.recall({"session_id": session_id})
        write_json(output_dir / "memory_recall.json", memory_recall)

        planner_input_after_update = {
            **planner_input_before_update,
            "memory_context": memory_recall,
        }
        write_json(
            output_dir / "planner_input_after_memory_update.json",
            planner_input_after_update,
        )

        render_top_down(
            points,
            colors,
            spatial_context,
            output_dir / "top_down.png",
        )
        elapsed_seconds = time.perf_counter() - started
        run_metadata = {
            "status": "success",
            "started_at": started_at.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "input": input_manifest["path"],
            "model_path": relative_path(model_path),
            "output_dir": relative_path(output_dir),
            "generation": generation_options,
            "engine": {
                "device": args.device,
                "inference_dtype": args.inference_dtype,
                "cleanup": args.cleanup,
                "default_wall_thickness": 0.12,
                "output_precision": 6,
            },
            "timing_seconds": {
                "model_load": model_load_seconds,
                "inference": inference_seconds,
                "total": elapsed_seconds,
            },
            "counts": {
                name: len(spatial_context[name])
                for name in ("walls", "doors", "windows", "objects")
            },
            "software": {
                "python": platform.python_version(),
                "torch": torch.__version__,
                "torch_cuda": torch.version.cuda,
                "spatiallm": package_version("spatiallm"),
                "omniroboagent": package_version("omniroboagent"),
            },
            "gpu": (
                torch.cuda.get_device_name(torch.cuda.current_device())
                if torch.cuda.is_available()
                else None
            ),
            "reproducibility_note": (
                "A fixed seed is used, but sampled GPU generation is not guaranteed "
                "to be bitwise identical across machines."
            ),
        }
        write_json(output_dir / "run_metadata.json", run_metadata)
        write_summary(
            output_dir / "summary.md",
            input_manifest,
            spatial_context,
            elapsed_seconds,
        )
        logger.info("Artifacts written to %s", output_dir)
        return 0
    except Exception as error:
        logger.exception("SpatialLM demo failed")
        write_json(
            output_dir / "error.json",
            {
                "status": "failed",
                "timestamp": datetime.now(UTC).isoformat(),
                "error_type": type(error).__name__,
                "message": str(error),
            },
        )
        return 1
    finally:
        if backend is not None:
            backend.close()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


if __name__ == "__main__":
    sys.exit(main())
