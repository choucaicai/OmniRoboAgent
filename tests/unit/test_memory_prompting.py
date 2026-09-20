from typing import Any

from omniroboagent.agent_core.prompting import (
    MEMORY_PARTITION_PRIORITY,
    WORKING_MEMORY_HEADER,
    memory_text_payload,
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


def key_event(
    step: int, text: str, evidence: list[str] | None = None
) -> dict[str, Any]:
    return {
        "step": step,
        "event_type": "subtask_failed",
        "text_summary": text,
        "evidence_summary": evidence or [],
    }


def test_memory_text_payload_drops_key_events_the_summary_already_states() -> None:
    payload = memory_text_payload(
        {
            "summary": "step=1 opened the cabinet\nstep=2 dropped the mug",
            "key_events": [
                key_event(1, "step=1 opened the cabinet"),
                key_event(2, "step=2 dropped the mug"),
            ],
        }
    )

    assert "key_events" not in payload
    assert payload["summary"] == "step=1 opened the cabinet\nstep=2 dropped the mug"


def test_memory_text_payload_keeps_evidence_of_covered_key_events() -> None:
    payload = memory_text_payload(
        {
            "summary": "step=1 opened the cabinet",
            "key_events": [
                key_event(1, "step=1 opened the cabinet", ["the door is ajar"]),
            ],
        }
    )

    assert payload["key_events"] == ["step=1 evidence=the door is ajar"]


def test_memory_text_payload_keeps_key_events_the_summary_omits() -> None:
    payload = memory_text_payload(
        {
            "summary": "step=1 opened the cabinet",
            "key_events": [key_event(9, "step=9 dropped the mug", ["mug on floor"])],
        }
    )

    assert payload["key_events"] == ["step=9 dropped the mug evidence=mug on floor"]


def test_memory_text_payload_renders_recent_events_as_one_line_each() -> None:
    payload = memory_text_payload(
        {
            "recent_events": [
                {
                    "step": 4,
                    "event_type": "chunk_executed",
                    "status": "in_progress",
                    "reason": "still moving",
                    "artifact_refs": ["dropped-by-the-renderer"],
                }
            ]
        }
    )

    assert payload["recent_events"] == [
        "step=4 event=chunk_executed status=in_progress reason=still moving"
    ]


def test_memory_text_payload_orders_partitions_by_priority() -> None:
    payload = memory_text_payload(
        {
            "summary": "narrative",
            "recent_events": [{"step": 1}],
            "key_events": [key_event(1, "a failure")],
            "lessons": [{"text": "grasp lower"}],
            "object_state": [{"text": "the cabinet is open"}],
            "procedures": [{"text": "task=x steps=1) MoveTo"}],
        }
    )

    assert list(payload) == [
        name for name in MEMORY_PARTITION_PRIORITY if name in payload
    ]
    assert list(payload)[:3] == ["object_state", "lessons", "procedures"]


def test_memory_text_payload_reports_what_the_budget_dropped() -> None:
    payload = memory_text_payload(
        {
            "summary": "old line that is quite long indeed\nnew line",
            "recent_events": [
                {"step": step, "event_type": "chunk_executed"} for step in range(3)
            ],
            "object_state": [{"text": "the cabinet is open"}],
        },
        char_budget=100,
    )

    assert payload["object_state"] == ["the cabinet is open"]
    assert payload["recent_events"] == [
        "step=2 event=chunk_executed status=None reason=None"
    ]
    assert payload["summary"] == "new line"
    assert payload["dropped"] == ["recent_events[oldest 2]", "summary[oldest 1]"]


def test_memory_text_payload_reports_a_partition_that_does_not_fit_at_all() -> None:
    payload = memory_text_payload(
        {
            "object_state": [{"text": "the cabinet is open"}],
            "summary": "a narrative far too long to survive the remaining budget",
        },
        char_budget=30,
    )

    assert payload["object_state"] == ["the cabinet is open"]
    assert "summary" not in payload
    assert payload["dropped"] == ["summary"]


def test_memory_text_payload_is_empty_without_memory() -> None:
    assert memory_text_payload(None) == {}
    assert memory_text_payload({}) == {}
    assert memory_text_payload({"summary": "", "recent_events": []}) == {}
