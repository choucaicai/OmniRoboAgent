"""Reusable inference interfaces for embedding SpatialLM in other programs."""

from __future__ import annotations

import json
import math
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Sequence

import numpy as np
import open3d as o3d
import torch
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TextIteratorStreamer,
    set_seed,
)

from spatiallm.layout.layout import Layout
from spatiallm.pcd import Compose, cleanup_pcd, get_points_and_colors, load_o3d_pcd


DETECT_TYPE_PROMPT = {
    "all": "Detect walls, doors, windows, boxes.",
    "arch": "Detect walls, doors, windows.",
    "object": "Detect boxes.",
}


def preprocess_point_cloud(
    points: np.ndarray,
    colors: np.ndarray,
    grid_size: float,
    num_bins: int,
) -> torch.Tensor:
    """Convert XYZ/RGB arrays to the tensor format expected by SpatialLM."""
    transform = Compose(
        [
            dict(type="PositiveShift"),
            dict(type="NormalizeColor"),
            dict(
                type="GridSample",
                grid_size=grid_size,
                hash_type="fnv",
                mode="test",
                keys=("coord", "color"),
                return_grid_coord=True,
                max_grid_coord=num_bins,
            ),
        ]
    )
    point_cloud = transform(
        {
            "name": "pcd",
            "coord": points.copy(),
            "color": colors.copy(),
        }
    )
    features = np.concatenate(
        [
            point_cloud["grid_coord"],
            point_cloud["coord"],
            point_cloud["color"],
        ],
        axis=1,
    )
    return torch.as_tensor(np.stack([features], axis=0))


def _task_prompt(detect_type: str, categories: Sequence[str]) -> str:
    if detect_type not in DETECT_TYPE_PROMPT:
        choices = ", ".join(DETECT_TYPE_PROMPT)
        raise ValueError(f"detect_type must be one of: {choices}")

    task_prompt = DETECT_TYPE_PROMPT[detect_type]
    if detect_type != "arch" and categories:
        task_prompt = task_prompt.replace("boxes", ", ".join(categories))

    return task_prompt


def generate_layout(
    model,
    point_cloud: torch.Tensor,
    tokenizer,
    code_template_file: str | Path,
    top_k: int = 10,
    top_p: float = 0.95,
    temperature: float = 0.6,
    num_beams: int = 1,
    seed: int = -1,
    max_new_tokens: int = 4096,
    detect_type: str = "all",
    categories: Sequence[str] | None = None,
    stream_output: bool = False,
) -> Layout:
    """Run model generation and return a metric-space ``Layout``.

    The returned layout is still relative to the positive-shifted point cloud.
    Callers must translate it by the original point cloud's minimum XYZ extent.
    """
    categories = list(categories or [])
    task_prompt = _task_prompt(detect_type, categories)

    if seed >= 0:
        set_seed(seed)

    with open(code_template_file, "r", encoding="utf-8") as file:
        code_template = file.read()

    prompt = (
        "<|point_start|><|point_pad|><|point_end|>"
        f"{task_prompt} The reference code is as followed: {code_template}"
    )
    if model.config.model_type == "spatiallm_qwen":
        conversation = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ]
    else:
        conversation = [{"role": "user", "content": prompt}]

    input_ids = tokenizer.apply_chat_template(
        conversation,
        add_generation_prompt=True,
        return_tensors="pt",
    ).to(model.device)
    attention_mask = torch.ones_like(input_ids, device=model.device)
    pad_token_id = tokenizer.pad_token_id
    if pad_token_id is None:
        pad_token_id = tokenizer.eos_token_id

    generate_kwargs = {
        "input_ids": input_ids,
        "attention_mask": attention_mask,
        "point_clouds": point_cloud,
        "max_new_tokens": max_new_tokens,
        "do_sample": True,
        "use_cache": True,
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "num_beams": num_beams,
        "pad_token_id": pad_token_id,
        "eos_token_id": tokenizer.eos_token_id,
    }

    if stream_output:
        streamer = TextIteratorStreamer(
            tokenizer,
            timeout=20.0,
            skip_prompt=True,
            skip_special_tokens=True,
        )
        generate_kwargs["streamer"] = streamer
        errors: list[BaseException] = []

        def run_generation():
            try:
                model.generate(**generate_kwargs)
            except BaseException as error:  # Propagate worker failures to the caller.
                errors.append(error)
                streamer.end()

        thread = Thread(target=run_generation)
        thread.start()
        generated_chunks = []
        for text in streamer:
            generated_chunks.append(text)
            print(text, end="", flush=True)
        thread.join()
        if errors:
            raise RuntimeError("SpatialLM generation failed") from errors[0]
        layout_text = "".join(generated_chunks)
    else:
        output_ids = model.generate(**generate_kwargs)
        generated_ids = output_ids[:, input_ids.shape[1] :]
        layout_text = tokenizer.batch_decode(
            generated_ids,
            skip_special_tokens=True,
        )[0]

    layout = Layout(layout_text)
    layout.undiscretize_and_unnormalize(
        num_bins=model.config.point_config["num_bins"]
    )
    return layout


