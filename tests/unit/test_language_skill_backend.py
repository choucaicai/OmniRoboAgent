import pytest

from omniroboagent.backends.skills import LanguageSkillBackend
from omniroboagent.contracts import SkillBackend


def test_language_skill_backend_implements_contract() -> None:
    assert isinstance(LanguageSkillBackend(), SkillBackend)


def test_language_skill_backend_returns_language_skill_unchanged() -> None:
    skill = "PickUp(mug)"

    assert LanguageSkillBackend().predict({"skill": skill}) == skill


def test_language_skill_backend_returns_same_skill_object() -> None:
    skill = {"name": "PickUp", "target": "mug"}

    result = LanguageSkillBackend().predict({"skill": skill, "observation": "ignored"})

    assert result is skill


def test_language_skill_backend_requires_skill() -> None:
    with pytest.raises(
        KeyError, match=r"LanguageSkillBackend requires inputs\['skill'\]"
    ):
        LanguageSkillBackend().predict({})
