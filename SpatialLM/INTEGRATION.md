# Framework Integration API

`SpatialLMInference` is a long-lived Python adapter for integrating SpatialLM
into another framework. It loads the model once and exposes two input paths:

- `infer_ply`: read a PLY file.
- `infer_points`: accept in-memory NumPy XYZ/RGB arrays without a temporary file.

Both methods return a JSON-compatible dictionary. The corresponding
`infer_ply_json` and `infer_points_json` methods return a JSON string.

## Input contract

- Point shape: `(N, 3)` for XYZ, or `(N, 6)`/`(N, 7)` for packed
  XYZRGB/XYZRGBA when a separate RGB array is not supplied.
- XYZ unit: meters.
- Coordinate system: right-handed, Z-up, with walls preferably aligned to the
  XY axes.
- RGB shape: `(N, 3)` or `(N, 4)`. Alpha is ignored.
- RGB range: integer-like `[0, 255]` or floating-point `[0, 1]`.
- RGB is optional. Missing RGB is represented as black.
- Rows containing NaN or infinity are removed before inference.

The SpatialLM1.1 model uses a 32-meter normalization range. Scenes spanning
more than 32 meters along an axis should be split or cropped before inference.

## Initialization

```python
from spatiallm import SpatialLMInference

engine = SpatialLMInference(
    model_path="../models/SpatialLM1.1-Qwen-0.5B",
    default_wall_thickness=0.12,  # optional downstream fallback
    output_precision=6,           # optional JSON rounding
)
```

Keep one `engine` alive for the lifetime of the framework process. Do not load
the model for every request. Calls on the same engine are serialized so it can
be safely invoked by multiple framework request threads on one GPU.

## PLY input

```python
result = engine.infer_ply(
    "/data/scene.ply",
    detect_type="all",
    seed=42,
)

json_text = engine.infer_ply_json(
    "/data/scene.ply",
    detect_type="all",
    seed=42,
)
```

## Array input

```python
import numpy as np

points = np.asarray(framework_point_cloud.xyz, dtype=np.float32)  # (N, 3)
colors = np.asarray(framework_point_cloud.rgb, dtype=np.uint8)    # (N, 3)

result = engine.infer_points(
    points,
    colors,
    detect_type="all",
    seed=42,
)

json_text = engine.infer_points_json(
    points,
    colors,
    detect_type="all",
    seed=42,
)
```

Packed XYZRGB is also accepted:

```python
xyzrgb = np.asarray(framework_point_cloud, dtype=np.float32)  # (N, 6)
result = engine.infer_points(xyzrgb)
```

For cross-process or cross-language integration, transmit large point clouds as
packed float32/uint8 buffers, NumPy `.npz`, MessagePack, shared memory, or gRPC
binary fields. Avoid nested JSON arrays for large point clouds.

## Detection options

`detect_type` accepts:

- `"all"`: walls, doors, windows, and object boxes.
- `"arch"`: walls, doors, and windows.
- `"object"`: object boxes only.

Object detection may be limited to selected categories:

```python
result = engine.infer_points(
    points,
    colors,
    detect_type="object",
    categories=["sofa", "chair", "dining_table"],
)
```

Generation is sampled by the upstream model. Use a fixed `seed` for repeatable
framework behavior.

## Output contract

```json
{
  "walls": [
    {
      "id": "wall_0",
      "a": [0.2, 0.4, 0.0],
      "b": [4.8, 0.4, 0.0],
      "height": 2.7,
      "thickness": 0.12
    }
  ],
  "doors": [
    {
      "id": "door_0",
      "wall_id": "wall_0",
      "center": [2.1, 0.4, 1.05],
      "width": 0.9,
      "height": 2.1
    }
  ],
  "windows": [],
  "objects": [
    {
      "id": "object_0",
      "class_name": "sofa",
      "center": [3.4, 2.2, 0.45],
      "angle_z": 1.5708,
      "size": [2.0, 0.9, 0.9]
    }
  ]
}
```

All positions and sizes use the input point cloud coordinate frame and unit.
`angle_z` is in radians. `size` contains full X/Y/Z box dimensions, not half
extents.

SpatialLM commonly predicts zero wall thickness. When
`default_wall_thickness` is configured, it replaces only non-positive predicted
thickness values. Leave it as `None` to preserve the model output exactly.