def point_cloud_from_arrays(
    points: np.ndarray,
    colors: np.ndarray | None = None,
) -> o3d.geometry.PointCloud:
    """Build an in-memory Open3D point cloud from framework-provided arrays.

    ``points`` may contain XYZ only with shape ``(N, 3)``, or packed XYZRGB(A)
    with shape ``(N, 6)``/``(N, 7)`` when ``colors`` is omitted. Coordinates
    use meters. Colors may be uint8-like RGB in [0, 255] or floating-point RGB
    in [0, 1]. RGBA input is accepted and its alpha channel is discarded.
    """
    packed_array = np.asarray(points)
    if packed_array.ndim != 2:
        raise ValueError("points must have shape (N, 3), (N, 6), or (N, 7)")
    if colors is None and packed_array.shape[1] in (6, 7):
        colors = packed_array[:, 3:]
        packed_array = packed_array[:, :3]
    if packed_array.shape[1] != 3:
        raise ValueError("points must have shape (N, 3), (N, 6), or (N, 7)")

    points_array = packed_array.astype(np.float64, copy=False)
    if len(points_array) == 0:
        raise ValueError("points must not be empty")

    if colors is None:
        colors_array = np.zeros((len(points_array), 3), dtype=np.float64)
    else:
        colors_array = np.asarray(colors)
        if colors_array.ndim != 2 or colors_array.shape[0] != len(points_array):
            raise ValueError("colors must have shape (N, 3) or (N, 4)")
        if colors_array.shape[1] not in (3, 4):
            raise ValueError("colors must have shape (N, 3) or (N, 4)")
        colors_array = colors_array[:, :3].astype(np.float64, copy=False)

    valid_rows = np.isfinite(points_array).all(axis=1)
    valid_rows &= np.isfinite(colors_array).all(axis=1)
    points_array = points_array[valid_rows]
    colors_array = colors_array[valid_rows]
    if len(points_array) == 0:
        raise ValueError("point cloud has no finite points")

    if colors_array.size and colors_array.min() >= 0 and colors_array.max() <= 1.0:
        colors_array = colors_array * 255.0
    colors_array = np.clip(colors_array, 0.0, 255.0)

    point_cloud = o3d.geometry.PointCloud()
    point_cloud.points = o3d.utility.Vector3dVector(points_array)
    point_cloud.colors = o3d.utility.Vector3dVector(colors_array / 255.0)
    return point_cloud


def _number(value: Any, precision: int | None) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("layout contains a non-finite numeric value")
    return round(number, precision) if precision is not None else number


