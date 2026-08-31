"""Parse AwareVLN reason/action output into the robot action vocabulary."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

ACTION_STOP = 0
ACTION_FORWARD = 1
ACTION_LEFT = 2
ACTION_RIGHT = 3

FORWARD_STEP_CM = 25.0
TURN_STEP_DEGREES = 15.0
MAX_ACTION_REPEATS = 3

_REASON_PREFIX = re.compile(
    r"^\s*(?:<begin_of_reasoning>|\[reason\])\s*",
    re.IGNORECASE,
)
_ACTION_PREFIX = re.compile(
    r"^\s*(?:<begin_of_action>|\[act\])\s*",
    re.IGNORECASE,
)
_LEADING_SPECIAL_TOKEN = re.compile(r"^\s*<\|begin_of_text\|>\s*", re.IGNORECASE)
_TRAILING_SPECIAL_TOKENS = re.compile(
    r"(?:<end_of_reasoning>|<end_of_action>|<\|end_of_text\|>|<\|eot_id\|>)\s*$",
    re.IGNORECASE,
)
_REASONING_LABEL = re.compile(
    r"^\s*(?:new\s*reasoning\s*is|reasoning)\s*[:\-]?\s*",
    re.IGNORECASE,
)
_PLACEHOLDER_REASON_TOKEN = re.compile(
    r"\[?ph_reasoning_token_?\]?",
    re.IGNORECASE,
)
_COMMAND_PATTERN = re.compile(
    r"\bstop\b"
    r"|\bmove\s+forward(?:\s+(?:by|for))?"
    r"(?:\s+(?P<forward_value>\d+(?:\.\d+)?))?"
    r"(?:\s*(?:cm|centimeters?))?"
    r"|\bturn\s+left(?:\s+(?:by|for))?"
    r"(?:\s+(?P<left_value>\d+(?:\.\d+)?))?"
    r"(?:\s*degrees?)?"
    r"|\bturn\s+right(?:\s+(?:by|for))?"
    r"(?:\s+(?P<right_value>\d+(?:\.\d+)?))?"
    r"(?:\s*degrees?)?",
    re.IGNORECASE,
)


class ActionParseError(ValueError):
    """Raised when an action-mode response has no safe, supported command."""


@dataclass(frozen=True)
class ParsedAwareVLNOutput:
    mode: Literal["reason", "act"]
    content: str
    actions: tuple[int, ...]
    command: str | None = None
    requested_quantity: float | None = None


def _strip_output_tokens(text: str) -> str:
    content = text.strip()
    content = _LEADING_SPECIAL_TOKEN.sub("", content)
    while True:
        stripped = _TRAILING_SPECIAL_TOKENS.sub("", content).strip()
        if stripped == content:
            return content
        content = stripped


def _repeat_count(value: float | None, unit: float) -> int:
    if value is None:
        return 1
    if not math.isfinite(value) or value <= 0:
        raise ActionParseError(f"Action quantity must be positive, got {value!r}")
    return min(MAX_ACTION_REPEATS, max(1, int(value / unit + 0.5)))


def parse_awarevln_output(text: str) -> ParsedAwareVLNOutput:
    """Parse one official AwareVLN generation.

    AwareVLN emits either a reasoning turn or one action command. Distances
    and angles are quantized to the robot's 25 cm / 15 degree primitives.
    Unknown action text fails explicitly instead of defaulting to motion.
    """

    if not isinstance(text, str) or not text.strip():
        raise ActionParseError("AwareVLN output is empty")

    content = _strip_output_tokens(text)
    reason_match = _REASON_PREFIX.match(content)
    if reason_match:
        reasoning = content[reason_match.end() :]
        reasoning = _PLACEHOLDER_REASON_TOKEN.sub("", reasoning)
        reasoning = _REASONING_LABEL.sub("", reasoning)
        reasoning = _strip_output_tokens(reasoning).strip(" '\"\n\t")
        if not reasoning:
            raise ActionParseError("AwareVLN reasoning output is empty")
        return ParsedAwareVLNOutput(
            mode="reason",
            content=reasoning,
            actions=(),
        )

    action_match = _ACTION_PREFIX.match(content)
    if action_match:
        content = content[action_match.end() :]
    content = _strip_output_tokens(content).strip()

    command_matches = list(_COMMAND_PATTERN.finditer(content))
    if not command_matches:
        raise ActionParseError(f"Unsupported AwareVLN action output: {content!r}")

    command_types = set()
    for match in command_matches:
        lowered = match.group(0).lower()
        if "stop" in lowered:
            command_types.add("stop")
        elif "forward" in lowered:
            command_types.add("forward")
        elif "left" in lowered:
            command_types.add("left")
        else:
            command_types.add("right")
    if len(command_types) != 1:
        raise ActionParseError(f"Ambiguous AwareVLN action output: {content!r}")

    match = command_matches[0]
    command = command_types.pop()
    if command == "stop":
        return ParsedAwareVLNOutput(
            mode="act",
            content=content,
            actions=(ACTION_STOP,),
            command=command,
        )

    group_name = f"{command}_value"
    value_text = match.groupdict().get(group_name)
    value = float(value_text) if value_text is not None else None

    if command == "forward":
        count = _repeat_count(value, FORWARD_STEP_CM)
        action_id = ACTION_FORWARD
    elif command == "left":
        count = _repeat_count(value, TURN_STEP_DEGREES)
        action_id = ACTION_LEFT
    else:
        count = _repeat_count(value, TURN_STEP_DEGREES)
        action_id = ACTION_RIGHT

    return ParsedAwareVLNOutput(
        mode="act",
        content=content,
        actions=(action_id,) * count,
        command=command,
        requested_quantity=value,
    )
