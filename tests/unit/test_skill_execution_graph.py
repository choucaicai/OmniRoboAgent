from typing import Any

from omniroboagent.agent_core import BaseAgent
from omniroboagent.environments import Environment
from omniroboagent.pipelines import SkillExecutionPipeline


class ScriptedAgent(BaseAgent):
    def __init__(
        self,
        proposals: list[dict[str, Any]],
        verifications: list[dict[str, Any]],
    ) -> None:
        self.proposals = proposals
        self.verifications = verifications
        self.plan_calls = 0
        self.action_calls = 0
        self.verify_calls = 0
        self.events: list[dict[str, Any]] = []
        self.recall_phases: list[str] = []
        self.verify_inputs: list[dict[str, Any]] = []

    def plan(self, inputs: dict[str, Any]) -> dict[str, Any]:
        proposal = self.proposals[min(self.plan_calls, len(self.proposals) - 1)]
        self.plan_calls += 1
        return proposal

    def predict_action(self, inputs: dict[str, Any]) -> dict[str, Any]:
        self.action_calls += 1
        return {"execution_id": inputs["execution_id"], "skill": inputs["skill"]}

    def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
        self.verify_inputs.append(inputs)
        result = self.verifications[
            min(self.verify_calls, len(self.verifications) - 1)
        ]
        self.verify_calls += 1
        environment_result = inputs["environment_result"]
        return {
            "task_success": environment_result.get("task_success", False),
            "task_progress": environment_result.get("task_progress", 0.0),
            "last_action_success": environment_result.get(
                "last_action_success", True
            ),
            "environment_done": environment_result.get("done", False),
            "env_feedback": environment_result.get("env_feedback", ""),
            **result,
        }

    def update(self, state: dict[str, Any], event: dict[str, Any]) -> None:
        self.events.append(event)

    def recall(self, query: dict[str, Any]) -> dict[str, Any]:
        self.recall_phases.append(str(query["phase"]))
        return {
            "working_frames": [],
            "recent_events": [],
            "summary": f"memory for {query['phase']}",
        }


class CountingEnvironment(Environment):
    def __init__(self, task_success: bool = False) -> None:
        self.task_success = task_success
        self.calls = 0

    def reset(self, task: Any) -> dict[str, Any]:
        return {"frame": 0, "available_skills": ["PickPlace"]}

    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        self.calls += 1
        return {
            "observation": {
                "frame": self.calls,
                "available_skills": ["PickPlace"],
            },
            "task_success": self.task_success,
            "task_progress": float(self.task_success),
            "last_action_success": True,
            "done": self.task_success,
            "executed_steps": 1,
        }

    def close(self) -> None:
        return None


def proposal(
    subtask: str = "place mug on tray",
    *,
    object_name: str = "mug",
    target: str = "tray",
) -> dict[str, Any]:
    return {
        "skill": "PickPlace",
        "skill_id": 7,
        "subtask": subtask,
        "grounded_arguments": {"object": object_name, "target": target},
        "expected_outcome": f"the {object_name} is on the {target}",
    }


def verification(status: str, **extra: Any) -> dict[str, Any]:
    return {
        "execution_status": status,
        "reason": f"status is {status}",
        "confidence": 0.9,
        "evidence": [status],
        **extra,
    }


def initial_state() -> dict[str, Any]:
    return {
        "task": "set the table",
        "observation": {"frame": 0, "available_skills": ["PickPlace"]},
        "step": 0,
        "session_id": "session",
        "history": [],
    }


def test_first_plan_creates_explicit_active_execution() -> None:
    agent = ScriptedAgent([proposal()], [verification("in_progress")])
    environment = CountingEnvironment()
    state = initial_state()

    output = SkillExecutionPipeline().step(agent, environment, state)

    active = state["active_execution"]
    assert active["execution_id"] == "session:1"
    assert active["attempt_id"] == "session:1:attempt:1"
    assert active["skill_id"] == 7
    assert active["chunk_count"] == 1
    assert output["previous_status"] == "idle"
    assert output["next_status"] == "in_progress"
    assert agent.plan_calls == 1
    assert environment.calls == 1
    assert agent.recall_phases == ["plan", "verify"]
    assert agent.verify_inputs[0]["memory_context"]["summary"] == "memory for verify"


