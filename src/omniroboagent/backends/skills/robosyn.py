import importlib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from omniroboagent.backends.skills.base import SkillBackend
from omniroboagent.exceptions import BackendError, ConfigError


class RoboSynPolicyBackend(SkillBackend):
    """Local LeRobot ACT/DP inference with the published RoboSyn observation schema."""

    def __init__(
        self,
        checkpoint_path: str | Path,
        policy_name: str = "act",
        device: str = "cuda",
        state_obs_path: str = "robot/qpos",
        image_key_map: dict[str, str] | None = None,
        dp_num_inference_steps: int = 10,
        policy: Any = None,
    ) -> None:
        if policy_name not in {"act", "dp"}:
            raise ConfigError("RoboSynPolicyBackend policy_name must be 'act' or 'dp'")
        if not str(checkpoint_path) or not state_obs_path:
            raise ConfigError("checkpoint_path and state_obs_path must be non-empty")
        if dp_num_inference_steps <= 0:
            raise ConfigError("dp_num_inference_steps must be positive")
        self.checkpoint_path = str(checkpoint_path)
        self.policy_name = policy_name
        self.device = device
        self.state_obs_path = state_obs_path
        self.image_key_map = image_key_map or {}
        self.dp_num_inference_steps = dp_num_inference_steps
        self.policy = policy
        self._episode_key: Any = object()

    def _load_policy(self) -> None:
        if self.policy is not None:
            return
        module_path, class_name = (
            ("lerobot.policies.act.modeling_act", "ACTPolicy")
            if self.policy_name == "act"
            else ("lerobot.policies.diffusion.modeling_diffusion", "DiffusionPolicy")
        )
        try:
            torch = importlib.import_module("torch")
            requested_device = torch.device(self.device)
            if requested_device.type == "cuda" and requested_device.index is not None:
                torch.cuda.set_device(requested_device)
            cls = getattr(importlib.import_module(module_path), class_name)
            # LeRobot 0.3 accepts a device type, but rejects indexed CUDA strings.
            overrides = [f"--device={requested_device.type}"]
            if self.policy_name == "dp":
                overrides.append(f"--num_inference_steps={self.dp_num_inference_steps}")
            try:
                policy = cls.from_pretrained(
                    self.checkpoint_path, cli_overrides=overrides
                )
            except TypeError as error:
                if "cli_overrides" not in str(error):
                    raise
                config_cls = importlib.import_module(
                    "lerobot.configs.policies"
                ).PreTrainedConfig
                config = config_cls.from_pretrained(
                    self.checkpoint_path, cli_overrides=overrides
                )
                policy = cls.from_pretrained(self.checkpoint_path, config=config)
            policy.to(requested_device)
            policy.eval()
            self.policy = policy
        except Exception as error:
            raise BackendError(
                f"Cannot load RoboSyn {self.policy_name} policy: {error}"
            ) from error

    def predict(self, inputs: dict[str, Any]) -> dict[str, Any]:
        observation = inputs.get("observation")
        if not isinstance(observation, Mapping):
            raise BackendError("RoboSyn policy requires an observation mapping")
        raw = observation.get("policy_observation")
        if not isinstance(raw, Mapping):
            raise BackendError("RoboSyn policy requires policy_observation")
        action_dim = observation.get("action_dim")
        if (
            isinstance(action_dim, bool)
            or not isinstance(action_dim, int)
            or action_dim <= 0
        ):
            raise BackendError("RoboSyn observation requires a positive action_dim")
        task_name = observation.get("task_name")
        if inputs.get("skill") != task_name:
            raise BackendError("RoboSyn policy skill must match the current task")
        self._load_policy()
        torch = importlib.import_module("torch")
        policy_device = next(self.policy.parameters()).device
        episode_key = inputs.get("session_id") or observation.get("episode_id")
        if episode_key is None:
            task = inputs.get("task", {})
            episode_key = (
                (task.get("name"), task.get("seed"), task.get("episode_index"))
                if isinstance(task, Mapping)
                else task
            )

        try:
            if episode_key != self._episode_key:
                self.policy.reset()
                self._episode_key = episode_key
            state = raw
            for key in self.state_obs_path.split("/"):
                if key:
                    state = state[key]
            state_tensor = torch.as_tensor(
                state, dtype=torch.float32, device=policy_device
            ).detach()
            if state_tensor.ndim == 1:
                state_tensor = state_tensor.unsqueeze(0)
            if state_tensor.ndim != 2 or state_tensor.shape[0] != 1:
                raise ValueError("Expected one proprioception observation [1,D]")
            batch = {"observation.state": state_tensor}
            for image_key in self.policy.config.image_features:
                camera_name = self.image_key_map.get(
                    image_key, image_key.removeprefix("observation.images.")
                )
                image = torch.as_tensor(
                    raw["sensor"][camera_name]["color"],
                    dtype=torch.float32,
                    device=policy_device,
                ).detach()
                if image.ndim == 3:
                    image = image.unsqueeze(0)
                if image.ndim != 4 or image.shape[0] != 1 or image.shape[-1] < 3:
                    raise ValueError(f"Expected one HWC image for {camera_name}")
                image = image[..., :3].permute(0, 3, 1, 2).contiguous()
                if float(image.max().item()) > 1.5:
                    image = image / 255.0
                batch[image_key] = image

            with torch.inference_mode():
                action = self.policy.select_action(batch)
            if action.ndim == 1:
                action = action.unsqueeze(0)
            if tuple(action.shape) != (1, action_dim):
                raise ValueError(
                    f"Policy action has shape {tuple(action.shape)}, "
                    f"expected (1, {action_dim})"
                )
            if not bool(torch.isfinite(action).all().item()):
                raise ValueError("Policy action must contain finite values")
            return {"actions": action.detach()}
        except Exception as error:
            raise BackendError(f"RoboSyn policy inference failed: {error}") from error

    def healthcheck(self) -> dict[str, Any]:
        try:
            self._load_policy()
            return {
                "healthy": True,
                "policy": self.policy_name,
                "checkpoint_path": self.checkpoint_path,
                "device": self.device,
                "language_conditioned": False,
            }
        except Exception as error:
            return {"healthy": False, "error": str(error)}

    def close(self) -> None:
        self.policy = None
