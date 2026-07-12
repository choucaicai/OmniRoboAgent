from typing import Any

from omniroboagent.contracts import SkillBackend


class LanguageSkillBackend(SkillBackend):
    """Pass a planner-selected language skill to the environment unchanged."""

    def predict(self, inputs: dict[str, Any]) -> Any:
        if "skill" not in inputs:
            raise KeyError("LanguageSkillBackend requires inputs['skill']")
        return inputs["skill"]
