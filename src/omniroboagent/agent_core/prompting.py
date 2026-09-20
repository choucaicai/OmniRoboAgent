from collections.abc import Mapping
from typing import Any

WORKING_MEMORY_HEADER = "Visual working memory, oldest to newest"


def frame_label(frame: Mapping[str, Any]) -> str:
    """Describe which transition a working frame was captured at."""
    parts = [f"step={frame.get('step')}"]
    event_type = frame.get("event_type")
    if isinstance(event_type, str) and event_type:
        parts.append(f"event={event_type}")
    status = frame.get("status")
    if status is not None:
        parts.append(f"status={status}")
    return " ".join(parts)


def working_frame_content(memory_context: Any) -> list[dict[str, Any]]:
    """Render recalled working frames as labelled image content, oldest to newest.

    Each frame is preceded by one line of text, so a model receiving several
    near-identical views can still tell which one is the failure it should
    reason about. Without the labels the salience gating in ``TieredMemory``
    selects the right frames but the selection is invisible downstream.
    """
    if not isinstance(memory_context, Mapping):
        return []
    frames = memory_context.get("working_frames", [])
    if not isinstance(frames, list):
        return []
    content: list[dict[str, Any]] = []
    for frame in frames:
        if not isinstance(frame, Mapping):
            continue
        cameras = frame.get("cameras")
        if not isinstance(cameras, Mapping):
            continue
        images: list[Any] = []
        for value in cameras.values():
            images.extend(value if isinstance(value, list) else [value])
        if not images:
            continue
        content.append({"type": "text", "text": frame_label(frame)})
        for image in images:
            content.append({"type": "image_url", "image_url": {"url": image}})
    if content:
        content.insert(0, {"type": "text", "text": WORKING_MEMORY_HEADER})
    return content