def test_in_progress_continues_same_execution_without_planner() -> None:
    agent = ScriptedAgent(
        [proposal()],
        [verification("in_progress"), verification("in_progress")],
    )
    environment = CountingEnvironment()
    state = initial_state()
    pipeline = SkillExecutionPipeline(planner_check_interval_chunks=1)

    pipeline.step(agent, environment, state)
    execution_id = state["active_execution"]["execution_id"]
    state["step"] += 1
    pipeline.step(agent, environment, state)

    assert state["active_execution"]["execution_id"] == execution_id
    assert state["active_execution"]["chunk_count"] == 2
    assert agent.plan_calls == 1
    assert agent.action_calls == 2
    assert environment.calls == 2


def test_completed_execution_is_recorded_and_next_step_plans() -> None:
    agent = ScriptedAgent(
        [proposal(), proposal("place plate on table")],
        [verification("completed"), verification("in_progress")],
    )
    environment = CountingEnvironment()
    state = initial_state()
    pipeline = SkillExecutionPipeline()

    first = pipeline.step(agent, environment, state)

    assert first["next_status"] == "plan"
    assert first["event_type"] == "subtask_completed"
    assert state["active_execution"] is None
    assert state["completed_executions"][0]["execution_id"] == "session:1"

    state["step"] += 1
    pipeline.step(agent, environment, state)

    assert state["active_execution"]["execution_id"] == "session:2"
    assert agent.plan_calls == 2


def test_failed_execution_retries_current_attempt_then_replans() -> None:
    agent = ScriptedAgent(
        [proposal(), proposal("recover mug")],
        [
            verification("failed"),
            verification("failed"),
            verification("in_progress"),
        ],
    )
    environment = CountingEnvironment()
    state = initial_state()
    pipeline = SkillExecutionPipeline()

    first = pipeline.step(agent, environment, state)

    assert first["recovery_action"] == "retry_current"
    assert first["event_type"] == "recovery_started"
    assert state["active_execution"]["execution_id"] == "session:1"
    assert state["active_execution"]["attempt_id"] == "session:1:attempt:2"
    assert state["failed_executions"] == []

    state["step"] += 1
    second = pipeline.step(agent, environment, state)

    assert second["recovery_action"] == "replan"
    assert second["event_type"] == "subtask_failed"
    assert state["active_execution"] is None
    assert state["failed_executions"][0]["attempt_count"] == 2

    state["step"] += 1
    pipeline.step(agent, environment, state)
    assert agent.plan_calls == 2
    assert state["active_execution"]["execution_id"] == "session:2"


def test_uncertain_reverifies_without_environment_action() -> None:
    agent = ScriptedAgent(
        [proposal()],
        [verification("uncertain"), verification("in_progress")],
    )
    environment = CountingEnvironment()
    state = initial_state()
    pipeline = SkillExecutionPipeline()

    pipeline.step(agent, environment, state)
    state["step"] += 1
    output = pipeline.step(agent, environment, state)

    assert output["previous_status"] == "uncertain"
    assert output["next_status"] == "in_progress"
    assert output["action"] is None
    assert environment.calls == 1
    assert agent.action_calls == 1
    assert agent.verify_calls == 2


def test_task_success_terminates_and_cleans_active_execution() -> None:
    agent = ScriptedAgent([proposal()], [verification("completed")])
    environment = CountingEnvironment(task_success=True)
    state = initial_state()

    output = SkillExecutionPipeline().step(agent, environment, state)

    assert output["success"] is True
    assert output["event_type"] == "task_success"
    assert output["termination_reason"] == "task_success"
    assert state["active_execution"] is None
    assert len(state["completed_executions"]) == 1
    assert environment.calls == 1


def test_chunk_budget_closes_execution_after_one_action_per_step() -> None:
    agent = ScriptedAgent(
        [proposal()],
        [verification("in_progress"), verification("in_progress")],
    )
    environment = CountingEnvironment()
    state = initial_state()
    pipeline = SkillExecutionPipeline(max_chunks_per_skill=2)

    pipeline.step(agent, environment, state)
    state["step"] += 1
    output = pipeline.step(agent, environment, state)

    assert output["transition_reason"] == "chunk budget exhausted"
    assert output["recovery_action"] == "replan"
    assert output["event_type"] == "subtask_failed"
    assert state["active_execution"] is None
    assert state["failed_executions"][0]["chunk_count"] == 2
    assert environment.calls == 2


