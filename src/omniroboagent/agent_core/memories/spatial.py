from collections import deque
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from copy import deepcopy
from dataclasses import dataclass
from json import dump
from math import acos, degrees, floor, isfinite, sqrt
from numbers import Integral, Real
from pathlib import Path
from struct import pack
from tempfile import NamedTemporaryFile
from threading import RLock
from typing import Any

from omniroboagent.agent_core.memories.base import Memory
from omniroboagent.backends.spatial import SpatialLMBackend
from omniroboagent.backends.spatial.ply import load_ply_points_colors

_Z_UP_COORDINATE_CONVENTION = "x_right_y_forward_z_up"
_SPATIAL_DETECT_TYPES = {"all", "arch", "object"}


def _empty_spatial_context() -> dict[str, list[dict[str, Any]]]:
    return {"walls": [], "doors": [], "windows": [], "objects": []}


@dataclass
class _Voxel:
    x: float
    y: float
    z: float
    red: float
    green: float
    blue: float
    weight: int
    observation_count: int
    last_seen_ns: int

    def integrate(
            self,
            point: tuple[float, float, float],
            color: tuple[int, int, int],
            observation_count: int,
            timestamp_ns: int,
            max_weight: int,
    ) -> None:
        if self.weight < max_weight:
            self.weight += 1
            alpha = 1.0 / self.weight
        else:
            alpha = 1.0 / max_weight
        self.x += alpha * (point[0] - self.x)
        self.y += alpha * (point[1] - self.y)
        self.z += alpha * (point[2] - self.z)
        self.red += alpha * (color[0] - self.red)
        self.green += alpha * (color[1] - self.green)
        self.blue += alpha * (color[2] - self.blue)
        self.observation_count += observation_count
        self.last_seen_ns = timestamp_ns


