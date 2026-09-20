import math
from collections.abc import Mapping, Sequence
from numbers import Real
from typing import Any

from omniroboagent.exceptions import BackendError

_ENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    "walls": ("id", "a", "b", "height", "thickness"),
    "doors": ("id", "wall_id", "center", "width", "height"),
    "windows": ("id", "wall_id", "center", "width", "height"),
    "objects": ("id", "class_name", "center", "angle_z", "size"),
}
_VECTOR_FIELDS = {"a", "b", "center", "size"}
_NUMBER_FIELDS = {"height", "thickness", "width", "angle_z"}
_STRING_FIELDS = {"id", "wall_id", "class_name"}


def validate_spatial_context(
    value: Any,
) -> dict[str, list[dict[str, Any]]]:
    """Validate and copy SpatialLM geometry into its canonical JSON shape."""
    if not isinstance(value, Mapping):
        raise BackendError("Spatial context must be a mapping")

    unexpected = set(value).difference(_ENTITY_FIELDS)
    if unexpected:
        names = ", ".join(sorted(str(name) for name in unexpected))
        raise BackendError(f"Spatial context has unexpected fields: {names}")

    canonical: dict[str, list[dict[str, Any]]] = {}
    for collection_name, fields in _ENTITY_FIELDS.items():
        if collection_name not in value:
            raise BackendError(
                f"Spatial context is missing collection {collection_name!r}"
            )
        entities = value[collection_name]
        if not isinstance(entities, list):
            raise BackendError(
                f"Spatial context collection {collection_name!r} must be a list"
            )

        canonical_entities: list[dict[str, Any]] = []
        for index, entity in enumerate(entities):
            location = f"{collection_name}[{index}]"
            if not isinstance(entity, Mapping):
                raise BackendError(f"Spatial context {location} must be a mapping")

            missing = set(fields).difference(entity)
            if missing:
                names = ", ".join(sorted(missing))
                raise BackendError(
                    f"Spatial context {location} is missing fields: {names}"
                )
            unexpected_entity_fields = set(entity).difference(fields)
            if unexpected_entity_fields:
                names = ", ".join(
                    sorted(str(name) for name in unexpected_entity_fields)
                )
                raise BackendError(
                    f"Spatial context {location} has unexpected fields: {names}"
                )

            canonical_entity: dict[str, Any] = {}
            for field in fields:
                field_value = entity[field]
                field_location = f"{location}.{field}"
                if field in _STRING_FIELDS:
                    canonical_entity[field] = _validate_string(
                        field_value, field_location
                    )
                elif field in _NUMBER_FIELDS:
                    canonical_entity[field] = _validate_number(
                        field_value, field_location
                    )
                elif field in _VECTOR_FIELDS:
                    canonical_entity[field] = _validate_vector3(
                        field_value, field_location
                    )
            canonical_entities.append(canonical_entity)
        canonical[collection_name] = canonical_entities

    return canonical


def _validate_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value:
        raise BackendError(f"Spatial context {location} must be a non-empty string")
    return value


def _validate_number(value: Any, location: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise BackendError(f"Spatial context {location} must be a finite number")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise BackendError(
            f"Spatial context {location} must be a finite number"
        ) from error
    if not math.isfinite(number):
        raise BackendError(f"Spatial context {location} must be a finite number")
    return number


def _validate_vector3(value: Any, location: str) -> list[float]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or len(value) != 3
    ):
        raise BackendError(f"Spatial context {location} must be a vector3")
    return [
        _validate_number(component, f"{location}[{index}]")
        for index, component in enumerate(value)
    ]
