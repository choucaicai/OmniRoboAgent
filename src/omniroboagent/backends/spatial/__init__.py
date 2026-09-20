"""In-process spatial inference backends and output validation."""

from omniroboagent.backends.spatial.schema import validate_spatial_context
from omniroboagent.backends.spatial.spatiallm import SpatialLMBackend

__all__ = ["SpatialLMBackend", "validate_spatial_context"]
