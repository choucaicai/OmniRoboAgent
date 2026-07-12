import importlib
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any

import httpx

from omniroboagent.contracts import SkillBackend
from omniroboagent.exceptions import BackendError


class OpenPIWebSocketPolicyBackend(SkillBackend):
    def __init__(
        self,
        host: str,
        port: int,
        api_key: str | None = None,
        timeout_seconds: float = 10.0,
        action_key: str = "actions",
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.host = host.removeprefix("ws://").removeprefix("wss://").rstrip("/")
        self.port = port
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.action_key = action_key
        self.client_factory = client_factory
        self.client: Any = None

    def healthcheck(self) -> dict[str, Any]:
        scheme = "https" if self.host.startswith("https://") else "http"
        host = self.host.removeprefix("http://").removeprefix("https://")
        try:
            response = httpx.get(
                f"{scheme}://{host}:{self.port}/healthz",
                timeout=self.timeout_seconds,
                trust_env=False,
            )
            response.raise_for_status()
            return {"healthy": True, "metadata": self._metadata()}
        except httpx.HTTPError as error:
            return {"healthy": False, "error": str(error)}

    def predict(self, inputs: dict[str, Any]) -> Any:
        observation = inputs.get("observation")
        if not isinstance(observation, dict):
            raise BackendError("OpenPI backend requires an observation dict")
        result: Any = None
        last_error: Exception | None = None
        for attempt in range(2):
            if self.client is None:
                health = self.healthcheck()
                if not health.get("healthy"):
                    raise BackendError(f"OpenPI server healthcheck failed: {health}")
                self.client = self._create_client()
            executor = ThreadPoolExecutor(max_workers=1)
            future = executor.submit(self.client.infer, observation)
            try:
                result = future.result(timeout=self.timeout_seconds)
                executor.shutdown(wait=False)
                break
            except FutureTimeoutError as error:
                last_error = error
                self.close()
                executor.shutdown(wait=False, cancel_futures=True)
                if attempt == 1:
                    raise BackendError(
                        f"OpenPI inference timed out after {self.timeout_seconds}s"
                    ) from error
            except Exception as error:
                last_error = error
                self.close()
                executor.shutdown(wait=False, cancel_futures=True)
        else:
            raise BackendError(f"OpenPI inference failed after reconnect: {last_error}")
        if not isinstance(result, dict) or self.action_key not in result:
            raise BackendError(
                f"OpenPI response is missing action key {self.action_key!r}"
            )
        return result[self.action_key]

    def close(self) -> None:
        if self.client is None:
            return
        websocket = getattr(self.client, "_ws", None)
        if websocket is not None:
            websocket.close()
        self.client = None

    def _create_client(self) -> Any:
        factory = self.client_factory
        if factory is None:
            try:
                module = importlib.import_module(
                    "openpi_client.websocket_client_policy"
                )
            except ImportError as error:
                raise BackendError(
                    "OpenPI support requires: uv pip install --editable '.[openpi]'"
                ) from error
            factory = module.WebsocketClientPolicy
        return factory(host=self.host, port=self.port, api_key=self.api_key)

    def _metadata(self) -> Any:
        if self.client is None:
            return None
        getter = getattr(self.client, "get_server_metadata", None)
        return getter() if getter is not None else None
