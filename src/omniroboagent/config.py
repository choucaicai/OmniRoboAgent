import importlib
from pathlib import Path
from typing import Any

import yaml

from omniroboagent.agent_core.agents.base import BaseAgent
from omniroboagent.backends.skills.base import SkillBackend
from omniroboagent.backends.skills.registry import create_skill_backend
from omniroboagent.environments.base import Environment
from omniroboagent.exceptions import ConfigError
from omniroboagent.pipelines.base import Pipeline
from omniroboagent.runtimes.base import Runtime


def load_yaml(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as error:
        raise ConfigError(f"Failed to load config {config_path}: {error}") from error
    if not isinstance(data, dict):
        raise ConfigError(f"Config root must be a mapping: {config_path}")
    return data


def instantiate(spec: Any, **extra_init_args: Any) -> Any:
    if isinstance(spec, list):
        return [instantiate(item) for item in spec]
    if not isinstance(spec, dict):
        return spec
    if "class_path" not in spec:
        return {key: instantiate(value) for key, value in spec.items()}

    class_path = spec["class_path"]
    if not isinstance(class_path, str) or "." not in class_path:
        raise ConfigError(f"Invalid class_path: {class_path!r}")
    init_args = spec.get("init_args", {})
    if not isinstance(init_args, dict):
        raise ConfigError(f"init_args for {class_path} must be a mapping")
    kwargs = {key: instantiate(value) for key, value in init_args.items()}
    kwargs.update(extra_init_args)
    module_name, class_name = class_path.rsplit(".", 1)
    try:
        cls = getattr(importlib.import_module(module_name), class_name)
        return cls(**kwargs)
    except (ImportError, AttributeError, TypeError) as error:
        raise ConfigError(f"Failed to instantiate {class_path}: {error}") from error


def build_agent(config: dict[str, Any]) -> BaseAgent:
    required = {"agent", "planner", "verifier", "memory", "skill_backend"}
    missing = sorted(required - config.keys())
    if missing:
        raise ConfigError(f"Agent config is missing: {', '.join(missing)}")
    skill_backend_spec = config["skill_backend"]
    if isinstance(skill_backend_spec, dict) and "name" in skill_backend_spec:
        if "class_path" in skill_backend_spec:
            raise ConfigError(
                "skill_backend must define either name or class_path, not both"
            )
        init_args = skill_backend_spec.get("init_args", {})
        if not isinstance(init_args, dict):
            raise ConfigError("init_args for skill_backend name must be a mapping")
        skill_backend = create_skill_backend(
            skill_backend_spec["name"],
            **{key: instantiate(value) for key, value in init_args.items()},
        )
    else:
        skill_backend = instantiate(skill_backend_spec)
    if not isinstance(skill_backend, SkillBackend):
        raise ConfigError("Configured skill_backend does not implement SkillBackend")

    agent = instantiate(
        config["agent"],
        planner=instantiate(config["planner"]),
        verifier=instantiate(config["verifier"]),
        memory=instantiate(config["memory"]),
        skill_backend=skill_backend,
    )
    if not isinstance(agent, BaseAgent):
        raise ConfigError("Configured agent does not implement BaseAgent")
    return agent


def build_run_components(
    config: dict[str, Any],
) -> tuple[Pipeline, Runtime, Environment | None]:
    pipeline = instantiate(config.get("pipeline"))
    runtime = instantiate(config.get("runtime"))
    environment = (
        instantiate(config["environment"]) if "environment" in config else None
    )
    if not isinstance(pipeline, Pipeline):
        raise ConfigError("Configured pipeline does not implement Pipeline")
    if not isinstance(runtime, Runtime):
        raise ConfigError("Configured runtime does not implement Runtime")
    if environment is not None and not isinstance(environment, Environment):
        raise ConfigError("Configured environment does not implement Environment")
    return pipeline, runtime, environment


def resolve_config_path(value: str | Path, owner_path: str | Path) -> Path:
    candidate = Path(value)
    if candidate.is_absolute() or candidate.exists():
        return candidate
    return Path(owner_path).parent / candidate
