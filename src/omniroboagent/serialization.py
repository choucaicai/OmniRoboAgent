from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def to_jsonable(value: Any, *, max_sequence_items: int = 32) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return {"type": type(value).__name__, "bytes": len(value)}
    if isinstance(value, Mapping):
        return {
            str(key): to_jsonable(item, max_sequence_items=max_sequence_items)
            for key, item in value.items()
        }
    if hasattr(value, "shape") and hasattr(value, "dtype"):
        return {
            "type": type(value).__name__,
            "shape": list(value.shape),
            "dtype": str(value.dtype),
        }
    if isinstance(value, Sequence):
        items = list(value)
        result = [
            to_jsonable(item, max_sequence_items=max_sequence_items)
            for item in items[:max_sequence_items]
        ]
        if len(items) > max_sequence_items:
            result.append({"truncated_items": len(items) - max_sequence_items})
        return result
    return {"type": type(value).__name__, "repr": repr(value)[:500]}