class SpatialMemory(Memory):
    """Incrementally fuse meter-scale RGB-D frames into a voxel point map.

    RGB and depth must already be synchronized, registered and rectified. RGB pixels
    are interpreted as 0-255 values, depth is expressed in meters, and each absolute
    ``T_world_camera`` pose maps camera coordinates into the configured ``map_frame``.
    """

    def __init__(
        self,
        frame_buffer_size: int = 32,
        frame_key: str = "spatial_frames",
        map_frame: str = "map",
        voxel_size_m: float = 0.03,
        depth_min_m: float = 0.2,
        depth_max_m: float = 5.0,
        pixel_stride: int = 8,
        max_voxel_weight: int = 20,
        keyframe_translation_m: float = 0.05,
        keyframe_rotation_deg: float = 5.0,
        artifact_dir: str | Path | None = None,
        session_export_interval_keyframes: int | None = 10,
        spatial_backend: SpatialLMBackend | None = None,
        spatial_detect_type: str = "all",
        spatial_seed: int = 42,
    ) -> None:
        if (
            not isinstance(frame_buffer_size, int)
            or isinstance(frame_buffer_size, bool)
            or frame_buffer_size <= 0
        ):
            raise ValueError("frame_buffer_size must be positive")
        if not isinstance(frame_key, str) or not frame_key:
            raise ValueError("frame_key must be a non-empty string")
        if not isinstance(map_frame, str) or not map_frame:
            raise ValueError("map_frame must be a non-empty string")
        if (
            isinstance(voxel_size_m, bool)
            or not isinstance(voxel_size_m, Real)
            or not isfinite(float(voxel_size_m))
            or voxel_size_m <= 0
        ):
            raise ValueError("voxel_size_m must be positive")
        if (
            isinstance(depth_min_m, bool)
            or not isinstance(depth_min_m, Real)
            or not isfinite(float(depth_min_m))
            or depth_min_m < 0
        ):
            raise ValueError("depth_min_m must be finite and non-negative")
        if (
            isinstance(depth_max_m, bool)
            or not isinstance(depth_max_m, Real)
            or not isfinite(float(depth_max_m))
            or depth_max_m <= depth_min_m
        ):
            raise ValueError("depth_max_m must be finite and greater than depth_min_m")
        if (
            not isinstance(pixel_stride, int)
            or isinstance(pixel_stride, bool)
            or pixel_stride <= 0
        ):
            raise ValueError("pixel_stride must be positive")
        if (
            not isinstance(max_voxel_weight, int)
            or isinstance(max_voxel_weight, bool)
            or max_voxel_weight <= 0
        ):
            raise ValueError("max_voxel_weight must be positive")
        for name, value in (
            ("keyframe_translation_m", keyframe_translation_m),
            ("keyframe_rotation_deg", keyframe_rotation_deg),
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, Real)
                or not isfinite(float(value))
                or value < 0
            ):
                raise ValueError(f"{name} must be finite and non-negative")
        if session_export_interval_keyframes is not None and (
            not isinstance(session_export_interval_keyframes, int)
            or isinstance(session_export_interval_keyframes, bool)
            or session_export_interval_keyframes <= 0
        ):
            raise ValueError(
                "session_export_interval_keyframes must be positive or None"
            )
        if spatial_backend is not None and not isinstance(
            spatial_backend, SpatialLMBackend
        ):
            raise TypeError("spatial_backend must be a SpatialLMBackend or None")
        if (
            not isinstance(spatial_detect_type, str)
            or spatial_detect_type not in _SPATIAL_DETECT_TYPES
        ):
            choices = ", ".join(sorted(_SPATIAL_DETECT_TYPES))
            raise ValueError(f"spatial_detect_type must be one of: {choices}")
        if not isinstance(spatial_seed, Integral) or isinstance(spatial_seed, bool):
            raise ValueError("spatial_seed must be an integer")

        self.frame_buffer_size: int = frame_buffer_size
        self.frame_key: str = frame_key
        self.map_frame: str = map_frame
        self.voxel_size_m: float = float(voxel_size_m)
        self.depth_min_m: float = float(depth_min_m)
        self.depth_max_m: float = float(depth_max_m)
        self.pixel_stride: int = pixel_stride
        self.max_voxel_weight: int = max_voxel_weight
        self.keyframe_translation_m: float = float(keyframe_translation_m)
        self.keyframe_rotation_deg: float = float(keyframe_rotation_deg)
        self.artifact_dir: Path | None = (
            Path(artifact_dir) if artifact_dir is not None else None
        )
        self.session_export_interval_keyframes: int | None = (
            session_export_interval_keyframes
        )
        self.spatial_backend: SpatialLMBackend | None = spatial_backend
        self.spatial_detect_type: str = spatial_detect_type
        self.spatial_seed: int = int(spatial_seed)

        self.session_id: str | None = None
        self._frames: deque[dict[str, Any]] = deque(maxlen=frame_buffer_size)
        self._voxels: dict[tuple[int, int, int], _Voxel] = {}
        self._trajectory: list[dict[str, Any]] = []
        self._last_keyframe_poses: dict[str, list[list[float]]] = {}
        self._lock: AbstractContextManager[bool] = RLock()
        self._received_frame_count: int = 0
        self._integrated_keyframe_count: int = 0
        self._skipped_frame_count: int = 0
        self._map_revision: int = 0
        self._last_update_ns: int | None = None
        self._latest_camera_id: str | None = None
        self._latest_frame_id: str | None = None
        self._latest_integration: dict[str, Any] | None = None
        self._bounds_min: list[float] | None = None
        self._bounds_max: list[float] | None = None
        self._latest_ply_ref: str | None = None
        self._latest_ply_revision: int | None = None
        self._latest_manifest_ref: str | None = None
        self._latest_manifest_revision: int | None = None
        self._localization: dict[str, Any] = _empty_spatial_context()

    def reset(self, session_id: str) -> None:
        with self._lock:
            self.session_id = session_id
            self._frames.clear()
            self._voxels.clear()
            self._trajectory.clear()
            self._last_keyframe_poses.clear()
            self._received_frame_count = 0
            self._integrated_keyframe_count = 0
            self._skipped_frame_count = 0
            self._map_revision = 0
            self._last_update_ns = None
            self._latest_camera_id = None
            self._latest_frame_id = None
            self._latest_integration = None
            self._bounds_min = None
            self._bounds_max = None
            self._latest_ply_ref = None
            self._latest_ply_revision = None
            self._latest_manifest_ref = None
            self._latest_manifest_revision = None
            self._localization = _empty_spatial_context()

    def ingest(self, frame: Mapping[str, Any]) -> None:
        """Validate and incrementally fuse one synchronized RGB-D frame."""
        if not isinstance(frame, Mapping):
            raise TypeError("spatial frame must be a mapping")
        normalized = self._validate_frame(frame)
        with self._lock:
            self._frames.append(normalized)
            self._received_frame_count += 1
            self._last_update_ns = normalized["timestamp_ns"]
            self._latest_camera_id = normalized["camera_id"]
            self._latest_frame_id = normalized["frame_id"]

            if not self._is_keyframe_locked(normalized):
                self._skipped_frame_count += 1
                self._latest_integration = {
                    "status": "skipped_not_keyframe",
                    "timestamp_ns": normalized["timestamp_ns"],
                    "camera_id": normalized["camera_id"],
                }
                self._record_pose_locked(
                    normalized,
                    keyframe=False,
                    integration_status="skipped_not_keyframe",
                )
                return

            frame_voxels, sampled_point_count = self._back_project_frame(normalized)
            if not frame_voxels:
                self._skipped_frame_count += 1
                self._latest_integration = {
                    "status": "skipped_no_valid_depth",
                    "timestamp_ns": normalized["timestamp_ns"],
                    "camera_id": normalized["camera_id"],
                }
                self._record_pose_locked(
                    normalized,
                    keyframe=False,
                    integration_status="skipped_no_valid_depth",
                )
                return

            self._fuse_frame_voxels_locked(frame_voxels, normalized["timestamp_ns"])
            self._last_keyframe_poses[normalized["camera_id"]] = [
                list(row) for row in normalized["T_world_camera"]
            ]
            self._integrated_keyframe_count += 1
            self._map_revision += 1
            self._latest_integration = {
                "status": "integrated",
                "timestamp_ns": normalized["timestamp_ns"],
                "camera_id": normalized["camera_id"],
                "sampled_point_count": sampled_point_count,
                "frame_voxel_count": len(frame_voxels),
            }
            self._record_pose_locked(
                normalized,
                keyframe=True,
                integration_status="integrated",
            )
        if self.spatial_backend is not None:
            self.update_layout()
        if (
            self.artifact_dir is not None
            and self.session_export_interval_keyframes is not None
            and self._integrated_keyframe_count
            % self.session_export_interval_keyframes
            == 0
        ):
            self.export_session()

    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        environment_result = event.get("environment_result")
        observation = (
            environment_result.get("observation")
            if isinstance(environment_result, Mapping)
            else state.get("observation")
        )
        if not isinstance(observation, Mapping) or self.frame_key not in observation:
            return

        frames = observation[self.frame_key]
        if isinstance(frames, Mapping):
            self.ingest(frames)
            return
        if isinstance(frames, Sequence) and not isinstance(
            frames, (str, bytes, bytearray)
        ):
            for frame in frames:
                if not isinstance(frame, Mapping):
                    raise TypeError(f"{self.frame_key} items must be mappings")
                self.ingest(frame)
            return
        raise TypeError(f"observation[{self.frame_key!r}] must be a frame or sequence")

    def point_cloud(self) -> dict[str, Any]:
        """Return an explicit point-cloud snapshot; unlike recall, this can be large."""
        with self._lock:
            points, colors = self._point_cloud_locked()
            return {
                "map_revision": self._map_revision,
                "coordinate_frame": self.map_frame,
                "voxel_size_m": self.voxel_size_m,
                "points_xyz_m": points,
                "colors_rgb": colors,
            }

    def trajectory(self) -> dict[str, Any]:
        """Return pose metadata without retaining or exposing raw RGB-D arrays."""
        with self._lock:
            return {
                "schema_version": 1,
                "session_id": self.session_id,
                "coordinate_frame": self.map_frame,
                "transform_convention": "camera_to_map",
                "frame_count": len(self._trajectory),
                "integrated_keyframe_count": self._integrated_keyframe_count,
                "frames": deepcopy(self._trajectory),
            }

    def export_ply(self, path: str | Path | None = None) -> str:
        """Write a Z-up binary PLY without using PLY as the live map state."""
        snapshot = self.point_cloud()
        revision = int(snapshot["map_revision"])
        if path is None:
            if self.artifact_dir is None:
                raise ValueError("path is required when artifact_dir is not configured")
            target = self.artifact_dir / f"map_{revision:06d}.ply"
        else:
            target = Path(path)
        if target.suffix.lower() != ".ply":
            raise ValueError("PLY snapshot path must end with .ply")
        target.parent.mkdir(parents=True, exist_ok=True)

        points = self._points_to_z_up(snapshot["points_xyz_m"])
        colors = snapshot["colors_rgb"]
        if not points:
            raise ValueError("cannot export an empty point cloud")
        header = (
            "ply\n"
            "format binary_little_endian 1.0\n"
            f"element vertex {len(points)}\n"
            "property float x\n"
            "property float y\n"
            "property float z\n"
            "property uchar red\n"
            "property uchar green\n"
            "property uchar blue\n"
            "end_header\n"
        ).encode("ascii")
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="wb", dir=target.parent, prefix=f".{target.name}.", delete=False
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(header)
                for point, color in zip(points, colors, strict=True):
                    temporary.write(pack("<fffBBB", *point, *color))
            temporary_path.replace(target)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

        with self._lock:
            self._latest_ply_ref = str(target)
            self._latest_ply_revision = revision
        return str(target)

    def export_session(self, directory: str | Path | None = None) -> dict[str, Any]:
        """Export a revision-consistent PLY and JSON session manifest snapshot."""
        with self._lock:
            if directory is None:
                if self.artifact_dir is None:
                    raise ValueError(
                        "directory is required when artifact_dir is not configured"
                    )
                target_directory = self.artifact_dir
            else:
                target_directory = Path(directory)
            target_directory.mkdir(parents=True, exist_ok=True)

            revision = self._map_revision
            point_cloud_path = target_directory / f"map_{revision:06d}.ply"
            self.export_ply(point_cloud_path)

            manifest_path = target_directory / "spatial_session.json"
            manifest = {
                "schema_version": 1,
                "session_id": self.session_id,
                "coordinate_frame": self.map_frame,
                "transform_convention": "camera_to_map",
                "depth_unit": "m",
                "point_cloud_coordinate_convention": (
                    _Z_UP_COORDINATE_CONVENTION
                ),
                "artifacts": {"point_cloud": point_cloud_path.name},
                "reconstruction": self._reconstruction_locked(),
                "trajectory": deepcopy(self._trajectory),
                "keyframes": [
                    deepcopy(frame)
                    for frame in self._trajectory
                    if frame["integration_status"] == "integrated"
                ],
            }
            temporary_path: Path | None = None
            try:
                with NamedTemporaryFile(
                        mode="w",
                        encoding="utf-8",
                        dir=target_directory,
                        prefix=f".{manifest_path.name}.",
                        delete=False,
                ) as temporary:
                    temporary_path = Path(temporary.name)
                    dump(manifest, temporary, ensure_ascii=False, indent=2)
                    temporary.write("\n")
                temporary_path.replace(manifest_path)
            finally:
                if temporary_path is not None and temporary_path.exists():
                    temporary_path.unlink()

            self._latest_manifest_ref = str(manifest_path)
            self._latest_manifest_revision = revision
            return {
                "session_id": self.session_id,
                "map_revision": revision,
                "point_cloud_ref": str(point_cloud_path),
                "manifest_ref": str(manifest_path),
            }

    def update_layout(
        self,
        point_cloud: Any | None = None,
        colors: Any | None = None,
    ) -> dict[str, Any]:
        """Infer a spatial context from a PLY, mapping, or point array."""
        if point_cloud is None:
            if colors is not None:
                raise ValueError("colors requires an explicit point-cloud array")
            point_cloud = self.point_cloud()
        localization = self._localize_with_spatiallm(
            point_cloud,
            colors,
        )
        with self._lock:
            self._localization = localization
            return deepcopy(self._localization)

    def recall(self, query: dict[str, Any]) -> dict[str, Any]:
        del query
        with self._lock:
            return {"spatial": deepcopy(self._localization)}

    def healthcheck(self) -> dict[str, Any]:
        with self._lock:
            status = {
                "implementation": "voxel_point_map",
                "point_count": len(self._voxels),
                "map_revision": self._map_revision,
                "trajectory_frame_count": len(self._trajectory),
                "session_export_interval_keyframes": (
                    self.session_export_interval_keyframes
                ),
                "latest_ply_ref": self._latest_ply_ref,
                "latest_manifest_ref": self._latest_manifest_ref,
                "latest_manifest_revision": self._latest_manifest_revision,
            }
        if self.spatial_backend is None:
            spatiallm_health = {"configured": False, "healthy": True}
        else:
            spatiallm_health = {
                "configured": True,
                **self.spatial_backend.healthcheck(),
            }
        return {
            "healthy": bool(spatiallm_health.get("healthy", False)),
            **status,
            "spatiallm": spatiallm_health,
        }

    def close(self) -> None:
        if self.spatial_backend is not None:
            self.spatial_backend.close()

    def _reconstruction_locked(self) -> dict[str, Any]:
        bounds = None
        if self._bounds_min is not None and self._bounds_max is not None:
            bounds = {
                "min": list(self._bounds_min),
                "max": list(self._bounds_max),
            }
        return {
            "status": "ready" if self._voxels else "empty",
            "placeholder": False,
            "representation": "voxel_point_cloud",
            "coordinate_frame": self.map_frame,
            "map_revision": self._map_revision,
            "voxel_size_m": self.voxel_size_m,
            "point_count": len(self._voxels),
            "bounds_m": bounds,
            "point_cloud_ref": self._latest_ply_ref,
            "point_cloud_revision": self._latest_ply_revision,
            "session_manifest_ref": self._latest_manifest_ref,
            "session_manifest_revision": self._latest_manifest_revision,
            "trajectory_frame_count": len(self._trajectory),
            "latest_integration": deepcopy(self._latest_integration),
        }

    def _localize_with_spatiallm(
        self,
        point_cloud: Any,
        colors: Any | None = None,
    ) -> dict[str, Any]:
        """Normalize point-cloud inputs and run configured SpatialLM inference."""
        points, normalized_colors = self._prepare_spatiallm_input(
            point_cloud,
            colors,
        )
        if self.spatial_backend is None:
            raise RuntimeError(
                "SpatialLM inference requires a configured spatial_backend"
            )
        return self.spatial_backend.infer_points(
            points,
            normalized_colors,
            detect_type=self.spatial_detect_type,
            seed=self.spatial_seed,
        )

    @classmethod
    def _prepare_spatiallm_input(
        cls,
        point_cloud: Any,
        colors: Any | None = None,
    ) -> tuple[list[list[float]], list[list[float]] | None]:
        if isinstance(point_cloud, (str, Path)):
            if colors is not None:
                raise ValueError("colors must not be provided with a PLY input")
            return load_ply_points_colors(point_cloud)
        if isinstance(point_cloud, Mapping):
            if "points_xyz_m" not in point_cloud:
                raise ValueError("point-cloud mapping is missing: points_xyz_m")
            if colors is not None and "colors_rgb" in point_cloud:
                raise ValueError(
                    "colors must not be provided when mapping contains colors_rgb"
                )
            points = point_cloud["points_xyz_m"]
            source_colors = point_cloud.get("colors_rgb", colors)
        else:
            points = point_cloud
            source_colors = colors
        return cls._normalize_point_arrays(points, source_colors)

    @classmethod
    def _normalize_point_arrays(
        cls,
        points: Any,
        colors: Any | None,
    ) -> tuple[list[list[float]], list[list[float]] | None]:
        point_rows = cls._rows(points, "points")
        if not point_rows:
            raise ValueError("points must not be empty")
        point_width = len(point_rows[0])
        if point_width not in (3, 6, 7) or any(
            len(row) != point_width for row in point_rows
        ):
            raise ValueError("points must have shape (N, 3), (N, 6), or (N, 7)")
        if colors is not None and point_width != 3:
            raise ValueError("colors must be omitted for packed XYZRGB(A) points")

        xyz = [row[:3] for row in point_rows]
        normalized_points = cls._points_to_z_up(xyz)
        if colors is None and point_width in (6, 7):
            colors = [row[3:] for row in point_rows]
        normalized_colors = cls._normalize_colors(colors, len(point_rows))
        return normalized_points, normalized_colors

    @staticmethod
    def _rows(value: Any, name: str) -> list[list[Any]]:
        if isinstance(value, (str, bytes, bytearray)):
            raise TypeError(f"{name} must be a two-dimensional array")
        try:
            source_rows = list(value)
        except TypeError as error:
            raise TypeError(f"{name} must be a two-dimensional array") from error
        rows: list[list[Any]] = []
        for index, row in enumerate(source_rows):
            if isinstance(row, (str, bytes, bytearray)):
                raise TypeError(f"{name}[{index}] must be an array")
            try:
                rows.append(list(row))
            except TypeError as error:
                raise TypeError(f"{name}[{index}] must be an array") from error
        return rows

    @classmethod
    def _normalize_colors(
        cls,
        colors: Any | None,
        point_count: int,
    ) -> list[list[float]] | None:
        if colors is None:
            return None
        color_rows = cls._rows(colors, "colors")
        if len(color_rows) != point_count or any(
            len(row) not in (3, 4) for row in color_rows
        ):
            raise ValueError("colors must have shape (N, 3) or (N, 4)")
        normalized: list[list[float]] = []
        for row in color_rows:
            normalized_row = cls._numeric_row(row, "color")
            if any(value < 0.0 or value > 255.0 for value in normalized_row):
                raise ValueError("colors must use values in [0, 1] or [0, 255]")
            normalized.append(normalized_row)
        return normalized

    @staticmethod
    def _numeric_row(values: Sequence[Any], name: str) -> list[float]:
        normalized: list[float] = []
        for value in values:
            if isinstance(value, bool) or isinstance(
                value, (str, bytes, bytearray)
            ):
                raise ValueError(f"{name} values must be numeric")
            try:
                number = float(value)
            except (TypeError, ValueError) as error:
                raise ValueError(f"{name} values must be numeric") from error
            if not isfinite(number):
                raise ValueError(f"{name} values must be finite")
            normalized.append(number)
        return normalized

    @staticmethod
    def _points_to_z_up(points: Any) -> list[list[float]]:
        if isinstance(points, (str, bytes, bytearray)):
            raise TypeError("points_xyz_m must be an iterable of XYZ points")
        try:
            source_points = list(points)
        except TypeError as error:
            raise TypeError(
                "points_xyz_m must be an iterable of XYZ points"
            ) from error

        converted: list[list[float]] = []
        for point_index, point in enumerate(source_points):
            if isinstance(point, (str, bytes, bytearray)):
                raise TypeError(
                    f"points_xyz_m[{point_index}] must contain three numbers"
                )
            try:
                values = list(point)
            except TypeError as error:
                raise TypeError(
                    f"points_xyz_m[{point_index}] must contain three numbers"
                ) from error
            if len(values) != 3:
                raise ValueError(
                    f"points_xyz_m[{point_index}] must contain three values"
                )
            coordinates = SpatialMemory._numeric_row(values, "point")
            x, y, z = coordinates
            converted.append([x, z, -y])
        return converted

    def _is_keyframe_locked(self, frame: Mapping[str, Any]) -> bool:
        camera_id = frame["camera_id"]
        previous = self._last_keyframe_poses.get(camera_id)
        if previous is None:
            return True
        if self.keyframe_translation_m == 0 and self.keyframe_rotation_deg == 0:
            return True

        current = frame["T_world_camera"]
        dx = current[0][3] - previous[0][3]
        dy = current[1][3] - previous[1][3]
        dz = current[2][3] - previous[2][3]
        translation_m = sqrt(dx * dx + dy * dy + dz * dz)
        rotation_trace = sum(
            previous[row][column] * current[row][column]
            for row in range(3)
            for column in range(3)
        )
        cosine = max(-1.0, min(1.0, (rotation_trace - 1.0) / 2.0))
        rotation_deg = degrees(acos(cosine))
        translation_triggered = (
            self.keyframe_translation_m > 0
            and translation_m >= self.keyframe_translation_m
        )
        rotation_triggered = (
            self.keyframe_rotation_deg > 0
            and rotation_deg >= self.keyframe_rotation_deg
        )
        return translation_triggered or rotation_triggered

    def _record_pose_locked(
            self,
            frame: Mapping[str, Any],
            *,
            keyframe: bool,
            integration_status: str,
    ) -> None:
        self._trajectory.append(
            {
                "ingest_index": self._received_frame_count - 1,
                "timestamp_ns": frame["timestamp_ns"],
                "camera_id": frame["camera_id"],
                "frame_id": frame["frame_id"],
                "intrinsics": {
                    key: frame["intrinsics"][key]
                    for key in ("width", "height", "fx", "fy", "cx", "cy")
                },
                "T_world_camera": [list(row) for row in frame["T_world_camera"]],
                "keyframe": keyframe,
                "integration_status": integration_status,
                "map_revision": self._map_revision,
            }
        )

    def _back_project_frame(
        self, frame: Mapping[str, Any]
    ) -> tuple[dict[tuple[int, int, int], list[float]], int]:
        intrinsics = frame["intrinsics"]
        width = intrinsics["width"]
        height = intrinsics["height"]
        fx = intrinsics["fx"]
        fy = intrinsics["fy"]
        cx = intrinsics["cx"]
        cy = intrinsics["cy"]
        transform = frame["T_world_camera"]
        frame_voxels: dict[tuple[int, int, int], list[float]] = {}
        sampled_point_count = 0

        for v in range(0, height, self.pixel_stride):
            for u in range(0, width, self.pixel_stride):
                depth = self._depth_at(frame["depth_m"], u, v)
                if (
                    not isfinite(depth)
                    or depth < self.depth_min_m
                    or depth > self.depth_max_m
                ):
                    continue
                camera_x = (u - cx) * depth / fx
                camera_y = (v - cy) * depth / fy
                world_x = (
                    transform[0][0] * camera_x
                    + transform[0][1] * camera_y
                    + transform[0][2] * depth
                    + transform[0][3]
                )
                world_y = (
                    transform[1][0] * camera_x
                    + transform[1][1] * camera_y
                    + transform[1][2] * depth
                    + transform[1][3]
                )
                world_z = (
                    transform[2][0] * camera_x
                    + transform[2][1] * camera_y
                    + transform[2][2] * depth
                    + transform[2][3]
                )
                homogeneous_w = (
                    transform[3][0] * camera_x
                    + transform[3][1] * camera_y
                    + transform[3][2] * depth
                    + transform[3][3]
                )
                if homogeneous_w == 0:
                    continue
                if homogeneous_w != 1.0:
                    world_x /= homogeneous_w
                    world_y /= homogeneous_w
                    world_z /= homogeneous_w
                if not all(isfinite(value) for value in (world_x, world_y, world_z)):
                    continue

                red, green, blue = self._color_at(frame["rgb"], u, v)
                voxel_key = (
                    floor(world_x / self.voxel_size_m),
                    floor(world_y / self.voxel_size_m),
                    floor(world_z / self.voxel_size_m),
                )
                aggregate = frame_voxels.setdefault(voxel_key, [0.0] * 7)
                aggregate[0] += world_x
                aggregate[1] += world_y
                aggregate[2] += world_z
                aggregate[3] += red
                aggregate[4] += green
                aggregate[5] += blue
                aggregate[6] += 1
                sampled_point_count += 1
        return frame_voxels, sampled_point_count

    def _fuse_frame_voxels_locked(
        self,
        frame_voxels: Mapping[tuple[int, int, int], list[float]],
        timestamp_ns: int,
    ) -> None:
        for voxel_key, aggregate in frame_voxels.items():
            point_count = int(aggregate[6])
            point = (
                aggregate[0] / point_count,
                aggregate[1] / point_count,
                aggregate[2] / point_count,
            )
            color = (
                self._to_uint8(aggregate[3] / point_count),
                self._to_uint8(aggregate[4] / point_count),
                self._to_uint8(aggregate[5] / point_count),
            )
            voxel = self._voxels.get(voxel_key)
            if voxel is None:
                voxel = _Voxel(
                    x=point[0],
                    y=point[1],
                    z=point[2],
                    red=float(color[0]),
                    green=float(color[1]),
                    blue=float(color[2]),
                    weight=1,
                    observation_count=point_count,
                    last_seen_ns=timestamp_ns,
                )
                self._voxels[voxel_key] = voxel
            else:
                voxel.integrate(
                    point,
                    color,
                    point_count,
                    timestamp_ns,
                    self.max_voxel_weight,
                )
            self._update_bounds_locked(voxel.x, voxel.y, voxel.z)

    def _point_cloud_locked(
        self,
    ) -> tuple[list[list[float]], list[list[int]]]:
        points: list[list[float]] = []
        colors: list[list[int]] = []
        for voxel_key in sorted(self._voxels):
            voxel = self._voxels[voxel_key]
            points.append([voxel.x, voxel.y, voxel.z])
            colors.append(
                [
                    self._to_uint8(voxel.red),
                    self._to_uint8(voxel.green),
                    self._to_uint8(voxel.blue),
                ]
            )
        return points, colors

    def _update_bounds_locked(self, x: float, y: float, z: float) -> None:
        if self._bounds_min is None or self._bounds_max is None:
            self._bounds_min = [x, y, z]
            self._bounds_max = [x, y, z]
            return
        for index, value in enumerate((x, y, z)):
            self._bounds_min[index] = min(self._bounds_min[index], value)
            self._bounds_max[index] = max(self._bounds_max[index], value)

    @staticmethod
    def _validate_image_size(image: Any, width: int, height: int, name: str) -> None:
        actual_width, actual_height = SpatialMemory._image_size(image, name)
        if actual_width != width or actual_height != height:
            raise ValueError(
                f"{name} size {(actual_width, actual_height)} does not match "
                f"intrinsics {(width, height)}"
            )

    @staticmethod
    def _image_size(image: Any, name: str) -> tuple[int, int]:
        shape = getattr(image, "shape", None)
        if shape is not None and len(shape) >= 2:
            return int(shape[1]), int(shape[0])
        size = getattr(image, "size", None)
        if (
            isinstance(size, Sequence)
            and not isinstance(size, (str, bytes, bytearray))
            and len(size) == 2
            and hasattr(image, "getpixel")
        ):
            return int(size[0]), int(size[1])
        try:
            height = len(image)
            width = len(image[0]) if height else 0
        except (IndexError, TypeError) as error:
            raise TypeError(f"{name} must be an indexable image") from error
        return int(width), int(height)

    @staticmethod
    def _pixel_at(image: Any, u: int, v: int) -> Any:
        if hasattr(image, "getpixel"):
            return image.getpixel((u, v))
        return image[v][u]

    @staticmethod
    def _depth_at(depth_image: Any, u: int, v: int) -> float:
        value = SpatialMemory._pixel_at(depth_image, u, v)
        if hasattr(value, "item"):
            value = value.item()
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            if not value:
                return float("nan")
            value = value[0]
        try:
            return float(value)
        except (TypeError, ValueError) as error:
            raise TypeError("depth_m pixels must be numeric") from error

    @staticmethod
    def _color_at(rgb_image: Any, u: int, v: int) -> tuple[int, int, int]:
        value = SpatialMemory._pixel_at(rgb_image, u, v)
        if hasattr(value, "tolist"):
            value = value.tolist()
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            channels = list(value)
        else:
            channels = [value, value, value]
        if len(channels) == 1:
            channels *= 3
        if len(channels) < 3:
            raise ValueError("rgb pixels must contain at least three channels")
        converted: list[int] = []
        for channel in channels[:3]:
            if hasattr(channel, "item"):
                channel = channel.item()
            try:
                numeric = float(channel)
            except (TypeError, ValueError) as error:
                raise TypeError("rgb channels must be numeric") from error
            if not isfinite(numeric):
                raise ValueError("rgb channels must be finite")
            converted.append(SpatialMemory._to_uint8(numeric))
        return converted[0], converted[1], converted[2]

    @staticmethod
    def _to_uint8(value: float) -> int:
        return max(0, min(255, round(value)))

    def _validate_frame(self, frame: Mapping[str, Any]) -> dict[str, Any]:
        required = {
            "timestamp_ns",
            "camera_id",
            "frame_id",
            "world_frame",
            "rgb",
            "depth_m",
            "intrinsics",
            "T_world_camera",
        }
        missing = sorted(required - frame.keys())
        if missing:
            raise ValueError(f"spatial frame is missing: {', '.join(missing)}")

        timestamp_ns = frame["timestamp_ns"]
        if (
            not isinstance(timestamp_ns, Integral)
            or isinstance(timestamp_ns, bool)
            or timestamp_ns < 0
        ):
            raise ValueError("timestamp_ns must be a non-negative integer")
        for key in ("camera_id", "frame_id", "world_frame"):
            if not isinstance(frame[key], str) or not frame[key]:
                raise ValueError(f"{key} must be a non-empty string")
        if frame["world_frame"] != self.map_frame:
            raise ValueError(
                f"world_frame must match configured map_frame {self.map_frame!r}"
            )
        if frame["rgb"] is None:
            raise ValueError("rgb must not be None")
        if frame["depth_m"] is None:
            raise ValueError("depth_m must not be None")

        intrinsics = frame["intrinsics"]
        if not isinstance(intrinsics, Mapping):
            raise TypeError("intrinsics must be a mapping")
        intrinsic_keys = {"width", "height", "fx", "fy", "cx", "cy"}
        missing_intrinsics = sorted(intrinsic_keys - intrinsics.keys())
        if missing_intrinsics:
            raise ValueError("intrinsics is missing: " + ", ".join(missing_intrinsics))
        normalized_intrinsics = dict(intrinsics)
        for key in ("width", "height"):
            value = intrinsics[key]
            if not isinstance(value, Integral) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"intrinsics.{key} must be a positive integer")
            normalized_intrinsics[key] = int(value)
        for key in ("fx", "fy", "cx", "cy"):
            value = intrinsics[key]
            if isinstance(value, bool) or not isinstance(value, Real):
                raise ValueError(f"intrinsics.{key} must be numeric")
            normalized_value = float(value)
            if not isfinite(normalized_value):
                raise ValueError(f"intrinsics.{key} must be finite")
            normalized_intrinsics[key] = normalized_value
        if normalized_intrinsics["fx"] <= 0 or normalized_intrinsics["fy"] <= 0:
            raise ValueError("intrinsics fx and fy must be positive")
        self._validate_image_size(
            frame["depth_m"],
            normalized_intrinsics["width"],
            normalized_intrinsics["height"],
            "depth_m",
        )
        self._validate_image_size(
            frame["rgb"],
            normalized_intrinsics["width"],
            normalized_intrinsics["height"],
            "rgb",
        )

        transform = frame["T_world_camera"]
        if isinstance(transform, (str, bytes, bytearray)):
            raise TypeError("T_world_camera must be a 4x4 sequence")
        try:
            transform_rows = list(transform)
        except TypeError as error:
            raise TypeError("T_world_camera must be a 4x4 sequence") from error
        if len(transform_rows) != 4:
            raise ValueError("T_world_camera must contain four rows")
        normalized_transform: list[list[float]] = []
        for row in transform_rows:
            if isinstance(row, (str, bytes, bytearray)):
                raise TypeError("T_world_camera rows must be sequences")
            try:
                row_values = list(row)
            except TypeError as error:
                raise TypeError("T_world_camera rows must be sequences") from error
            if len(row_values) != 4:
                raise ValueError("T_world_camera rows must contain four values")
            normalized_row: list[float] = []
            for value in row_values:
                if isinstance(value, bool) or not isinstance(value, Real):
                    raise ValueError("T_world_camera values must be numeric")
                normalized_value = float(value)
                if not isfinite(normalized_value):
                    raise ValueError("T_world_camera values must be finite")
                normalized_row.append(normalized_value)
            normalized_transform.append(normalized_row)

        expected_bottom_row = (0.0, 0.0, 0.0, 1.0)
        if any(
                abs(actual - expected) > 1e-6
                for actual, expected in zip(
                    normalized_transform[3], expected_bottom_row, strict=True
                )
        ):
            raise ValueError("T_world_camera bottom row must be [0, 0, 0, 1]")

        rotation = [row[:3] for row in normalized_transform[:3]]
        tolerance = 1e-3
        for row_index, row in enumerate(rotation):
            row_norm_squared = sum(value * value for value in row)
            if abs(row_norm_squared - 1.0) > tolerance:
                raise ValueError("T_world_camera rotation must be orthonormal")
            for other_row in rotation[row_index + 1:]:
                dot_product = sum(
                    a * b for a, b in zip(row, other_row, strict=True)
                )
                if abs(dot_product) > tolerance:
                    raise ValueError("T_world_camera rotation must be orthonormal")
        determinant = (
                rotation[0][0]
                * (rotation[1][1] * rotation[2][2] - rotation[1][2] * rotation[2][1])
                - rotation[0][1]
                * (rotation[1][0] * rotation[2][2] - rotation[1][2] * rotation[2][0])
                + rotation[0][2]
                * (rotation[1][0] * rotation[2][1] - rotation[1][1] * rotation[2][0])
        )
        if abs(determinant - 1.0) > tolerance:
            raise ValueError("T_world_camera rotation determinant must be 1")

        return {
            **frame,
            "timestamp_ns": int(timestamp_ns),
            "intrinsics": normalized_intrinsics,
            "T_world_camera": normalized_transform,
        }
