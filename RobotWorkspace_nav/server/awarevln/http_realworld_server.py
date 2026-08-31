"""HTTP inference service for the official AwareVLN checkpoint."""

from __future__ import annotations

import io
import json
import os
import re
import threading
from argparse import ArgumentParser, Namespace
from collections import OrderedDict
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request
from PIL import Image, UnidentifiedImageError

from .action_parser import ActionParseError
from .policy import AwareVLNPolicy, AwareVLNSession

_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")


class RequestValidationError(ValueError):
    """Raised when the HTTP request does not satisfy the navigation protocol."""


def _request_payload() -> dict[str, Any]:
    raw_payload = request.form.get("json", "{}")
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as error:
        raise RequestValidationError(f"Invalid json form field: {error.msg}") from error
    if not isinstance(payload, dict):
        raise RequestValidationError("json form field must contain an object")
    return payload


def _request_image() -> Image.Image:
    upload = request.files.get("image")
    if upload is None:
        raise RequestValidationError("Missing multipart image field")
    try:
        image = Image.open(io.BytesIO(upload.read()))
        image.load()
    except (UnidentifiedImageError, OSError) as error:
        raise RequestValidationError("image field is not a valid image") from error
    return image.convert("RGB")


def create_app(
    policy: AwareVLNPolicy,
    *,
    default_instruction: str | None = None,
    max_sessions: int = 8,
) -> Flask:
    if max_sessions <= 0:
        raise ValueError("max_sessions must be positive")

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024
    sessions: OrderedDict[str, AwareVLNSession] = OrderedDict()
    inference_lock = threading.Lock()

    @app.get("/healthz")
    def healthz():
        return jsonify({**policy.health(), "sessions": len(sessions)})

    @app.post("/eval_vln")
    def eval_vln():
        try:
            payload = _request_payload()
            image = _request_image()

            reset = payload.get("reset", False)
            if not isinstance(reset, bool):
                raise RequestValidationError("reset must be a boolean")

            session_id = payload.get("session_id", "default")
            if not isinstance(session_id, str) or not _SESSION_ID_PATTERN.fullmatch(
                session_id
            ):
                raise RequestValidationError(
                    "session_id must contain 1-128 letters, digits, '.', '_' or '-'"
                )

            requested_instruction = payload.get("instruction")
            if requested_instruction is not None and not isinstance(
                requested_instruction, str
            ):
                raise RequestValidationError("instruction must be a string")

            with inference_lock:
                if reset:
                    instruction = (
                        requested_instruction
                        if requested_instruction is not None
                        else default_instruction
                    )
                    if instruction is None or not instruction.strip():
                        raise RequestValidationError(
                            "instruction is required when reset=true and no "
                            "server default is configured"
                        )
                    session = policy.new_session(instruction)
                    sessions[session_id] = session
                else:
                    session = sessions.get(session_id)
                    if session is None:
                        return (
                            jsonify(
                                {
                                    "error": "unknown_session",
                                    "message": (
                                        "Start the episode with reset=true and an "
                                        "instruction"
                                    ),
                                }
                            ),
                            409,
                        )
                    if (
                        requested_instruction is not None
                        and requested_instruction.strip() != session.instruction
                    ):
                        return (
                            jsonify(
                                {
                                    "error": "instruction_changed",
                                    "message": (
                                        "Changing instruction requires reset=true"
                                    ),
                                }
                            ),
                            409,
                        )

                sessions.move_to_end(session_id)
                while len(sessions) > max_sessions:
                    sessions.popitem(last=False)

                prediction = policy.predict(session, image)

            return jsonify(
                {
                    "action": list(prediction.actions),
                    "mode": prediction.mode,
                    "terminal": prediction.terminal,
                    "reasoning": list(prediction.reasoning),
                    "raw_output": prediction.raw_output,
                    "session_id": session_id,
                }
            )
        except ActionParseError as error:
            return (
                jsonify({"error": "unparseable_model_output", "message": str(error)}),
                422,
            )
        except RequestValidationError as error:
            return (
                jsonify({"error": "invalid_request", "message": str(error)}),
                400,
            )
        except Exception:
            app.logger.exception("AwareVLN inference failed")
            return (
                jsonify(
                    {
                        "error": "inference_failed",
                        "message": "AwareVLN inference failed; inspect server logs",
                    }
                ),
                500,
            )

    return app


def _parse_args() -> Namespace:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument(
        "--awarevln_root",
        default=os.environ.get("AWAREVLN_ROOT"),
        help="Path to the official GWxuan/AwareVLN repository",
    )
    parser.add_argument(
        "--model_path",
        default=os.environ.get("AWAREVLN_MODEL_PATH"),
        help="Path to the local AwareVLN checkpoint directory",
    )
    parser.add_argument(
        "--device",
        default=os.environ.get("AWAREVLN_DEVICE", "cuda:0"),
    )
    parser.add_argument(
        "--default_instruction",
        default=os.environ.get("AWAREVLN_DEFAULT_INSTRUCTION"),
        help="Fallback instruction for legacy clients that only send reset",
    )
    parser.add_argument("--max_new_tokens", type=int, default=256)
    parser.add_argument("--max_reasoning_turns", type=int, default=4)
    parser.add_argument("--max_history_frames", type=int, default=128)
    parser.add_argument("--max_sessions", type=int, default=8)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5802)
    args = parser.parse_args()
    if not args.awarevln_root:
        parser.error("--awarevln_root or AWAREVLN_ROOT is required")
    if not args.model_path:
        parser.error("--model_path or AWAREVLN_MODEL_PATH is required")
    return args


def main() -> None:
    args = _parse_args()
    policy = AwareVLNPolicy(
        awarevln_root=Path(args.awarevln_root),
        model_path=Path(args.model_path),
        device=args.device,
        max_new_tokens=args.max_new_tokens,
        max_reasoning_turns=args.max_reasoning_turns,
        max_history_frames=args.max_history_frames,
    )
    app = create_app(
        policy,
        default_instruction=args.default_instruction,
        max_sessions=args.max_sessions,
    )
    app.run(host=args.host, port=args.port, threaded=True, debug=False)


if __name__ == "__main__":
    main()
