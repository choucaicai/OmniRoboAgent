import importlib
from collections.abc import Callable, Mapping
from typing import Any

import httpx
from PIL import Image

from omniroboagent.backends.skills.base import SkillBackend
from omniroboagent.exceptions import BackendError

_ROBOCASA_CAMERAS = {
    "video.robot0_agentview_left": "observation/image",
    "video.robot0_eye_in_hand": "observation/wrist_image",
    "video.robot0_agentview_right": "observation/right_image",
}
_ROBOCASA_STATE_DIMS = {
    "state.end_effector_position_relative": 3,
    "state.end_effector_rotation_relative": 4,
    "state.base_position": 3,
    "state.base_rotation": 4,
    "state.gripper_qpos": 2,
}
_ACTION_RANGE_TOLERANCE = 0.05


class _OpenPIClient:
    def __init__(
        self,
        host: str,
        port: int,
        api_key: str | None,
        timeout_seconds: float,
    ) -> None:
        try:
            self._serializer = importlib.import_module("openpi_client.msgpack_numpy")
            websocket_client = importlib.import_module("websockets.sync.client")
        except ImportError as error:
            raise BackendError(
                "OpenPI support requires: uv pip install --editable '.[openpi]'"
            ) from error
        headers = {"Authorization": f"Api-Key {api_key}"} if api_key else None
        self.timeout_seconds = timeout_seconds
        self._ws = websocket_client.connect(
            f"ws://{host}:{port}",
            compression=None,
            max_size=None,
            additional_headers=headers,
            open_timeout=timeout_seconds,
            close_timeout=timeout_seconds,
        )
        try:
            metadata = self._ws.recv(timeout=timeout_seconds)
            if isinstance(metadata, str):
                raise BackendError(
                    "OpenPI server returned text instead of metadata bytes"
                )
            self._server_metadata = self._serializer.unpackb(metadata)
        except Exception:
            self._ws.close()
            raise

    def infer(self, observation: dict[str, Any]) -> Any:
        self._ws.send(self._serializer.packb(observation))
        response = self._ws.recv(timeout=self.timeout_seconds)
        if isinstance(response, str):
            raise BackendError("OpenPI server returned text instead of action bytes")
        return self._serializer.unpackb(response)

    def get_server_metadata(self) -> Any:
        return self._server_metadata

    def close(self) -> None:
        self._ws.close()


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
        if not isinstance(host, str) or not host.strip():
            raise ValueError("OpenPI host must be a non-empty string")
        if host.startswith(("wss://", "https://")):
            raise ValueError("The official OpenPI client supports ws:// only")
        if port <= 0 or timeout_seconds <= 0:
            raise ValueError("OpenPI port and timeout_seconds must be positive")
        self.host = host.removeprefix("ws://").removeprefix("http://").rstrip("/")
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
            return {
                "healthy": True,
                "protocol": "openpi-websocket-msgpack",
                "host": self.host,
                "port": self.port,
                "metadata": self._metadata(),
            }
        except httpx.HTTPError as error:
            return {"healthy": False, "error": str(error)}

    def predict(self, inputs: dict[str, Any]) -> Any:
        observation = self._prepare_observation(inputs)
        result = self._infer(observation)
        return self._extract_action(result)

    def _prepare_observation(self, inputs: dict[str, Any]) -> dict[str, Any]:
        observation = inputs.get("observation")
        if not isinstance(observation, dict):
            raise BackendError("OpenPI backend requires an observation dict")
        observation = dict(observation)
        skill = inputs.get("skill")
        subtask = inputs.get("subtask")
        if skill is not None:
            observation["skill"] = skill
        if isinstance(subtask, str) and subtask:
            observation["prompt"] = subtask
            observation["annotation.human.task_description"] = subtask
        return observation

    def _infer(self, observation: dict[str, Any]) -> Any:
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                if self.client is None:
                    health = self.healthcheck()
                    if not health.get("healthy"):
                        raise BackendError(
                            f"OpenPI server healthcheck failed: {health}"
                        )
                    self.client = self._create_client()
                return self.client.infer(observation)
            except TimeoutError as error:
                last_error = error
                self.close()
                if attempt == 1:
                    raise BackendError(
                        f"OpenPI inference timed out after {self.timeout_seconds}s"
                    ) from error
            except Exception as error:
                last_error = error
                self.close()
        raise BackendError(f"OpenPI inference failed after reconnect: {last_error}")

    def _extract_action(self, result: Any) -> Any:
        if not isinstance(result, dict) or self.action_key not in result:
            raise BackendError(
                f"OpenPI response is missing action key {self.action_key!r}"
            )
        return result[self.action_key]

    def close(self) -> None:
        if self.client is None:
            return
        close = getattr(self.client, "close", None)
        if callable(close):
            close()
        else:
            websocket = getattr(self.client, "_ws", None)
            if websocket is not None:
                websocket.close()
        self.client = None

    def _create_client(self) -> Any:
        factory = self.client_factory
        if factory is None:
            return _OpenPIClient(
                host=self.host,
                port=self.port,
                api_key=self.api_key,
                timeout_seconds=self.timeout_seconds,
            )
        try:
            return factory(
                host=self.host,
                port=self.port,
                api_key=self.api_key,
                timeout_seconds=self.timeout_seconds,
            )
        except TypeError:
            return factory(host=self.host, port=self.port, api_key=self.api_key)

    def _metadata(self) -> Any:
        if self.client is None:
            return None
        getter = getattr(self.client, "get_server_metadata", None)
        return getter() if getter is not None else None


