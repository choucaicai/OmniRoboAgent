from collections.abc import Callable, Mapping
from typing import Any

from omniroboagent.backends.skills.base import SkillBackend
from omniroboagent.exceptions import BackendError, ConfigError

_ENTRYPOINTS = {"predict", "infer", "get_action", "callable"}


class LocalPolicyBackend(SkillBackend):
    """Adapt an already-instantiated in-process policy to SkillBackend."""

    def __init__(
        self,
        policy: Any,
        entrypoint: str = "predict",
        action_key: str | None = None,
    ) -> None:
        if entrypoint not in _ENTRYPOINTS:
            supported = ", ".join(sorted(_ENTRYPOINTS))
            raise ConfigError(
                f"Unsupported local policy entrypoint {entrypoint!r}; expected one of: "
                f"{supported}"
            )
        if action_key is not None and (
            not isinstance(action_key, str) or not action_key
        ):
            raise ConfigError("Local policy action_key must be a non-empty string")

        policy_call: Any = (
            policy if entrypoint == "callable" else getattr(policy, entrypoint, None)
        )
        if not callable(policy_call):
            raise ConfigError(
                f"Local policy does not provide callable entrypoint {entrypoint!r}"
            )

        self.policy = policy
        self.entrypoint = entrypoint
        self.action_key = action_key
        self._policy_call: Callable[[dict[str, Any]], Any] = policy_call

    def predict(self, inputs: dict[str, Any]) -> Any:
        try:
            result = self._policy_call(inputs)
        except Exception as error:
            raise BackendError(
                f"Local policy entrypoint {self.entrypoint!r} failed: {error}"
            ) from error

        if self.action_key is None:
            return result
        if not isinstance(result, Mapping) or self.action_key not in result:
            raise BackendError(
                f"Local policy output is missing action key {self.action_key!r}"
            )
        return result[self.action_key]

    def healthcheck(self) -> dict[str, Any]:
        healthcheck = getattr(self.policy, "healthcheck", None)
        if callable(healthcheck):
            try:
                result = healthcheck()
            except Exception as error:
                return {"healthy": False, "error": str(error)}
            if not isinstance(result, Mapping):
                return {
                    "healthy": False,
                    "error": "Local policy healthcheck must return a mapping",
                }
            return dict(result)
        return {"healthy": True, "entrypoint": self.entrypoint}

    def close(self) -> None:
        close = getattr(self.policy, "close", None)
        if callable(close):
            close()
