"""Single-owner client for the Chemistry Bench Isaac Sim chemistry worker."""

import importlib
import json
import math
from importlib.resources import files
from io import BytesIO
from typing import Any

from PIL import Image, UnidentifiedImageError

from omniroboagent.environments.base import Environment
from omniroboagent.exceptions import EnvironmentError

TASK_ID = "toy_titration_v1"
SKILLS: dict[str, tuple[str, dict[str, Any]]] = {
    "pick naoh_bottle": ("pick", {"object": "naoh_bottle"}),
    "pour 5 ml into beaker": ("pour", {"target": "beaker", "volume_ml": 5}),
    "pour 15 ml into beaker": ("pour", {"target": "beaker", "volume_ml": 15}),
    "pour 30 ml into beaker": ("pour", {"target": "beaker", "volume_ml": 30}),
    "place bottle on table": ("place", {"position": [0.5, -0.2, 0.1]}),
    "observe beaker": ("observe_closely", {}),
    "record finding: beaker is pink": (
        "record_finding",
        {"text": "The beaker is pink."},
    ),
}


class ChemistryBenchEnvironment(Environment):
    """Fixed toy titration; no simulator SDK is imported into the agent process.

    The worker must be exclusively owned by this episode. RPC failures invalidate
    this client: a timed-out command may still execute on the worker's main thread.
    """

    def __init__(
        self,
        address: str = "127.0.0.1:50051",
        timeout_seconds: float = 120,
        load_timeout_seconds: float = 600,
        max_steps: int = 30,
    ) -> None:
        if not address or any(
            not math.isfinite(value) or value <= 0
            for value in (timeout_seconds, load_timeout_seconds)
        ):
            raise ValueError("address and positive finite RPC timeouts are required")
        if (
            isinstance(max_steps, bool)
            or not isinstance(max_steps, int)
            or max_steps < 1
        ):
            raise ValueError("max_steps must be a positive integer")
        self.address = address
        self.timeout_seconds = timeout_seconds
        self.load_timeout_seconds = load_timeout_seconds
        self.max_steps = max_steps
        self._channel: Any = None
        self._stub: Any = None
        self._pb: Any = None
        self._closed = False
        self._ready = False
        self._steps = 0

    def _connect(self) -> None:
        if self._closed:
            raise EnvironmentError(
                "Chemistry Bench client is closed; create a new instance"
            )
        if self._channel is not None:
            return
        try:
            grpc = importlib.import_module("grpc")
            self._pb = importlib.import_module("chemistry_bench_proto.embodiment_pb2")
            services = importlib.import_module(
                "chemistry_bench_proto.embodiment_pb2_grpc"
            )
        except (ImportError, RuntimeError) as error:
            raise EnvironmentError(
                "Install Chemistry Bench protobuf bindings; see docs/chemistry_bench.md"
            ) from error
        # No transparent action replay, including after a deadline expires.
        self._channel = grpc.insecure_channel(
            self.address,
            # Worker addresses are direct trusted-network connections. Inherited
            # HTTP proxies must not intercept local simulator traffic.
            options=(("grpc.enable_retries", 0), ("grpc.enable_http_proxy", 0)),
        )
        self._stub = services.SimBackendStub(self._channel)

    def _rpc(self, method: str, request: Any, timeout: float) -> Any:
        try:
            return getattr(self._stub, method)(request, timeout=timeout)
        except Exception:
            self.close()
            # Do not include remote payloads or privileged details in trace errors.
            raise EnvironmentError(
                f"Chemistry Bench {method} RPC failed; worker state may be uncertain. "
                "No automatic replay; reconcile/restart the dedicated worker."
            ) from None

    def reset(self, task: Any) -> dict[str, Any]:
        task_id = task.get("task_id") if isinstance(task, dict) else task
        if task_id != TASK_ID:
            raise EnvironmentError(f"Chemistry Bench supports only {TASK_ID}")
        self._ready = False
        self._connect()
        health = self._rpc("Health", self._pb.Empty(), self.timeout_seconds)
        if not health.ok:
            raise EnvironmentError("Chemistry Bench worker is not healthy")
        resources = files(__package__)
        request = self._pb.LoadSceneRequest(
            scene_yaml=resources.joinpath("scene.yaml").read_text(encoding="utf-8"),
            embodiment_spec_yaml=resources.joinpath("embodiment.yaml").read_text(
                encoding="utf-8"
            ),
            enable_webrtc=False,
        )
        # The upstream empty Reset request does not restore chemistry state.
        ack = self._rpc("LoadScene", request, self.load_timeout_seconds)
        if not ack.ok:
            raise EnvironmentError(
                "Chemistry Bench scene load rejected; restart worker"
            )
        observation, _ = self._observe()
        self._steps = 0
        self._ready = True
        return observation

    def _observe(self) -> tuple[dict[str, Any], bool]:
        message = self._rpc("Observe", self._pb.Empty(), self.timeout_seconds)
        try:
            truth = json.loads(message.privileged_json)
            beaker = truth["vessels"]["beaker"]
            findings = truth["findings"]
            if not isinstance(beaker["color"], str) or not isinstance(findings, list):
                raise ValueError("Invalid task truth")
            if not all(isinstance(finding, str) for finding in findings):
                raise ValueError("Invalid findings")
            success = beaker["color"] == "pink" and len(findings) > 0
            cameras = [cam for cam in message.cameras if cam.name == "main"]
            if len(cameras) != 1:
                raise ValueError("Expected one main camera")
            camera = cameras[0]
            with Image.open(BytesIO(camera.png)) as image:
                if image.format != "PNG" or image.size != (camera.width, camera.height):
                    raise ValueError("Invalid camera image")
                image.verify()
            if not math.isfinite(message.timestamp):
                raise ValueError("Invalid simulator timestamp")
        except (
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
            OSError,
            UnidentifiedImageError,
        ):
            self.close()
            raise EnvironmentError(
                "Invalid Chemistry Bench observation or task truth"
            ) from None
        # Bytes are encoded by the LLM backend and summarized by the trace serializer.
        # Never forward privileged_json, raw ActionResult details, volumes or pH.
        return {
            "head_rgb": bytes(camera.png),
            "available_skills": list(SKILLS),
            "timestamp": message.timestamp,
        }, success

    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        if not self._ready or self._closed:
            raise EnvironmentError("Reset Chemistry Bench before executing an action")
        if execute_steps is not None:
            raise EnvironmentError(
                "Chemistry Bench primitives require full execution mode"
            )
        valid = isinstance(action, str) and action in SKILLS
        ok = False
        if valid:
            primitive, params = SKILLS[action]
            result = self._rpc(
                "Act",
                self._pb.ActionCommandMsg(
                    kind="primitive",
                    primitive=primitive,
                    params_json=json.dumps(params),
                    timeout_s=self.timeout_seconds,
                ),
                self.timeout_seconds,
            )
            ok = bool(result.ok)
        observation, success = self._observe()
        self._steps += 1
        done = success or self._steps >= self.max_steps
        self._ready = not done
        return {
            "observation": observation,
            "task_success": success,
            "task_progress": float(success),
            "last_action_success": ok,
            "done": done,
            "env_feedback": (
                "Primitive completed."
                if ok
                else "Primitive rejected or failed."
                if valid
                else "Unavailable skill."
            ),
        }

    def close(self) -> None:
        self._ready = False
        self._closed = True
        if self._channel is not None:
            self._channel.close()
            self._channel = None
