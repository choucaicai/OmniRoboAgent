import json
from pathlib import Path
from typing import Any

from omniroboagent.agent_core.memories.base import Memory
from omniroboagent.serialization import to_jsonable


class JsonlMemory(Memory):
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        record = {
            "session_id": state.get("session_id"),
            "step": state.get("step"),
            "event": to_jsonable(event),
        }
        with self.path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
