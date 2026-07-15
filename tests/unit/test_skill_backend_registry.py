from typing import Any

import pytest

from omniroboagent.agent_core import DefaultAgent
from omniroboagent.backends.skills import (
    LocalPolicyBackend,
    SkillBackend,
    SkillBackendRegistry,
    register_skill_backend,
    skill_backend_registry,
)
from omniroboagent.config import build_agent
from omniroboagent.exceptions import BackendError, ConfigError


class FakeBackend(SkillBackend):
    def __init__(self, value: str = "action") -> None:
        self.value = value

    def predict(self, inputs: dict[str, Any]) -> Any:
        return self.value


def test_registry_has_stable_builtin_names() -> None:
    assert set(skill_backend_registry.names) >= {
        "groot_remote",
        "local",
        "openpi_remote",
    }


def test_registry_registers_and_creates_backend() -> None:
    registry = SkillBackendRegistry()
    registry.register("fake", FakeBackend)

    backend = registry.create("fake", value="registered")

    assert backend.predict({}) == "registered"


def test_registry_loads_lazy_dotted_path() -> None:
    registry = SkillBackendRegistry(
        {"language": ("omniroboagent.backends.skills.language.LanguageSkillBackend")}
    )

    assert isinstance(registry.create("language"), SkillBackend)


@pytest.mark.parametrize("name", ["", " local ", None, []])
def test_registry_rejects_invalid_names(name: Any) -> None:
    registry = SkillBackendRegistry({"fake": FakeBackend})

    with pytest.raises(ConfigError, match="Skill backend name"):
        registry.create(name)


def test_registry_rejects_unknown_name() -> None:
    registry = SkillBackendRegistry({"fake": FakeBackend})

    with pytest.raises(
        ConfigError, match="Unknown skill backend 'missing'.*Available backends: fake"
    ):
        registry.create("missing")


def test_registry_rejects_duplicate_name() -> None:
    registry = SkillBackendRegistry({"fake": FakeBackend})

    with pytest.raises(ConfigError, match="already registered"):
        registry.register("fake", FakeBackend)


def test_build_agent_supports_registered_skill_backend() -> None:
    register_skill_backend("test_config_backend", FakeBackend)

    agent = build_agent(
        {
            "agent": {"class_path": "omniroboagent.agent_core.DefaultAgent"},
            "planner": {
                "class_path": "omniroboagent.agent_core.LanguageSkillPlanner",
                "init_args": {
                    "backend": {
                        "class_path": (
                            "omniroboagent.backends.llm.OpenAICompatibleLLMBackend"
                        ),
                        "init_args": {
                            "base_url": "http://localhost:8000",
                            "model": "test-model",
                        },
                    }
                },
            },
            "verifier": {"class_path": "omniroboagent.agent_core.EnvironmentVerifier"},
            "memory": {"class_path": "omniroboagent.agent_core.InMemoryMemory"},
            "skill_backend": {
                "name": "test_config_backend",
                "init_args": {"value": "configured"},
            },
        }
    )

    assert isinstance(agent, DefaultAgent)
    assert agent.predict_action({}) == "configured"
    agent.close()


@pytest.mark.parametrize("entrypoint", ["predict", "infer", "get_action"])
def test_local_backend_uses_explicit_method(entrypoint: str) -> None:
    class Policy:
        def predict(self, inputs: dict[str, Any]) -> Any:
            return {"entrypoint": "predict", "inputs": inputs}

        def infer(self, inputs: dict[str, Any]) -> Any:
            return {"entrypoint": "infer", "inputs": inputs}

        def get_action(self, inputs: dict[str, Any]) -> Any:
            return {"entrypoint": "get_action", "inputs": inputs}

    inputs = {"observation": {"state": [0.0]}}

    result = LocalPolicyBackend(Policy(), entrypoint=entrypoint).predict(inputs)

    assert result == {"entrypoint": entrypoint, "inputs": inputs}


def test_local_backend_supports_callable_and_action_key() -> None:
    def policy(inputs: dict[str, Any]) -> dict[str, Any]:
        return {"actions": [inputs["observation"]]}

    backend = LocalPolicyBackend(policy, entrypoint="callable", action_key="actions")

    assert backend.predict({"observation": "frame"}) == ["frame"]


def test_local_backend_rejects_missing_entrypoint() -> None:
    with pytest.raises(ConfigError, match="does not provide callable entrypoint"):
        LocalPolicyBackend(object(), entrypoint="infer")


def test_local_backend_rejects_missing_action_key() -> None:
    backend = LocalPolicyBackend(
        lambda inputs: {"other": inputs},
        entrypoint="callable",
        action_key="actions",
    )

    with pytest.raises(BackendError, match="missing action key 'actions'"):
        backend.predict({})


def test_local_backend_wraps_policy_error() -> None:
    def failing_policy(inputs: dict[str, Any]) -> Any:
        raise RuntimeError(f"failed for {inputs}")

    backend = LocalPolicyBackend(failing_policy, entrypoint="callable")

    with pytest.raises(BackendError, match="entrypoint 'callable' failed"):
        backend.predict({"observation": "frame"})


def test_local_backend_healthcheck_and_close() -> None:
    class Policy:
        def __init__(self) -> None:
            self.closed = False

        def predict(self, inputs: dict[str, Any]) -> Any:
            return inputs

        def close(self) -> None:
            self.closed = True

    policy = Policy()
    backend = LocalPolicyBackend(policy)

    assert backend.healthcheck() == {"healthy": True, "entrypoint": "predict"}
    backend.close()

    assert policy.closed is True


def test_local_backend_delegates_policy_healthcheck() -> None:
    class Policy:
        def predict(self, inputs: dict[str, Any]) -> Any:
            return inputs

        def healthcheck(self) -> dict[str, Any]:
            return {"healthy": False, "reason": "checkpoint missing"}

    assert LocalPolicyBackend(Policy()).healthcheck() == {
        "healthy": False,
        "reason": "checkpoint missing",
    }