def test_uncertain_budget_exhaustion_replans_without_second_action() -> None:
    agent = ScriptedAgent(
        [proposal()],
        [verification("uncertain"), verification("uncertain")],
    )
    environment = CountingEnvironment()
    state = initial_state()
    pipeline = SkillExecutionPipeline(max_uncertain_verifications=2)

    pipeline.step(agent, environment, state)
    state["step"] += 1
    output = pipeline.step(agent, environment, state)

    assert output["transition_reason"] == "uncertain verification budget exhausted"
    assert output["recovery_action"] == "replan"
    assert state["active_execution"] is None
    assert len(state["failed_executions"]) == 1
    assert environment.calls == 1


def test_no_progress_detection_replans_current_execution() -> None:
    agent = ScriptedAgent(
        [proposal()],
        [
            verification("in_progress", progress_marker="unchanged"),
            verification("in_progress", progress_marker="unchanged"),
        ],
    )
    environment = CountingEnvironment()
    state = initial_state()
    pipeline = SkillExecutionPipeline(max_no_progress_steps=1)

    pipeline.step(agent, environment, state)
    state["step"] += 1
    output = pipeline.step(agent, environment, state)

    assert output["transition_reason"] == "no progress detected"
    assert output["recovery_action"] == "replan"
    assert state["failed_executions"][0]["chunk_count"] == 2
    assert environment.calls == 2


def test_recovery_uses_configured_fallback_after_replan_budget() -> None:
    fallback = proposal(
        "place plate on table", object_name="plate", target="table"
    )
    agent = ScriptedAgent(
        [proposal()],
        [verification("failed"), verification("in_progress")],
    )
    environment = CountingEnvironment()
    state = initial_state()
    pipeline = SkillExecutionPipeline(
        max_attempts_per_execution=1,
        max_replans=0,
        fallback_proposal=fallback,
    )

    first = pipeline.step(agent, environment, state)

    assert first["recovery_action"] == "fallback"
    assert first["transition"]["next_execution_id"] == "session:2"
    assert state["active_execution"]["grounded_arguments"]["object"] == "plate"

    state["step"] += 1
    pipeline.step(agent, environment, state)

    assert agent.plan_calls == 1
    assert environment.calls == 2


def test_recovery_aborts_when_all_budgets_are_exhausted() -> None:
    agent = ScriptedAgent([proposal()], [verification("failed")])
    environment = CountingEnvironment()
    state = initial_state()
    pipeline = SkillExecutionPipeline(
        max_attempts_per_execution=1,
        max_replans=0,
    )

    output = pipeline.step(agent, environment, state)

    assert output["recovery_action"] == "abort"
    assert output["termination_reason"] == "execution_aborted"
    assert output["decision"] == "failure"
    assert state["active_execution"] is None


def test_repeated_execution_loop_ignores_subtask_wording() -> None:
    agent = ScriptedAgent(
        [
            proposal("place the mug on the tray"),
            proposal("put mug onto tray"),
            proposal("move the mug to the tray"),
        ],
        [
            verification("completed"),
            verification("completed"),
            verification("in_progress"),
        ],
    )
    environment = CountingEnvironment()
    state = initial_state()
    pipeline = SkillExecutionPipeline()

    pipeline.step(agent, environment, state)
    state["step"] += 1
    pipeline.step(agent, environment, state)
    state["step"] += 1
    output = pipeline.step(agent, environment, state)

    assert output["transition_reason"] == "repeated execution loop detected"
    assert output["recovery_action"] == "abort"
    assert output["event_type"] == "execution_aborted"
    assert environment.calls == 2


def test_a_b_a_execution_loop_is_detected() -> None:
    agent = ScriptedAgent(
        [
            proposal(),
            proposal("place plate on table", object_name="plate", target="table"),
            proposal("put mug onto tray"),
        ],
        [
            verification("completed"),
            verification("completed"),
            verification("in_progress"),
        ],
    )
    environment = CountingEnvironment()
    state = initial_state()
    pipeline = SkillExecutionPipeline()

    pipeline.step(agent, environment, state)
    state["step"] += 1
    pipeline.step(agent, environment, state)
    state["step"] += 1
    output = pipeline.step(agent, environment, state)

    assert output["transition_reason"] == "A-B-A execution loop detected"
    assert output["recovery_action"] == "abort"
    assert environment.calls == 2
