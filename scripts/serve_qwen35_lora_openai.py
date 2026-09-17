"""Serve the checked Qwen3.5 LoRA through the small OpenAI API Omni expects."""

from __future__ import annotations

import argparse
import json
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from eval_omni_schedule_lora import (
    DEFAULT_ADAPTER,
    DEFAULT_BASE_MODEL,
    TransformersBackend,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", type=Path, default=DEFAULT_BASE_MODEL)
    parser.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--model-name", default="qwen_schedule")
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    return parser.parse_args()


class QwenServer(HTTPServer):
    backend: TransformersBackend
    model_name: str


class Handler(BaseHTTPRequestHandler):
    server: QwenServer

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/v1/models":
            self._reply(
                200,
                {
                    "object": "list",
                    "data": [
                        {
                            "id": self.server.model_name,
                            "object": "model",
                            "owned_by": "local",
                        }
                    ],
                },
            )
            return
        self._reply(404, {"error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/v1/chat/completions":
            self._reply(404, {"error": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            result = self.server.backend.complete(payload)
            content = result["choices"][0]["message"]["content"]
            self._reply(
                200,
                {
                    "id": f"chatcmpl-{time.time_ns()}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": self.server.model_name,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": content},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {},
                },
            )
        except Exception as error:  # Keep the server alive and expose the cause.
            print(
                json.dumps(
                    {
                        "status": "request_error",
                        "error_type": type(error).__name__,
                        "error": str(error),
                        "traceback": traceback.format_exc(),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            self._reply(
                500,
                {
                    "error": {
                        "type": type(error).__name__,
                        "message": str(error),
                    }
                },
            )

    def log_message(self, format: str, *args: Any) -> None:
        print(format % args, flush=True)

    def _reply(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def main() -> None:
    args = parse_args()
    backend = TransformersBackend(
        args.base_model.resolve(),
        args.adapter.resolve(),
        temperature=args.temperature,
        top_p=args.top_p,
        top_k=args.top_k,
        max_new_tokens=args.max_new_tokens,
    )
    server = QwenServer((args.host, args.port), Handler)
    server.backend = backend
    server.model_name = args.model_name
    print(
        json.dumps(
            {
                "status": "ready",
                "host": args.host,
                "port": args.port,
                "model": args.model_name,
                "base_model": str(args.base_model.resolve()),
                "adapter": str(args.adapter.resolve()),
            }
        ),
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
