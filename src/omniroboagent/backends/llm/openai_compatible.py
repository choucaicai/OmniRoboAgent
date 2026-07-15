import base64
import io
import os
import time
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from omniroboagent.backends.llm.base import LLMBackend
from omniroboagent.exceptions import BackendError


class OpenAICompatibleLLMBackend(LLMBackend):
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        max_retries: int = 2,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        normalized = base_url.rstrip("/")
        self.base_url = normalized if normalized.endswith("/v1") else normalized + "/v1"
        self.model = model
        self.max_retries = max_retries
        self.client = httpx.Client(
            base_url=self.base_url,
            headers={
                "Authorization": (
                    f"Bearer {api_key or os.getenv('OPENAI_API_KEY', 'EMPTY')}"
                )
            },
            timeout=timeout_seconds,
            transport=transport,
            trust_env=False,
        )

    def healthcheck(self) -> dict[str, Any]:
        started = time.monotonic()
        try:
            response = self.client.get("/models")
            response.raise_for_status()
            payload = response.json()
            model_ids = [item.get("id") for item in payload.get("data", [])]
            return {
                "healthy": self.model in model_ids or not model_ids,
                "model": self.model,
                "available_models": model_ids,
                "latency_seconds": time.monotonic() - started,
            }
        except (httpx.HTTPError, ValueError) as error:
            return {
                "healthy": False,
                "model": self.model,
                "error": str(error),
                "latency_seconds": time.monotonic() - started,
            }

    def complete(self, inputs: dict[str, Any]) -> dict[str, Any]:
        messages = inputs.get("messages")
        if not isinstance(messages, list) or not messages:
            raise BackendError("OpenAI backend requires a non-empty messages list")
        payload: dict[str, Any] = {
            "model": inputs.get("model", self.model),
            "messages": self._normalize_messages(messages),
            "temperature": inputs.get("temperature", 0),
            "max_tokens": inputs.get("max_tokens", 2048),
        }
        for key in ("response_format", "seed", "stop", "top_p", "extra_body"):
            if key in inputs and inputs[key] is not None:
                if key == "extra_body":
                    if not isinstance(inputs[key], dict):
                        raise BackendError("extra_body must be a dict")
                    payload.update(inputs[key])
                else:
                    payload[key] = inputs[key]

        started = time.monotonic()
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.client.post("/chat/completions", json=payload)
                response.raise_for_status()
                result = response.json()
                if not isinstance(result, dict):
                    raise BackendError(
                        "OpenAI-compatible response must be a JSON object"
                    )
                result["_backend"] = {
                    "model": payload["model"],
                    "latency_seconds": time.monotonic() - started,
                    "attempts": attempt + 1,
                }
                return result
            except (httpx.HTTPError, ValueError) as error:
                last_error = error
                if attempt < self.max_retries:
                    time.sleep(min(2**attempt, 4))
        raise BackendError(
            "OpenAI-compatible request failed after "
            f"{self.max_retries + 1} attempts: {last_error}"
        ) from last_error

    def close(self) -> None:
        self.client.close()

    def _normalize_messages(self, messages: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for message in messages:
            if not isinstance(message, dict):
                raise BackendError("Each message must be a dict")
            item = dict(message)
            content = item.get("content")
            if isinstance(content, list):
                normalized_content = []
                for part in content:
                    if not isinstance(part, dict):
                        raise BackendError("Multimodal content items must be dicts")
                    part = dict(part)
                    if part.get("type") == "image_url":
                        image_url = part.get("image_url")
                        if not isinstance(image_url, dict) or "url" not in image_url:
                            raise BackendError("image_url content requires a url")
                        part["image_url"] = {
                            **image_url,
                            "url": self._image_to_data_url(image_url["url"]),
                        }
                    normalized_content.append(part)
                item["content"] = normalized_content
            normalized.append(item)
        return normalized

    @staticmethod
    def _image_to_data_url(image: Any) -> str:
        if isinstance(image, str):
            if image.startswith(("data:image/", "http://", "https://")):
                return image
            path = Path(image)
            if not path.is_file():
                raise BackendError(f"Image path does not exist: {path}")
            suffix = path.suffix.lower().lstrip(".") or "png"
            mime = "jpeg" if suffix in {"jpg", "jpeg"} else suffix
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            return f"data:image/{mime};base64,{encoded}"

        if isinstance(image, bytes | bytearray | memoryview):
            encoded = base64.b64encode(bytes(image)).decode("ascii")
            return f"data:image/png;base64,{encoded}"

        try:
            pil_image = (
                image if isinstance(image, Image.Image) else Image.fromarray(image)
            )
        except Exception as error:
            raise BackendError(
                f"Unsupported image type: {type(image).__name__}"
            ) from error
        buffer = io.BytesIO()
        pil_image.save(buffer, format="PNG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/png;base64,{encoded}"