def layout_to_dict(
    layout: Layout,
    *,
    default_wall_thickness: float | None = None,
    precision: int | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Convert a SpatialLM ``Layout`` to the framework JSON schema."""

    def vector(*values):
        return [_number(value, precision) for value in values]

    walls = []
    for wall in layout.walls:
        thickness_value = float(wall.thickness)
        if default_wall_thickness is not None and thickness_value <= 0:
            thickness_value = default_wall_thickness
        thickness = _number(thickness_value, precision)
        walls.append(
            {
                "id": f"wall_{wall.id}",
                "a": vector(wall.ax, wall.ay, wall.az),
                "b": vector(wall.bx, wall.by, wall.bz),
                "height": _number(wall.height, precision),
                "thickness": thickness,
            }
        )

    def fixture_to_dict(fixture):
        return {
            "id": f"{fixture.entity_label}_{fixture.id}",
            "wall_id": f"wall_{fixture.wall_id}",
            "center": vector(
                fixture.position_x,
                fixture.position_y,
                fixture.position_z,
            ),
            "width": _number(fixture.width, precision),
            "height": _number(fixture.height, precision),
        }

    objects = [
        {
            "id": f"object_{bbox.id}",
            "class_name": bbox.class_name,
            "center": vector(
                bbox.position_x,
                bbox.position_y,
                bbox.position_z,
            ),
            "angle_z": _number(bbox.angle_z, precision),
            "size": vector(bbox.scale_x, bbox.scale_y, bbox.scale_z),
        }
        for bbox in layout.bboxes
    ]

    return {
        "walls": walls,
        "doors": [fixture_to_dict(door) for door in layout.doors],
        "windows": [fixture_to_dict(window) for window in layout.windows],
        "objects": objects,
    }


def layout_to_json(
    layout: Layout,
    *,
    default_wall_thickness: float | None = None,
    precision: int | None = None,
    indent: int | None = None,
) -> str:
    """Serialize a SpatialLM ``Layout`` using the framework JSON schema."""
    payload = layout_to_dict(
        layout,
        default_wall_thickness=default_wall_thickness,
        precision=precision,
    )
    return json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        indent=indent,
    )


class SpatialLMInference:
    """Long-lived SpatialLM inference adapter for third-party frameworks."""

    def __init__(
        self,
        model_path: str | Path,
        *,
        code_template_file: str | Path | None = None,
        device: str = "cuda",
        inference_dtype: str | torch.dtype = "bfloat16",
        cleanup: bool = True,
        default_wall_thickness: float | None = None,
        output_precision: int | None = None,
    ):
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError("CUDA was requested but is not available")
        if isinstance(inference_dtype, str):
            try:
                inference_dtype = getattr(torch, inference_dtype)
            except AttributeError as error:
                raise ValueError(f"unknown torch dtype: {inference_dtype}") from error

        repo_root = Path(__file__).resolve().parents[1]
        self.code_template_file = Path(
            code_template_file or repo_root / "code_template.txt"
        )
        if not self.code_template_file.is_file():
            raise FileNotFoundError(self.code_template_file)

        self.device = device
        self.cleanup = cleanup
        self.default_wall_thickness = default_wall_thickness
        self.output_precision = output_precision
        self._generation_lock = Lock()

        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path))
        self.model = AutoModelForCausalLM.from_pretrained(
            str(model_path),
            torch_dtype=inference_dtype,
        )
        self.model.to(device)
        self.model.set_point_backbone_dtype(torch.float32)
        self.model.eval()

        self.num_bins = self.model.config.point_config["num_bins"]
        self.grid_size = Layout.get_grid_size(self.num_bins)

    def infer_ply_layout(self, ply_path: str | Path, **generation_options) -> Layout:
        """Infer a ``Layout`` from a PLY file without writing temporary files."""
        ply_path = Path(ply_path)
        if not ply_path.is_file():
            raise FileNotFoundError(ply_path)
        point_cloud = load_o3d_pcd(str(ply_path))
        if len(point_cloud.points) == 0:
            raise ValueError(f"PLY contains no readable points: {ply_path}")
        return self._infer_point_cloud(point_cloud, **generation_options)

    def infer_points_layout(
        self,
        points: np.ndarray,
        colors: np.ndarray | None = None,
        **generation_options,
    ) -> Layout:
        """Infer a ``Layout`` directly from in-memory XYZ/RGB arrays."""
        point_cloud = point_cloud_from_arrays(points, colors)
        return self._infer_point_cloud(point_cloud, **generation_options)

    def infer_ply(
        self,
        ply_path: str | Path,
        **generation_options,
    ) -> dict[str, list[dict[str, Any]]]:
        """Infer from PLY and return a JSON-compatible dictionary."""
        return self._layout_dict(
            self.infer_ply_layout(ply_path, **generation_options)
        )

    def infer_points(
        self,
        points: np.ndarray,
        colors: np.ndarray | None = None,
        **generation_options,
    ) -> dict[str, list[dict[str, Any]]]:
        """Infer from arrays and return a JSON-compatible dictionary."""
        return self._layout_dict(
            self.infer_points_layout(points, colors, **generation_options)
        )

    def infer_ply_json(
        self,
        ply_path: str | Path,
        *,
        indent: int | None = None,
        **generation_options,
    ) -> str:
        """Infer from PLY and return a JSON string."""
        return self._layout_json(
            self.infer_ply_layout(ply_path, **generation_options),
            indent=indent,
        )

    def infer_points_json(
        self,
        points: np.ndarray,
        colors: np.ndarray | None = None,
        *,
        indent: int | None = None,
        **generation_options,
    ) -> str:
        """Infer from arrays and return a JSON string."""
        return self._layout_json(
            self.infer_points_layout(points, colors, **generation_options),
            indent=indent,
        )

    def _infer_point_cloud(
        self,
        point_cloud: o3d.geometry.PointCloud,
        *,
        detect_type: str = "all",
        categories: Sequence[str] | None = None,
        seed: int = 42,
        top_k: int = 10,
        top_p: float = 0.95,
        temperature: float = 0.6,
        num_beams: int = 1,
        max_new_tokens: int = 4096,
        cleanup: bool | None = None,
    ) -> Layout:
        do_cleanup = self.cleanup if cleanup is None else cleanup
        if do_cleanup:
            point_cloud = cleanup_pcd(point_cloud, voxel_size=self.grid_size)

        points, colors = get_points_and_colors(point_cloud)
        if len(points) == 0:
            raise ValueError("point cloud contains no points after preprocessing")

        min_extent = np.min(points, axis=0)
        point_tensor = preprocess_point_cloud(
            points,
            colors,
            grid_size=self.grid_size,
            num_bins=self.num_bins,
        )

        # set_seed and model.generate both mutate/shared state. Keep one request on
        # a model instance at a time so a framework can safely call this adapter
        # from multiple request threads.
        with self._generation_lock, torch.inference_mode():
            layout = generate_layout(
                self.model,
                point_tensor,
                self.tokenizer,
                self.code_template_file,
                top_k=top_k,
                top_p=top_p,
                temperature=temperature,
                num_beams=num_beams,
                seed=seed,
                max_new_tokens=max_new_tokens,
                detect_type=detect_type,
                categories=categories,
                stream_output=False,
            )

        # PositiveShift makes coordinates relative to the point-cloud minimum.
        # Restore the original framework coordinate system before serialization.
        layout.translate(min_extent)
        return layout

    def _layout_dict(self, layout: Layout):
        return layout_to_dict(
            layout,
            default_wall_thickness=self.default_wall_thickness,
            precision=self.output_precision,
        )

    def _layout_json(self, layout: Layout, *, indent: int | None):
        return layout_to_json(
            layout,
            default_wall_thickness=self.default_wall_thickness,
            precision=self.output_precision,
            indent=indent,
        )


__all__ = [
    "SpatialLMInference",
    "generate_layout",
    "layout_to_dict",
    "layout_to_json",
    "point_cloud_from_arrays",
    "preprocess_point_cloud",
]
