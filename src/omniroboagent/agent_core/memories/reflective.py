import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from omniroboagent.agent_core.memories.tiered import TieredMemory
from omniroboagent.serialization import to_jsonable

FAILURE_EVENT_TYPES = {"subtask_failed", "execution_aborted"}
SUCCESS_EVENT_TYPES = {"subtask_completed"}

CONTROL_FAILURE_CLASSES = {
    "loop": "control_loop",
    "no_progress": "no_progress",
    "chunk_budget": "chunk_budget",
}

FAILURE_KEYWORD_CLASSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "precondition_unmet",
        ("precondition", "not open", "still closed", "unreachable", "out of reach"),
    ),
    ("grasp_failed", ("grasp", "slip", "dropped", "not holding")),
    ("placement_failed", ("misplaced", "wrong location", "not placed")),
    ("environment_error", ("exception", "invalid action", "timeout")),
)

_WORD_PATTERN = re.compile(r"[a-z0-9]+")


class ReflectiveMemory(TieredMemory):
    """Tiered memory that distils repeated failures into evidence-gated lessons."""

    def __init__(
        self,
        visual_window_size: int = 4,
        recent_event_limit: int = 20,
        key_event_limit: int = 20,
        summary_max_chars: int = 4096,
        camera_keys: list[str] | None = None,
        event_path: str | Path | None = None,
        save_key_event_artifacts: bool = False,
        frame_selection: str = "recent",
        lesson_recall_limit: int = 3,
        lesson_min_support: int = 2,
        lesson_limit: int = 64,
        lesson_path: str | Path | None = None,
        lesson_reload: bool = False,
    ) -> None:
        super().__init__(
            visual_window_size=visual_window_size,
            recent_event_limit=recent_event_limit,
            key_event_limit=key_event_limit,
            summary_max_chars=summary_max_chars,
            camera_keys=camera_keys,
            event_path=event_path,
            save_key_event_artifacts=save_key_event_artifacts,
            frame_selection=frame_selection,
        )
        if lesson_recall_limit <= 0:
            raise ValueError("lesson_recall_limit must be positive")
        if lesson_min_support <= 0:
            raise ValueError("lesson_min_support must be positive")
        if lesson_limit < lesson_recall_limit:
            raise ValueError("lesson_limit must be at least lesson_recall_limit")
        if lesson_reload and lesson_path is None:
            raise ValueError("lesson_reload requires lesson_path")

        self.lesson_recall_limit = lesson_recall_limit
        self.lesson_min_support = lesson_min_support
        self.lesson_limit = lesson_limit
        self.lesson_path = Path(lesson_path) if lesson_path is not None else None
        self.lesson_reload = lesson_reload
        if self.lesson_path is not None:
            self.lesson_path.parent.mkdir(parents=True, exist_ok=True)

        self.lessons: list[dict[str, Any]] = []
        self._lesson_sequence = 0
        if self.lesson_reload:
            self._load_lessons()

    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        key_event_count = len(self.key_events)
        super().update(state, event)
        if len(self.key_events) == key_event_count:
            return

        key_record = self.key_events[-1]
        event_type = key_record.get("event_type")
        if event_type not in FAILURE_EVENT_TYPES | SUCCESS_EVENT_TYPES:
            return

        signature = self._attempt_signature(state, event, key_record)
        if signature is None:
            return
        if event_type in SUCCESS_EVENT_TYPES:
            self._refute(signature, key_record)
            return
        self._reinforce(signature, event, key_record)
        self._evict_lessons()

    def recall(self, query: dict[str, Any]) -> dict[str, Any]:
        recalled = super().recall(query)
        recalled["lessons"] = self._recall_lessons(query)
        return recalled

    def _reinforce(
        self,
        signature: str,
        event: Mapping[str, Any],
        key_record: Mapping[str, Any],
    ) -> None:
        failure_class = self._failure_class(event, key_record)
        lesson = self._find_lesson(signature, failure_class)
        reason = key_record.get("reason")
        last_reason = str(reason)[:256] if reason is not None else None
        step = key_record.get("step")
        session_id = key_record.get("session_id")
        event_id = key_record.get("event_id")
        if lesson is None:
            self._lesson_sequence += 1
            lesson = {
                "lesson_id": f"lesson:{self._lesson_sequence}",
                "signature": signature,
                "skill": key_record.get("skill"),
                "subtask": key_record.get("subtask"),
                "failure_class": failure_class,
                "status": "candidate",
                "support_count": 1,
                "refutation_count": 0,
                "revision": 1,
                "first_seen_step": step,
                "last_seen_step": step,
                "last_reason": last_reason,
                "session_ids": [session_id] if session_id is not None else [],
                "source_event_ids": [event_id] if event_id is not None else [],
                "text": "",
                "carried_over": False,
            }
            self.lessons.append(lesson)
            operation = "add"
        else:
            lesson["support_count"] = int(lesson["support_count"]) + 1
            lesson["revision"] = int(lesson["revision"]) + 1
            lesson["subtask"] = key_record.get("subtask")
            lesson["last_seen_step"] = step
            lesson["last_reason"] = last_reason
            if session_id is not None and session_id not in lesson["session_ids"]:
                lesson["session_ids"].append(session_id)
            if event_id is not None:
                lesson["source_event_ids"].append(event_id)
            operation = "upvote"

        changed = self._resolve_status(lesson)
        lesson["text"] = self._lesson_text(lesson)
        self._log_lesson(operation, lesson)
        self._log_status_change(changed, lesson)

    def _refute(self, signature: str, key_record: Mapping[str, Any]) -> None:
        event_id = key_record.get("event_id")
        for lesson in self.lessons:
            if lesson["signature"] != signature or lesson["status"] == "retired":
                continue
            lesson["refutation_count"] = int(lesson["refutation_count"]) + 1
            lesson["revision"] = int(lesson["revision"]) + 1
            lesson["last_seen_step"] = key_record.get("step")
            if event_id is not None:
                lesson["source_event_ids"].append(event_id)
            changed = self._resolve_status(lesson)
            lesson["text"] = self._lesson_text(lesson)
            self._log_lesson("refute", lesson)
            self._log_status_change(changed, lesson)

    def _resolve_status(self, lesson: dict[str, Any]) -> bool:
        previous = lesson["status"]
        support = int(lesson["support_count"])
        refutations = int(lesson["refutation_count"])
        if refutations >= support:
            lesson["status"] = "retired"
        elif support - refutations >= self.lesson_min_support:
            lesson["status"] = "active"
        else:
            lesson["status"] = "candidate"
        return bool(lesson["status"] != previous)

    def _find_lesson(self, signature: str, failure_class: str) -> dict[str, Any] | None:
        for lesson in self.lessons:
            if (
                lesson["signature"] == signature
                and lesson["failure_class"] == failure_class
            ):
                return lesson
        return None

    def _evict_lessons(self) -> None:
        while len(self.lessons) > self.lesson_limit:
            weakest = min(self.lessons, key=self._eviction_rank)
            self.lessons.remove(weakest)
            self._log_lesson("evict", weakest)

    @staticmethod
    def _eviction_rank(lesson: Mapping[str, Any]) -> tuple[int, int, int]:
        status_rank = {"retired": 0, "candidate": 1, "active": 2}
        last_seen = lesson.get("last_seen_step")
        return (
            status_rank.get(str(lesson.get("status")), 1),
            int(lesson["support_count"]) - int(lesson["refutation_count"]),
            int(last_seen) if isinstance(last_seen, int) else 0,
        )

    def _recall_lessons(self, query: Mapping[str, Any]) -> list[dict[str, Any]]:
        if query.get("phase") == "verify":
            return []
        query_words = self._words(str(query.get("task", "")))
        ranked = [
            (self._lesson_score(lesson, query_words), lesson)
            for lesson in self.lessons
            if lesson["status"] == "active"
        ]
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [dict(lesson) for _, lesson in ranked[: self.lesson_recall_limit]]

    def _lesson_score(
        self, lesson: Mapping[str, Any], query_words: set[str]
    ) -> tuple[float, int, int]:
        lesson_words = self._words(
            f"{lesson.get('signature', '')} {lesson.get('subtask', '')}"
        )
        overlap = (
            len(lesson_words & query_words) / len(lesson_words) if lesson_words else 0.0
        )
        last_seen = lesson.get("last_seen_step")
        return (
            overlap,
            int(lesson["support_count"]) - int(lesson["refutation_count"]),
            int(last_seen) if isinstance(last_seen, int) else 0,
        )

    @staticmethod
    def _words(text: str) -> set[str]:
        return set(_WORD_PATTERN.findall(text.lower()))

    @staticmethod
    def _attempt_signature(
        state: Mapping[str, Any],
        event: Mapping[str, Any],
        key_record: Mapping[str, Any],
    ) -> str | None:
        """Build a signature that ignores volatile numeric grounding arguments."""
        skill = key_record.get("skill")
        if not isinstance(skill, str) or not skill:
            return None
        grounded_arguments: Mapping[str, Any] | None = None
        planner_output = event.get("planner_output")
        if isinstance(planner_output, Mapping):
            candidate = planner_output.get("grounded_arguments")
            if isinstance(candidate, Mapping):
                grounded_arguments = candidate
        if grounded_arguments is None:
            active_execution = state.get("active_execution")
            if isinstance(active_execution, Mapping):
                candidate = active_execution.get("grounded_arguments")
                if isinstance(candidate, Mapping):
                    grounded_arguments = candidate
        slots = []
        if grounded_arguments is not None:
            for name in sorted(grounded_arguments):
                value = grounded_arguments[name]
                if not isinstance(value, str):
                    continue
                normalized = " ".join(value.lower().split())
                if normalized:
                    slots.append(f"{name}={normalized}")
        return f"{skill}|{','.join(slots)}"

    @staticmethod
    def _failure_class(event: Mapping[str, Any], key_record: Mapping[str, Any]) -> str:
        environment_result = event.get("environment_result")
        if isinstance(environment_result, Mapping):
            control_failure = environment_result.get("control_failure")
            if isinstance(control_failure, str):
                mapped = CONTROL_FAILURE_CLASSES.get(control_failure)
                if mapped is not None:
                    return mapped
        reason = key_record.get("reason")
        text = str(reason).lower() if reason is not None else ""
        for failure_class, keywords in FAILURE_KEYWORD_CLASSES:
            if any(keyword in text for keyword in keywords):
                return failure_class
        return "unclassified"

    @staticmethod
    def _lesson_text(lesson: Mapping[str, Any]) -> str:
        return (
            f"signature={lesson.get('signature')} "
            f"class={lesson.get('failure_class')} "
            f"failures={lesson.get('support_count')} "
            f"later_successes={lesson.get('refutation_count')} "
            f"last_reason={lesson.get('last_reason')}"
        )

    def _log_status_change(self, changed: bool, lesson: Mapping[str, Any]) -> None:
        if not changed:
            return
        status = str(lesson["status"])
        operation = {
            "active": "promote",
            "retired": "retire",
            "candidate": "demote",
        }[status]
        self._log_lesson(operation, lesson)

    def _load_lessons(self) -> None:
        """Rebuild the lesson store by replaying a previous run's audit log."""
        if self.lesson_path is None or not self.lesson_path.is_file():
            return
        restored: dict[str, dict[str, Any]] = {}
        with self.lesson_path.open(encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(record, Mapping):
                    continue
                lesson = self._restore_lesson(record)
                if lesson is None:
                    continue
                if record.get("operation") == "evict":
                    restored.pop(lesson["lesson_id"], None)
                    continue
                restored[lesson["lesson_id"]] = lesson
        for lesson_id, lesson in restored.items():
            self._lesson_sequence = max(
                self._lesson_sequence, self._lesson_index(lesson_id)
            )
            self._resolve_status(lesson)
            lesson["text"] = self._lesson_text(lesson)
            self.lessons.append(lesson)
        self._evict_lessons()

    @staticmethod
    def _restore_lesson(record: Mapping[str, Any]) -> dict[str, Any] | None:
        """Rebuild one lesson from a log line, skipping malformed records."""
        lesson_id = record.get("lesson_id")
        signature = record.get("signature")
        if not isinstance(lesson_id, str) or not isinstance(signature, str):
            return None
        try:
            support_count = int(record["support_count"])
            refutation_count = int(record["refutation_count"])
            revision = int(record["revision"])
        except (KeyError, TypeError, ValueError):
            return None
        session_ids = record.get("session_ids")
        source_event_ids = record.get("source_event_ids")
        return {
            "lesson_id": lesson_id,
            "signature": signature,
            "skill": record.get("skill"),
            "subtask": record.get("subtask"),
            "failure_class": str(record.get("failure_class", "unclassified")),
            "status": "candidate",
            "support_count": support_count,
            "refutation_count": refutation_count,
            "revision": revision,
            "first_seen_step": record.get("first_seen_step"),
            "last_seen_step": record.get("last_seen_step"),
            "last_reason": record.get("last_reason"),
            "session_ids": list(session_ids) if isinstance(session_ids, list) else [],
            "source_event_ids": (
                list(source_event_ids) if isinstance(source_event_ids, list) else []
            ),
            "text": "",
            "carried_over": True,
        }

    @staticmethod
    def _lesson_index(lesson_id: str) -> int:
        suffix = lesson_id.rpartition(":")[2]
        return int(suffix) if suffix.isdigit() else 0

    def _log_lesson(self, operation: str, lesson: Mapping[str, Any]) -> None:
        if self.lesson_path is None:
            return
        record = {
            "operation": operation,
            "timestamp": datetime.now(UTC).isoformat(),
            **to_jsonable(lesson),
        }
        with self.lesson_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