class OpenPIRoboCasaPolicyBackend(OpenPIWebSocketPolicyBackend):
    """Adapt RoboCasa observations and OpenPI 12-D actions over WebSocket."""

    def __init__(self, *args: Any, image_size: int = 224, **kwargs: Any) -> None:
        if image_size <= 0:
            raise ValueError("image_size must be positive")
        super().__init__(*args, **kwargs)
        self.image_size = image_size

    def _prepare_observation(self, inputs: dict[str, Any]) -> dict[str, Any]:
        try:
            import numpy as np
        except ImportError as error:
            raise BackendError("OpenPI RoboCasa backend requires NumPy") from error

        observation = inputs.get("observation")
        if not isinstance(observation, Mapping):
            raise BackendError("OpenPI backend requires an observation dict")

        request: dict[str, Any] = {}
        for source_key, target_key in _ROBOCASA_CAMERAS.items():
            if source_key not in observation:
                raise BackendError(
                    f"OpenPI RoboCasa observation is missing camera {source_key!r}"
                )
            image = np.asarray(observation[source_key])
            if image.ndim != 3 or image.shape[-1] != 3:
                raise BackendError(
                    f"OpenPI RoboCasa camera {source_key!r} must be [H,W,3], "
                    f"got {image.shape}"
                )
            if np.issubdtype(image.dtype, np.floating):
                if (
                    not np.isfinite(image).all()
                    or np.any(image < 0)
                    or np.any(image > 1)
                ):
                    raise BackendError(
                        f"OpenPI RoboCasa camera {source_key!r} float values must "
                        "be finite and in [0, 1]"
                    )
                image = (image * 255).astype(np.uint8)
            elif image.dtype != np.uint8:
                raise BackendError(
                    f"OpenPI RoboCasa camera {source_key!r} must be uint8 or float"
                )
            if image.shape[:2] != (self.image_size, self.image_size):
                image = np.asarray(
                    Image.fromarray(image).resize(
                        (self.image_size, self.image_size), Image.Resampling.BILINEAR
                    )
                )
            request[target_key] = np.ascontiguousarray(image)

        state_parts = []
        for key, width in _ROBOCASA_STATE_DIMS.items():
            if key not in observation:
                raise BackendError(
                    f"OpenPI RoboCasa observation is missing state {key!r}"
                )
            value = np.asarray(observation[key])
            if value.shape != (width,) or not np.issubdtype(value.dtype, np.floating):
                raise BackendError(
                    f"OpenPI RoboCasa state {key!r} must be a float [{width}], "
                    f"got shape={value.shape}, dtype={value.dtype}"
                )
            if not np.isfinite(value).all():
                raise BackendError(
                    f"OpenPI RoboCasa state {key!r} must contain finite floats"
                )
            state_parts.append(value)
        request["observation/state"] = np.concatenate(state_parts)

        subtask = inputs.get("subtask")
        prompt = (
            subtask
            if isinstance(subtask, str) and subtask
            else observation.get("annotation.human.task_description")
        )
        if not isinstance(prompt, str) or not prompt:
            raise BackendError("OpenPI RoboCasa backend requires a non-empty prompt")
        request["prompt"] = prompt
        if isinstance(inputs.get("skill"), str):
            request["skill"] = inputs["skill"]
        return request

    def _extract_action(self, result: Any) -> dict[str, Any]:
        try:
            import numpy as np
        except ImportError as error:
            raise BackendError("OpenPI RoboCasa backend requires NumPy") from error

        actions = np.asarray(super()._extract_action(result))
        if actions.ndim == 3 and actions.shape[0] == 1:
            actions = actions[0]
        if actions.ndim != 2 or actions.shape[1] != 12:
            raise BackendError(
                f"OpenPI RoboCasa actions must be [T,12], got {actions.shape}"
            )
        if (
            not np.issubdtype(actions.dtype, np.floating)
            or not np.isfinite(actions).all()
        ):
            raise BackendError("OpenPI RoboCasa actions must contain finite floats")
        if np.any(actions < -1.0 - _ACTION_RANGE_TOLERANCE) or np.any(
            actions > 1.0 + _ACTION_RANGE_TOLERANCE
        ):
            raise BackendError(
                "OpenPI RoboCasa actions exceed controller range tolerance"
            )
        if actions.shape[0] == 0:
            raise BackendError("OpenPI RoboCasa action chunk must not be empty")
        return {
            "action.end_effector_position": actions[:, 0:3],
            "action.end_effector_rotation": actions[:, 3:6],
            "action.gripper_close": actions[:, 6:7],
            "action.base_motion": actions[:, 7:11],
            "action.control_mode": actions[:, 11:12],
        }
