import importlib
from typing import Any

from omniroboagent.backends.skills.base import SkillBackend
from omniroboagent.exceptions import ConfigError

BackendTarget = type[SkillBackend] | str


def _validate_name(name: object) -> str:
    if not isinstance(name, str) or not name:
        raise ConfigError("Skill backend name must be a non-empty string")
    if name != name.strip():
        raise ConfigError("Skill backend name must not contain surrounding whitespace")
    return name


class SkillBackendRegistry:
    """Map stable config names to SkillBackend implementations."""

    def __init__(self, backends: dict[str, BackendTarget] | None = None) -> None:
        self._backends: dict[str, BackendTarget] = {}
        for name, target in (backends or {}).items():
            self.register(name, target)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._backends))

    def register(self, name: str, target: BackendTarget) -> None:
        name = _validate_name(name)
        if name in self._backends:
            raise ConfigError(f"Skill backend {name!r} is already registered")
        if isinstance(target, str):
            if "." not in target:
                raise ConfigError(f"Invalid skill backend class path: {target!r}")
        elif not isinstance(target, type) or not issubclass(target, SkillBackend):
            raise ConfigError(
                "Registered skill backend must be a SkillBackend class or dotted path"
            )
        self._backends[name] = target

    def create(self, name: str, **init_args: Any) -> SkillBackend:
        name = _validate_name(name)
        if name not in self._backends:
            available = ", ".join(self.names) or "(none)"
            raise ConfigError(
                f"Unknown skill backend {name!r}. Available backends: {available}"
            )

        target = self._backends[name]
        if isinstance(target, str):
            module_name, class_name = target.rsplit(".", 1)
            try:
                target = getattr(importlib.import_module(module_name), class_name)
            except (ImportError, AttributeError) as error:
                raise ConfigError(
                    f"Failed to load skill backend {name!r} from "
                    f"{self._backends[name]}: "
                    f"{error}"
                ) from error
            if not isinstance(target, type) or not issubclass(target, SkillBackend):
                raise ConfigError(
                    f"Registered target for skill backend {name!r} does not implement "
                    "SkillBackend"
                )

        try:
            backend = target(**init_args)
        except TypeError as error:
            raise ConfigError(
                f"Failed to instantiate skill backend {name!r}: {error}"
            ) from error
        if not isinstance(backend, SkillBackend):
            raise ConfigError(
                f"Registered target for skill backend {name!r} does not implement "
                "SkillBackend"
            )
        return backend


skill_backend_registry = SkillBackendRegistry(
    {
        "groot_remote": (
            "omniroboagent.backends.skills.groot.GR00TRemotePolicyBackend"
        ),
        "local": "omniroboagent.backends.skills.local.LocalPolicyBackend",
        "openpi_remote": (
            "omniroboagent.backends.skills.openpi.OpenPIRoboCasaPolicyBackend"
        ),
    }
)


def register_skill_backend(name: str, target: BackendTarget) -> None:
    skill_backend_registry.register(name, target)


def create_skill_backend(name: str, **init_args: Any) -> SkillBackend:
    return skill_backend_registry.create(name, **init_args)
