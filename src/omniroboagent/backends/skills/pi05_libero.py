from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from omniroboagent.backends.skills.base import SkillBackend
from omniroboagent.exceptions import BackendError


class LiberoPi05PolicyBackend(SkillBackend):
    """Run the existing ClawVLA/LeRobot LIBERO pi0.5 adapter in process."""

    def __init__(
        self,
        config_path: str | Path,
        pretrained_path: str | Path | None = None,
        device: str | None = None,
        horizon: int = 50,
        tokenizer_name: str | Path | None = None,
        backend_factory: Callable[[dict[str, Any]], Any] | None = None,
    ) -> None:
        if horizon <= 0:
            raise ValueError("LIBERO pi0.5 horizon must be positive")
        self.config_path = Path(config_path).expanduser().resolve()
        self.pretrained_path = (
            str(Path(pretrained_path).expanduser().resolve())
            if pretrained_path is not None
            else None
        )
        self.device = device
        self.horizon = horizon
        self.tokenizer_name = (
            str(Path(tokenizer_name).expanduser().resolve())
            if tokenizer_name is not None
            else None
        )
        self.backend_factory = backend_factory
        self.backend: Any = None

    def healthcheck(self) -> dict[str, Any]:
        try:
            backend = self._load_backend()
            diagnosis = backend.diagnose(load_policy=False)
            adapter = diagnosis.get("lerobot_adapter", {})
            healthy = bool(adapter.get("compatible_for_execution", False))
            return {
                "healthy": healthy,
                "checkpoint_format": diagnosis.get("policy_summary", {}).get(
                    "checkpoint_format"
                ),
                "pretrained_path": diagnosis.get("pretrained_path"),
                "adapter": adapter,
            }
        except Exception as error:
            return {
                "healthy": False,
                "error": f"{type(error).__name__}: {error}",
            }

    def predict(self, inputs: dict[str, Any]) -> dict[str, Any]:
        observation = inputs.get("observation")
        if not isinstance(observation, Mapping):
            raise BackendError("LIBERO pi0.5 requires an observation dictionary")
        prompt = inputs.get("subtask")
        if not isinstance(prompt, str) or not prompt.strip():
            prompt = observation.get("annotation.human.task_description")
        if not isinstance(prompt, str) or not prompt.strip():
            raise BackendError("LIBERO pi0.5 requires a non-empty subtask prompt")
        observation_id = observation.get("observation_id")
        if not isinstance(observation_id, str) or not observation_id:
            raise BackendError("LIBERO pi0.5 requires an observation_id")
        agentview = observation.get("agentview_rgb")
        wrist = observation.get("wrist_rgb")
        state = observation.get("libero_state8")
        if not isinstance(agentview, str) or not isinstance(wrist, str):
            raise BackendError("LIBERO pi0.5 requires agentview and wrist RGB paths")
        if not isinstance(state, list) or len(state) != 8:
            raise BackendError("LIBERO pi0.5 requires an 8D robot state")

        try:
            from clawvla.schema import (  # type: ignore[import-not-found]
                CameraView,
                ObservationBundle,
            )

            bundle = ObservationBundle(
                observation_id=observation_id,
                task_instruction=prompt,
                camera_views={
                    "agentview": CameraView(name="agentview", rgb_path=agentview),
                    "wrist": CameraView(name="wrist", rgb_path=wrist),
                },
                raw={"libero_state8": [float(value) for value in state]},
                metadata={
                    "suite": observation.get("suite"),
                    "task_id": observation.get("task_id"),
                    "task_name": observation.get("task_name"),
                },
            )
            result = self._load_backend().build_action_chunk(
                motion_goal=None,
                world_state=None,
                observation=bundle,
                request={
                    "motion_plan": {"vla_prompt": prompt},
                    "horizon": self.horizon,
                },
            )
        except BackendError:
            raise
        except Exception as error:
            raise BackendError(
                f"LIBERO pi0.5 inference failed: {type(error).__name__}: {error}"
            ) from error

        if not bool(getattr(result, "success", False)):
            errors = getattr(result, "errors", [])
            raise BackendError(f"LIBERO pi0.5 inference failed: {errors}")
        chunk = getattr(result, "action_chunk", None)
        if chunk is None or not hasattr(chunk, "to_dict"):
            raise BackendError("LIBERO pi0.5 returned no action chunk")
        payload = chunk.to_dict()
        if not isinstance(payload, dict):
            raise BackendError("LIBERO pi0.5 action chunk must serialize to a dict")
        return {
            **payload,
            "source_observation_id": observation_id,
            "vla_prompt": prompt,
            "skill": inputs.get("skill"),
        }

    def close(self) -> None:
        self.backend = None

    def _load_backend(self) -> Any:
        if self.backend is not None:
            return self.backend
        if not self.config_path.is_file():
            raise BackendError(f"Missing ClawVLA config: {self.config_path}")
        try:
            from clawvla.action_backends.pi05 import (  # type: ignore[import-not-found]
                Pi05ActionBackend,
            )
            from clawvla.config import load_config  # type: ignore[import-not-found]

            config = load_config(self.config_path)
            backend_config = dict(config.metadata.get("action_backend", {}))
            if self.pretrained_path is not None:
                backend_config["pretrained_path"] = self.pretrained_path
            if self.device is not None:
                backend_config["device"] = self.device
            if self.tokenizer_name is not None:
                backend_config["tokenizer_name"] = self.tokenizer_name
            policy_kwargs = dict(backend_config.get("policy_kwargs", {}))
            policy_kwargs["n_action_steps"] = self.horizon
            backend_config["policy_kwargs"] = policy_kwargs
            factory = self.backend_factory or Pi05ActionBackend
            self.backend = factory(backend_config)
            return self.backend
        except BackendError:
            raise
        except Exception as error:
            raise BackendError(
                f"Failed to initialize LIBERO pi0.5 backend: "
                f"{type(error).__name__}: {error}"
            ) from error
