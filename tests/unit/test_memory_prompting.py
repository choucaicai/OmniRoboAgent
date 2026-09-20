from typing import Any

from omniroboagent.agent_core.prompting import (
    WORKING_MEMORY_HEADER,
    working_frame_content,
)


def frame(step: int, **overrides: Any) -> dict[str, Any]:
    return {
        "step": step,
        "event_type": "transition",
        "status": "in_progress",
        "cameras": {"head": f"image-{step}"},
        **overrides,
    }


def test_working_frame_content_labels_every_frame() -> None:
    context = {
        "working_frames": [
            frame(3, event_type="subtask_failed", status="failed"),
            frame(4),
        ]
    }

    content = working_frame_content(context)

    assert [item.get("text") for item in content if item["type"] == "text"] == [
        WORKING_MEMORY_HEADER,
        "step=3 event=subtask_failed status=failed",
        "step=4 event=transition status=in_progress",
    ]


def test_working_frame_content_keeps_image_order_and_count() -> None:
    context = {
        "working_frames": [
            frame(0, cameras={"head": "a", "wrist": ["b", "c"]}),
            frame(1),
        ]
    }

    content = working_frame_content(context)

    assert [
        item["image_url"]["url"] for item in content if item["type"] == "image_url"
    ] == ["a", "b", "c", "image-1"]


def test_working_frame_content_emits_nothing_without_frames() -> None:
    assert working_frame_content({"working_frames": []}) == []
    assert working_frame_content({"working_frames": [{"cameras": {}}]}) == []
    assert working_frame_content({"working_frames": "nope"}) == []
    assert working_frame_content(None) == []


def test_working_frame_content_omits_absent_label_fields() -> None:
    content = working_frame_content(
        {"working_frames": [{"step": 2, "cameras": {"head": "x"}}]}
    )

    assert content[1]["text"] == "step=2"
