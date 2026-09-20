from collections.abc import Mapping
from typing import Any

from omniroboagent.agent_core.memories.base import Memory


class CompositeMemory(Memory):
    """Compose independent memory implementations behind one Memory contract."""

    def __init__(self, memories: Mapping[str, Memory]) -> None:
        if not isinstance(memories, Mapping) or not memories:
            raise ValueError("memories must not be empty")
        if any(not isinstance(name, str) or not name for name in memories):
            raise ValueError("memory names must be non-empty strings")
        if any(not isinstance(memory, Memory) for memory in memories.values()):
            raise TypeError("all memories must implement Memory")
        self.memories = dict(memories)

    def reset(self, session_id: str) -> None:
        for memory in self.memories.values():
            memory.reset(session_id)

    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        for memory in self.memories.values():
            memory.update(state, event)

    def recall(self, query: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {
            "working_frames": [],
            "recent_events": [],
            "key_events": [],
            "summary": "",
        }
        summaries: list[str] = []
        for name, memory in self.memories.items():
            context = memory.recall(query)
            if not isinstance(context, dict):
                raise TypeError(f"memory {name!r} recall must return a dict")
            for key in ("working_frames", "recent_events", "key_events"):
                values = context.get(key, [])
                if not isinstance(values, list):
                    raise TypeError(f"memory {name!r} {key} must be a list")
                merged[key].extend(values)
            summary = context.get("summary", "")
            if not isinstance(summary, str):
                raise TypeError(f"memory {name!r} summary must be a string")
            if summary:
                summaries.append(summary)
            for key, value in context.items():
                if key in {"working_frames", "recent_events", "key_events", "summary"}:
                    continue
                if key in merged:
                    raise ValueError(
                        f"memory {name!r} returned duplicate context key {key!r}"
                    )
                merged[key] = value
        merged["summary"] = "\n".join(summaries)
        return merged

    def healthcheck(self) -> dict[str, Any]:
        components = {
            name: memory.healthcheck() for name, memory in self.memories.items()
        }
        return {
            "healthy": all(
                bool(status.get("healthy", False)) for status in components.values()
            ),
            "components": components,
        }

    def close(self) -> None:
        for memory in self.memories.values():
            memory.close()
