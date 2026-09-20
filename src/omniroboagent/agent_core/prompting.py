import json
from collections.abc import Mapping, Sequence
from typing import Any

WORKING_MEMORY_HEADER = "Visual working memory, oldest to newest"

DEFAULT_MEMORY_CHAR_BUDGET = 4096
EVENT_RENDER_LIMIT = 10

# Ordered by decision value per character. The distilled partitions come first
# because they are both the smallest and the most specific, then the compact
# event lines, and `summary` fills whatever is left. Summary is last precisely
# because it is the most duplicative block: it is the concatenation of the same
# key-event texts, so letting it bid early starves everything behind it.
MEMORY_PARTITION_PRIORITY = (
    "object_state",
    "lessons",
    "procedures",
    "key_events",
    "recent_events",
    "summary",
)


def _cost(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False))


def _entry_texts(partition: Any) -> list[str]:
    """Render a distilled partition as the single-line text of each entry."""
    if not isinstance(partition, list):
        return []
    texts: list[str] = []
    for entry in partition:
        if not isinstance(entry, Mapping):
            continue
        text = str(entry.get("text") or "").strip()
        if text:
            texts.append(text)
    return texts


def _recent_event_lines(partition: Any) -> list[str]:
    """Render recent transitions as one compact line each."""
    if not isinstance(partition, list):
        return []
    return [
        f"step={event.get('step')} event={event.get('event_type')} "
        f"status={event.get('status')} reason={event.get('reason')}"
        for event in partition[-EVENT_RENDER_LIMIT:]
        if isinstance(event, Mapping)
    ]


def _key_event_lines(partition: Any, summary: str) -> list[str]:
    """Render key events, emitting only what the summary does not already say.

    ``summary`` is the concatenation of the same key-event texts, so repeating
    the full records costs a large share of the prompt and carries no new
    information. Only verifier evidence, which the summary omits, is kept for
    events the summary already covers.

    The untrimmed summary is used for the comparison. It is trimmed oldest
    first while this renders the newest events, so the events checked here are
    the ones whose summary lines survive.
    """
    if not isinstance(partition, list):
        return []
    lines: list[str] = []
    for event in partition[-EVENT_RENDER_LIMIT:]:
        if not isinstance(event, Mapping):
            continue
        text = str(event.get("text_summary") or "").strip()
        raw_evidence = event.get("evidence_summary")
        evidence = (
            [str(item) for item in raw_evidence]
            if isinstance(raw_evidence, Sequence) and not isinstance(raw_evidence, str)
            else []
        )
        covered = bool(text) and text in summary
        head = "" if covered else text
        if not head and not evidence:
            continue
        if not head:
            head = f"step={event.get('step')}"
        lines.append(f"{head} evidence={'; '.join(evidence)}" if evidence else head)
    return lines


def _fit(value: Any, remaining: int) -> tuple[Any, int]:
    """Trim a rendered partition to the budget, dropping the oldest content."""
    if _cost(value) <= remaining:
        return value, 0
    if isinstance(value, list):
        kept = list(value)
        while kept and _cost(kept) > remaining:
            kept.pop(0)
        return (kept or None), len(value) - len(kept)
    lines = str(value).split("\n")
    total = len(lines)
    while lines and _cost("\n".join(lines)) > remaining:
        lines.pop(0)
    return ("\n".join(lines) or None), total - len(lines)


def memory_text_payload(
    memory_context: Any, char_budget: int = DEFAULT_MEMORY_CHAR_BUDGET
) -> dict[str, Any]:
    """Render recalled memory as a compact, de-duplicated, budgeted payload.

    Partitions are filled in priority order and anything that does not fit is
    reported under ``dropped``, so a truncated prompt never silently reads as a
    complete one.
    """
    if not isinstance(memory_context, Mapping):
        return {}
    summary = str(memory_context.get("summary") or "")
    rendered: dict[str, Any] = {
        "object_state": _entry_texts(memory_context.get("object_state")),
        "lessons": _entry_texts(memory_context.get("lessons")),
        "procedures": _entry_texts(memory_context.get("procedures")),
        "key_events": _key_event_lines(memory_context.get("key_events"), summary),
        "recent_events": _recent_event_lines(memory_context.get("recent_events")),
        "summary": summary,
    }

    payload: dict[str, Any] = {}
    dropped: list[str] = []
    remaining = char_budget
    for name in MEMORY_PARTITION_PRIORITY:
        value = rendered[name]
        if not value:
            continue
        fitted, lost = _fit(value, remaining)
        if fitted is None:
            dropped.append(name)
            continue
        if lost:
            dropped.append(f"{name}[oldest {lost}]")
        payload[name] = fitted
        remaining -= _cost(fitted)
    if dropped:
        payload["dropped"] = dropped
    return payload


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
