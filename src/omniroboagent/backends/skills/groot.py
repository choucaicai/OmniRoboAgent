import importlib
import os
from collections.abc import Callable, Mapping
from io import BytesIO
from pathlib import Path
from typing import Any

from omniroboagent.backends.skills.base import SkillBackend
from omniroboagent.exceptions import BackendError, ConfigError

_ACTION_DIMS = {
    "action.end_effector_position": 3,
    "action.end_effector_rotation": 3,
    "action.gripper_close": 1,
    "action.base_motion": 4,
    "action.control_mode": 1,
}
_VIDEO_KEYS = (
    "video.robot0_agentview_left",
    "video.robot0_agentview_right",
    "video.robot0_eye_in_hand",
)
_STATE_DIMS = {
    "state.gripper_qpos": 2,
    "state.base_position": 3,
    "state.base_rotation": 4,
    "state.end_effector_position_relative": 3,
    "state.end_effector_rotation_relative": 4,
}
_ACTION_RANGE_TOLERANCE = 0.05


class _GR00TZMQClient:
    def __init__(
        self,
        host: str,
        port: int,
        api_token: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        try:
            self.torch = importlib.import_module("torch")
            self.zmq = importlib.import_module("zmq")
        except ImportError as error:
            raise BackendError(
                "GR00T remote support requires torch and pyzmq"
            ) from error
        self.api_token = api_token
        self.context = self.zmq.Context()
        self.socket = self.context.socket(self.zmq.REQ)
        timeout_ms = max(1, int(timeout_seconds * 1000))
        self.socket.setsockopt(self.zmq.SNDTIMEO, timeout_ms)
        self.socket.setsockopt(self.zmq.RCVTIMEO, timeout_ms)
        self.socket.setsockopt(self.zmq.LINGER, 0)
        self.socket.connect(f"tcp://{host}:{port}")

    def ping(self) -> bool:
        response = self.call_endpoint("ping", requires_input=False)
        return response.get("status") == "ok"

    def get_action(self, observations: dict[str, Any]) -> dict[str, Any]:
        return self.call_endpoint("get_action", observations)

    def call_endpoint(
        self,
        endpoint: str,
        data: dict[str, Any] | None = None,
        requires_input: bool = True,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {"endpoint": endpoint}
        if requires_input:
            request["data"] = data
        if self.api_token:
            request["api_token"] = self.api_token
        buffer = BytesIO()
        self.torch.save(request, buffer)
        self.socket.send(buffer.getvalue())
        response = self.torch.load(BytesIO(self.socket.recv()), weights_only=False)
        if not isinstance(response, dict):
            raise BackendError("GR00T server returned a non-dict response")
        if "error" in response:
            raise BackendError(f"GR00T server error: {response['error']}")
        return response


def _task_skill(inputs: dict[str, Any]) -> tuple[str, str, int | None]:
    task = inputs.get("task")
    task_name = task.get("name") if isinstance(task, Mapping) else task
    skill = inputs.get("skill")
    if not isinstance(task_name, str) or not task_name:
        raise BackendError("GR00T backend requires a concrete RoboCasa task name")
    if not isinstance(skill, str) or not skill:
        raise BackendError("GR00T backend requires a non-empty skill")

    planner_output = inputs.get("planner_output")
    if isinstance(planner_output, Mapping) and "skill_id" in planner_output:
        has_skill_id = True
        skill_id = planner_output["skill_id"]
    else:
        has_skill_id = False
        skill_id = None
    if has_skill_id and (
        not isinstance(skill_id, int) or isinstance(skill_id, bool) or skill_id < 0
    ):
        raise BackendError("GR00T planner skill_id must be a non-negative integer")
    if not has_skill_id and skill != task_name:
        raise BackendError(
            "GR00T requires skill to equal the concrete RoboCasa task name when "
            f"planner_output.skill_id is absent; expected {task_name!r}, got {skill!r}"
        )
    return task_name, skill, skill_id


def _prepare_request(inputs: dict[str, Any]) -> dict[str, Any]:
    try:
        import numpy as np
    except ImportError as error:
        raise BackendError("GR00T backend requires NumPy") from error

    observation = inputs.get("observation")
    if not isinstance(observation, Mapping):
        raise BackendError("GR00T backend requires an observation dict")
    task_name, skill, skill_id = _task_skill(inputs)
    request: dict[str, Any] = {}
    for key in _VIDEO_KEYS:
        if key not in observation:
            raise BackendError(f"GR00T observation is missing video {key!r}")
        array = np.asarray(observation[key])
        if array.dtype != np.uint8:
            raise BackendError(f"GR00T video {key!r} must use uint8 dtype")
        if array.ndim == 3:
            array = array[None, None, ...]
        elif array.ndim == 4:
            array = array[None, ...]
        if (
            array.ndim != 5
            or array.shape[0] != 1
            or array.shape[-1] != 3
            or min(array.shape[1:4]) <= 0
        ):
            raise BackendError(
                f"GR00T video {key!r} must be [1,T,H,W,3], got {array.shape}"
            )
        request[key] = array

    for key, width in _STATE_DIMS.items():
        if key not in observation:
            raise BackendError(f"GR00T observation is missing state {key!r}")
        array = np.asarray(observation[key])
        if not np.issubdtype(array.dtype, np.floating) or not np.isfinite(array).all():
            raise BackendError(f"GR00T state {key!r} must contain finite floats")
        if array.ndim == 1:
            array = array[None, None, ...]
        elif array.ndim == 2:
            array = array[None, ...]
        if array.ndim != 3 or array.shape[0] != 1 or array.shape[-1] != width:
            raise BackendError(
                f"GR00T state {key!r} must be [1,T,{width}], got {array.shape}"
            )
        request[key] = array

    for key, value in observation.items():
        if isinstance(key, str) and key.startswith("annotation."):
            request[key] = np.asarray([value])
    if "vis_prompt" in observation:
        request["vis_prompt"] = observation["vis_prompt"]

    subtask = inputs.get("subtask")
    if isinstance(subtask, str) and subtask:
        request["annotation.human.task_description"] = np.asarray([subtask])
    request["skill"] = np.asarray([skill])
    request["task"] = np.asarray([task_name])
    if skill_id is not None:
        request["skill_id"] = np.asarray([skill_id], dtype=np.int64)
    task = inputs.get("task")
    request["episode_index"] = np.asarray(
        [int(task.get("episode_index", 0)) if isinstance(task, Mapping) else 0]
    )
    request.setdefault(
        "vis_prompt",
        [
            {
                "has_vis_prompt": False,
                "anchor_image": np.zeros((448, 448, 3), dtype=np.uint8),
                "mask_prompt": np.zeros((448, 448), dtype=bool),
            }
        ],
    )
    return request


def _validate_actions(result: Any) -> dict[str, Any]:
    try:
        import numpy as np
    except ImportError as error:
        raise BackendError("GR00T backend requires NumPy") from error

    if isinstance(result, Mapping) and "actions" in result:
        result = result["actions"]
    if not isinstance(result, Mapping):
        raise BackendError("GR00T policy must return an action dict")

    actions: dict[str, Any] = {}
    horizons: set[int] = set()
    for key, width in _ACTION_DIMS.items():
        if key not in result:
            raise BackendError(f"GR00T action is missing key {key!r}")
        array = np.asarray(result[key])
        if array.ndim == 3 and array.shape[0] == 1:
            array = array[0]
        if array.ndim != 2 or array.shape[1] != width:
            raise BackendError(
                f"GR00T action {key!r} must be [T,{width}], got {array.shape}"
            )
        if not np.issubdtype(array.dtype, np.floating) or not np.isfinite(array).all():
            raise BackendError(f"GR00T action {key!r} must contain finite floats")
        if np.any(array < -1.0 - _ACTION_RANGE_TOLERANCE) or np.any(
            array > 1.0 + _ACTION_RANGE_TOLERANCE
        ):
            raise BackendError(
                f"GR00T action {key!r} exceeds controller range tolerance"
            )
        horizons.add(int(array.shape[0]))
        actions[key] = array
    if len(horizons) != 1 or next(iter(horizons), 0) <= 0:
        raise BackendError("GR00T action keys must share a positive chunk horizon")
    return actions


class GR00TRemotePolicyBackend(SkillBackend):
    def __init__(
        self,
        host: str = "localhost",
        port: int = 5555,
        timeout_seconds: float = 120.0,
        api_token: str | None = None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.api_token = api_token
        self.client_factory = client_factory
        self.client: Any = None
        self._episode_marker: tuple[Any, ...] | None = None

    def healthcheck(self) -> dict[str, Any]:
        try:
            client = self._ensure_client()
            healthy = bool(client.ping())
            if not healthy:
                self.close()
            result = {
                "healthy": healthy,
                "protocol": "groot-zmq-torch",
                "host": self.host,
                "port": self.port,
            }
            if healthy:
                try:
                    result["metadata"] = client.call_endpoint(
                        "metadata", requires_input=False
                    )
                except Exception:
                    pass
            return result
        except Exception as error:
            self.close()
            return {"healthy": False, "error": str(error)}

    def predict(self, inputs: dict[str, Any]) -> dict[str, Any]:
        request = _prepare_request(inputs)
        marker = (
            inputs.get("session_id"),
            request["task"][0],
            int(request["episode_index"][0]),
        )
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                client = self._ensure_client()
                if marker != self._episode_marker:
                    client.call_endpoint("reset_episode_memory", requires_input=False)
                    self._episode_marker = marker
                return _validate_actions(client.get_action(request))
            except Exception as error:
                last_error = error
                self.close()
                if attempt == 1:
                    break
        raise BackendError(
            f"GR00T remote inference failed: {last_error}"
        ) from last_error

    def close(self) -> None:
        if self.client is None:
            return
        socket = getattr(self.client, "socket", None)
        context = getattr(self.client, "context", None)
        if socket is not None:
            socket.close(linger=0)
        if context is not None:
            context.term()
        self.client = None
        self._episode_marker = None

    def _ensure_client(self) -> Any:
        if self.client is not None:
            return self.client
        factory = self.client_factory
        if factory is None:
            factory = _GR00TZMQClient
        try:
            client = factory(
                host=self.host,
                port=self.port,
                api_token=self.api_token,
                timeout_seconds=self.timeout_seconds,
            )
        except TypeError:
            client = factory(host=self.host, port=self.port, api_token=self.api_token)
        socket = getattr(client, "socket", None)
        if socket is not None:
            try:
                zmq = importlib.import_module("zmq")
                timeout_ms = max(1, int(self.timeout_seconds * 1000))
                socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
                socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
                socket.setsockopt(zmq.LINGER, 0)
            except (ImportError, AttributeError):
                pass
        self.client = client
        return client


class GR00TLocalPolicyAdapter:
    """Load the reference RoboCasa GR00T policy for LocalPolicyBackend."""

    def __init__(
        self,
        model_path: str | None = None,
        model_path_env: str = "OMNIROBOAGENT_GROOT_MODEL_PATH",
        policy_class_path: str = "gr00t.model_moe_v1.policy.Gr00tPolicy",
        data_config_module: str = "gr00t.experiment.data_config_mem_groot",
        data_config: str = "panda_omron",
        embodiment_tag: str = "new_embodiment",
        denoising_steps: int = 4,
        device: str = "cuda:0",
        memory_queue_size: int = 0,
    ) -> None:
        resolved_model_path = model_path or os.environ.get(model_path_env)
        if not resolved_model_path:
            raise ConfigError(
                "GR00T local policy requires model_path or environment variable "
                f"{model_path_env}"
            )
        self.model_path = str(Path(resolved_model_path).expanduser())
        self.model_path_env = model_path_env
        self.policy_class_path = policy_class_path
        self.data_config_module = data_config_module
        self.data_config = data_config
        self.embodiment_tag = embodiment_tag
        self.denoising_steps = denoising_steps
        self.device = device
        self.memory_queue_size = memory_queue_size
        self.policy: Any = None
        self._episode_marker: tuple[Any, ...] | None = None

    def healthcheck(self) -> dict[str, Any]:
        model_path = Path(self.model_path)
        return {
            "healthy": model_path.exists(),
            "model_path": str(model_path.resolve()),
            "policy_class_path": self.policy_class_path,
            "loaded": self.policy is not None,
        }

    def _load_policy(self) -> Any:
        if self.policy is not None:
            return self.policy
        try:
            config_module = importlib.import_module(self.data_config_module)
            config = config_module.DATA_CONFIG_MAP[self.data_config]
            module_name, class_name = self.policy_class_path.rsplit(".", 1)
            policy_class = getattr(importlib.import_module(module_name), class_name)
        except (ImportError, AttributeError, KeyError, ValueError) as error:
            raise BackendError(
                f"Failed to load GR00T policy configuration: {error}"
            ) from error
        self.policy = policy_class(
            model_path=self.model_path,
            modality_config=config.modality_config(),
            modality_transform=config.transform(),
            embodiment_tag=self.embodiment_tag,
            denoising_steps=self.denoising_steps,
            device=self.device,
            memory_queue_size=self.memory_queue_size,
        )
        return self.policy

    def predict(self, inputs: dict[str, Any]) -> dict[str, Any]:
        policy = self._load_policy()
        request = _prepare_request(inputs)
        marker = (
            inputs.get("session_id"),
            request["task"][0],
            int(request["episode_index"][0]),
        )
        if marker != self._episode_marker:
            reset = getattr(policy, "reset_episode_memory", None)
            if callable(reset):
                reset()
            self._episode_marker = marker
        return _validate_actions(policy.get_action(request))

    def close(self) -> None:
        if self.policy is None:
            return
        close = getattr(self.policy, "close", None)
        if callable(close):
            close()
        self.policy = None
