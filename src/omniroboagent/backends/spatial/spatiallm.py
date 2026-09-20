import importlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from omniroboagent.backends.spatial.schema import validate_spatial_context
from omniroboagent.exceptions import BackendError


class SpatialLMBackend:
    """Keep one in-process SpatialLM engine and validate its geometry output."""

    def __init__(
        self,
        model_path: str | Path | None = None,
        *,
        engine: Any | None = None,
        **engine_options: Any,
    ) -> None:
        if engine is None:
            if model_path is None or not str(model_path):
                raise BackendError(
                    "SpatialLM backend requires model_path when no engine is provided"
                )
            try:
                module = importlib.import_module("spatiallm")
                engine_type = module.SpatialLMInference
                engine = engine_type(model_path=model_path, **engine_options)
            except Exception as error:
                raise BackendError(
                    f"Failed to initialize SpatialLM inference engine: {error}"
                ) from error

        infer_points = getattr(engine, "infer_points", None)
        if not callable(infer_points):
            raise BackendError("SpatialLM engine must provide callable infer_points")

        self.model_path = str(model_path) if model_path is not None else None
        self.engine = engine
        self._closed = False

    def infer_points(
        self,
        points: Any,
        colors: Any | None = None,
        **generation_options: Any,
    ) -> dict[str, list[dict[str, Any]]]:
        if self._closed:
            raise BackendError("SpatialLM backend is closed")
        try:
            result = self.engine.infer_points(
                points,
                colors,
                **generation_options,
            )
        except Exception as error:
            raise BackendError(f"SpatialLM inference failed: {error}") from error
        return validate_spatial_context(result)

    def infer_ply(
        self,
        path: str | Path,
        **generation_options: Any,
    ) -> dict[str, list[dict[str, Any]]]:
        """Load a PLY with SpatialLM's Open3D helpers and run inference."""
        if self._closed:
            raise BackendError("SpatialLM backend is closed")
        point_cloud_path = Path(path)
        if point_cloud_path.suffix.lower() != ".ply":
            raise ValueError("SpatialLM point-cloud path must end with .ply")
        if not point_cloud_path.is_file():
            raise FileNotFoundError(
                f"SpatialLM point-cloud file does not exist: {point_cloud_path}"
            )

        try:
            numpy = importlib.import_module("numpy")
            pcd = importlib.import_module("spatiallm.pcd")
        except Exception as error:
            raise BackendError(
                f"Failed to import SpatialLM point-cloud dependencies: {error}"
            ) from error

        point_cloud = pcd.load_o3d_pcd(str(point_cloud_path))
        points, colors = pcd.get_points_and_colors(point_cloud)
        points = numpy.asarray(points)
        colors = numpy.asarray(colors)
        if len(points) == 0:
            raise ValueError(f"PLY contains no readable points: {point_cloud_path}")
        if not numpy.isfinite(points).all():
            raise ValueError(f"PLY contains non-finite XYZ values: {point_cloud_path}")
        return self.infer_points(points, colors, **generation_options)

    def healthcheck(self) -> dict[str, Any]:
        if self._closed:
            return {"healthy": False, "error": "SpatialLM backend is closed"}

        healthcheck = getattr(self.engine, "healthcheck", None)
        if not callable(healthcheck):
            return {"healthy": True, "backend": "spatiallm"}
        try:
            result = healthcheck()
        except Exception as error:
            return {"healthy": False, "error": str(error)}
        if not isinstance(result, Mapping):
            return {
                "healthy": False,
                "error": "SpatialLM engine healthcheck must return a mapping",
            }
        return dict(result)

    def close(self) -> None:
        if self._closed:
            return
        close = getattr(self.engine, "close", None)
        if callable(close):
            try:
                close()
            except Exception as error:
                raise BackendError(
                    f"Failed to close SpatialLM engine: {error}"
                ) from error
        self._closed = True
        self.engine = None
