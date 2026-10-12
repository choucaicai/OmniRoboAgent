import json
from pathlib import Path
from threading import Barrier, Event, Lock
from typing import Any, cast

import pytest

from omniroboagent.agent_core import (
    DefaultAgent,
    EnvironmentVerifier,
    InMemoryMemory,
    TaskSkillPlanner,
)
from omniroboagent.backends.skills import LanguageSkillBackend
from omniroboagent.environments.base import Environment
from omniroboagent.evals.benchmarks.robosynchallenge.evaluator import (
    RoboSynChallengeEvaluator,
    summarize,
    write_json,
)
from omniroboagent.evals.benchmarks.robosynchallenge.matrix import (
    group_tasks,
    run_matrix,
    summarize_matrix,
    task_command,
)
from omniroboagent.pipelines import DirectPipeline
from omniroboagent.runtimes import SyncRuntime
from omniroboagent.serialization import to_jsonable


class FakeEnvironment(Environment):
    def __init__(self, error_seed: int | None = None) -> None:
        self.error_seed = error_seed
        self.seeds: list[int] = []
        self.seed = -1
        self.steps = 0

    def reset(self, task: Any) -> dict[str, Any]:
        self.seed = task["seed"]
        self.seeds.append(self.seed)
        self.steps = 0
        return {"available_skills": ["click_bell"]}

    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        if self.seed == self.error_seed:
            raise RuntimeError("policy inference failed")
        self.steps += 1
        return {
            "observation": {},
            "task_success": False,
            "done": True,
            "last_action_success": True,
            "executed_steps": 1,
        }

    def metadata(self) -> dict[str, Any]:
        return {"upstream_commit": "fixed"}

    def episode_metadata(self) -> dict[str, Any]:
        return {
            "environment_steps": self.steps,
            "horizon": 1,
            "authoritative_success": False,
        }

    def close(self) -> None:
        pass


def run_evaluation(
    environment: FakeEnvironment,
    output: Path,
    *,
    resume: bool = False,
    seeds: list[int] | None = None,
) -> dict[str, Any]:
    agent = DefaultAgent(
        TaskSkillPlanner(),
        EnvironmentVerifier(),
        InMemoryMemory(),
        LanguageSkillBackend(),
    )
    evaluator = RoboSynChallengeEvaluator(
        cast(Any, environment),
        output,
        "click_bell",
        [0, 1] if seeds is None else seeds,
        resume=resume,
    )
    return evaluator.run(
        agent, DirectPipeline(), SyncRuntime(output_dir=output, max_steps=2)
    )


def test_zero_success_is_complete_and_resume_skips_valid_failures(
    tmp_path: Path,
) -> None:
    environment = FakeEnvironment()
    summary = run_evaluation(environment, tmp_path)
    assert summary["complete"] is True
    assert summary["success_rate"] == 0
    assert summary["evaluated_episodes"] == 2
    assert len(list(tmp_path.glob("robosyn-*/trace.jsonl"))) == 2
    resumed = FakeEnvironment()
    assert run_evaluation(resumed, tmp_path, resume=True)["complete"] is True
    assert resumed.seeds == []


@pytest.mark.parametrize("old_protocol", [None, "warmup_get_obs_v1"])
def test_resume_rejects_old_reset_protocol_without_touching_episodes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old_protocol: str | None
) -> None:
    class UpdatedEnvironment(FakeEnvironment):
        def metadata(self) -> dict[str, Any]:
            return {
                **super().metadata(),
                "reset_state_protocol": "warmup_get_obs_get_info_v2",
            }

    run_evaluation(UpdatedEnvironment(), tmp_path)
    metadata_path = tmp_path / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    if old_protocol is None:
        metadata.pop("reset_state_protocol")
    else:
        metadata["reset_state_protocol"] = old_protocol
    metadata_path.write_text(json.dumps(metadata))
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    monkeypatch.setattr(
        SyncRuntime,
        "run",
        lambda *args, **kwargs: pytest.fail("Resume must not run an episode"),
    )
    resumed = UpdatedEnvironment()
    with pytest.raises(ValueError, match="reset_state_protocol"):
        run_evaluation(resumed, tmp_path, resume=True)
    assert resumed.seeds == []
    assert before == {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }


def test_resume_retries_only_exception_and_preserves_attempts(tmp_path: Path) -> None:
    initial = run_evaluation(FakeEnvironment(error_seed=1), tmp_path)
    assert initial["complete"] is False
    assert initial["execution_errors"] == 1
    resumed = FakeEnvironment()
    result = run_evaluation(resumed, tmp_path, resume=True)
    assert resumed.seeds == [1]
    assert result["complete"] is True
    assert result["execution_errors"] == 0
    assert len(list(tmp_path.glob("robosyn-*/episode.json"))) == 3
    rows = [
        json.loads(line)
        for line in (tmp_path / "episodes.jsonl").read_text().splitlines()
    ]
    assert len(rows) == 2
    assert rows[1]["attempt"] == 2


def test_exception_stops_task_after_persisting_progress(tmp_path: Path) -> None:
    environment = FakeEnvironment(error_seed=0)
    result = run_evaluation(environment, tmp_path)
    assert environment.seeds == [0]
    assert result["complete"] is False
    assert result["attempted_episodes"] == 1
    assert result["evaluated_episodes"] == 0
    assert result["execution_errors"] == 1
    assert result["error_seeds"] == [0]
    assert result["missing_seeds"] == [1]
    assert json.loads((tmp_path / "summary.json").read_text()) == result
    rows = (tmp_path / "episodes.jsonl").read_text().splitlines()
    assert len(rows) == 1
    assert json.loads(rows[0])["termination_reason"] == "exception"
    resumed = FakeEnvironment()
    assert run_evaluation(resumed, tmp_path, resume=True)["complete"] is True
    assert resumed.seeds == [0, 1]


def test_summary_rejects_duplicate_seed() -> None:
    episode = {"seed": 0, "success": False, "termination_reason": "exception"}
    with pytest.raises(ValueError, match="duplicate"):
        summarize([episode, episode], [0])


def test_model_verifier_cannot_override_native_failure(tmp_path: Path) -> None:
    class OverconfidentVerifier(EnvironmentVerifier):
        def verify(self, inputs: dict[str, Any]) -> dict[str, Any]:
            return {**super().verify(inputs), "task_success": True}

    agent = DefaultAgent(
        TaskSkillPlanner(),
        OverconfidentVerifier(),
        InMemoryMemory(),
        LanguageSkillBackend(),
    )
    evaluator = RoboSynChallengeEvaluator(
        cast(Any, FakeEnvironment()), tmp_path, "click_bell", [0]
    )
    result = evaluator.run(
        agent, DirectPipeline(), SyncRuntime(output_dir=tmp_path, max_steps=2)
    )
    assert result["complete"] is True
    assert result["successes"] == 0
    episode = json.loads((tmp_path / "episodes.jsonl").read_text())
    assert episode["authoritative_success"] is False
    assert episode["success"] is False
    raw = json.loads((tmp_path / episode["session_id"] / "result.json").read_text())
    assert raw["success"] is True


def test_resume_preserves_interrupted_attempt_directory(tmp_path: Path) -> None:
    run_evaluation(FakeEnvironment(error_seed=1), tmp_path)
    interrupted = tmp_path / "robosyn-click_bell-random-seed-1-attempt-2"
    interrupted.mkdir()
    trace = interrupted / "trace.jsonl"
    trace.write_text('{"event": "interrupted"}\n')
    assert run_evaluation(FakeEnvironment(), tmp_path, resume=True)["complete"] is True
    assert trace.read_text() == '{"event": "interrupted"}\n'
    assert (
        tmp_path / "robosyn-click_bell-random-seed-1-attempt-3/episode.json"
    ).exists()


def test_matrix_counts_policy_failures_and_missing_process_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "input.json"
    manifest.write_text(
        json.dumps(
            {
                "seeds": [0],
                "tasks": [
                    {"name": "click_bell", "checkpoint_path": "weights/bell"},
                    {"name": "water_pouring", "checkpoint_path": "weights/water"},
                ],
            }
        )
    )

    class Process:
        returncode = 1

    def launch(command: list[str], **kwargs: Any) -> Process:
        name = command[command.index("--task") + 1]
        output = Path(command[command.index("--output") + 1])
        process = Process()
        if name == "click_bell":
            output.mkdir(parents=True)
            (output / "summary.json").write_text(
                json.dumps(
                    {
                        "task": name,
                        "seeds": [0],
                        "requested_episodes": 1,
                        "attempted_episodes": 1,
                        "evaluated_episodes": 1,
                        "execution_errors": 0,
                        "successes": 0,
                        "complete": True,
                    }
                )
            )
            process.returncode = 0
        return process

    monkeypatch.setattr(
        "omniroboagent.evals.benchmarks.robosynchallenge.matrix.subprocess.run", launch
    )
    result = run_matrix(manifest, tmp_path / "matrix", ["python", "runner.py"])
    assert result["requested_episodes"] == 2
    assert result["evaluated_episodes"] == 1
    assert result["success_rate"] == 0
    assert result["complete"] is False
    assert result["tasks"][1]["process_returncode"] == 1


def test_gpu_grouping_and_command_preserve_task_identity(tmp_path: Path) -> None:
    tasks = [
        {"name": f"task{index}", "checkpoint_path": "weights"} for index in range(4)
    ]
    assert group_tasks(tasks, 2) == [[tasks[0], tasks[2]], [tasks[1], tasks[3]]]
    args = task_command(
        ["python", "runner.py", "--gpu", "5", "--device", "cuda:5"],
        {"tasks": tasks, "seeds": [0, 1], "agent_config": "visual.yaml"},
        tasks[1],
        tmp_path,
        resume=True,
        gpu=4,
    )
    assert args[-4:] == ["--gpu", "4", "--device", "cuda:4"]
    assert args[args.index("--task") + 1] == "task1"
    assert args[args.index("--output") + 1] == str(tmp_path / "task1")
    assert "--resume" in args


def test_parallel_queues_run_each_task_once_and_aggregate_all_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = [
        {"name": f"task{index}", "checkpoint_path": "weights"} for index in range(4)
    ]
    manifest = {"tasks": tasks, "seeds": [0, 1]}
    path = tmp_path / "input.json"
    path.write_text(json.dumps(manifest))
    first_tasks = Barrier(2)
    lock = Lock()
    observed: dict[int, list[str]] = {5: [], 4: []}

    class Process:
        returncode = 0

    def launch(command: list[str], **kwargs: Any) -> Process:
        name = command[command.index("--task") + 1]
        gpu = int(command[-3])
        assert command[-1] == f"cuda:{gpu}"
        with lock:
            observed[gpu].append(name)
        if name in {"task0", "task1"}:
            first_tasks.wait(timeout=5)
        output = Path(command[command.index("--output") + 1])
        output.mkdir()
        write_json(
            output / "summary.json",
            {
                "task": name,
                "seeds": [0, 1],
                "requested_episodes": 2,
                "attempted_episodes": 2,
                "evaluated_episodes": 2,
                "execution_errors": 0,
                "successes": 0,
                "complete": True,
            },
        )
        return Process()

    monkeypatch.setattr(
        "omniroboagent.evals.benchmarks.robosynchallenge.matrix.subprocess.run", launch
    )
    result = run_matrix(path, tmp_path / "matrix", ["python"], matrix_gpus=[5, 4])
    assert observed == {5: ["task0", "task2"], 4: ["task1", "task3"]}
    assert result["complete"] is True
    assert result["evaluated_episodes"] == 8
    assert result["success_rate"] == 0
    assert result["matrix_scheduling"] == "fixed"
    assert json.loads((tmp_path / "matrix/summary.json").read_text()) == result


def test_matrix_includes_partial_and_missing_task_summaries(tmp_path: Path) -> None:
    tasks = [{"name": f"task{index}"} for index in range(2)]
    (tmp_path / "task0").mkdir()
    write_json(
        tmp_path / "task0/summary.json",
        {
            "task": "task0",
            "seeds": [0, 1],
            "requested_episodes": 2,
            "attempted_episodes": 1,
            "evaluated_episodes": 1,
            "execution_errors": 0,
            "successes": 1,
            "complete": False,
        },
    )
    summary = summarize_matrix({"tasks": tasks, "seeds": [0, 1]}, tmp_path, {})
    assert len(summary["tasks"]) == 2
    assert summary["requested_episodes"] == 4
    assert summary["evaluated_episodes"] == 1
    assert summary["complete"] is False
    assert summary["pending_tasks"] == ["task0", "task1"]


def test_dynamic_free_gpu_takes_fifo_tasks_without_moving_existing_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = [{"name": f"task{i}", "checkpoint_path": "weights"} for i in range(4)]
    manifest = {"tasks": tasks, "seeds": [0]}
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(manifest))
    output = tmp_path / "matrix"
    for name, gpu in (("task0", 5), ("task1", 4)):
        directory = output / name
        directory.mkdir(parents=True)
        write_json(directory / "metadata.json", {"task": name, "gpu_id": gpu})
    release_slow = Event()
    lock = Lock()
    observed: dict[int, list[str]] = {5: [], 4: []}

    class Process:
        returncode = 0

    def launch(command: list[str], **kwargs: Any) -> Process:
        name = command[command.index("--task") + 1]
        gpu = int(command[-3])
        with lock:
            observed[gpu].append(name)
        if name == "task0":
            assert release_slow.wait(timeout=5)
        directory = Path(command[command.index("--output") + 1])
        directory.mkdir(exist_ok=True)
        write_json(
            directory / "summary.json",
            {
                "task": name,
                "seeds": [0],
                "requested_episodes": 1,
                "attempted_episodes": 1,
                "evaluated_episodes": 1,
                "execution_errors": 0,
                "successes": 0,
                "complete": True,
            },
        )
        if name == "task3":
            release_slow.set()
        return Process()

    monkeypatch.setattr(
        "omniroboagent.evals.benchmarks.robosynchallenge.matrix.subprocess.run", launch
    )
    result = run_matrix(
        input_path,
        output,
        ["python"],
        resume=True,
        matrix_gpus=[5, 4],
        matrix_scheduling="dynamic",
    )
    assert observed == {5: ["task0"], 4: ["task1", "task2", "task3"]}
    assert result["complete"] is True
    assert result["evaluated_episodes"] == 4
    expected = {"task0": 5, "task1": 4, "task2": 4, "task3": 4}
    assert result["task_gpu_assignment"] == expected
    assert json.loads((output / "gpu_allocation.json").read_text()) == {
        "task_gpu_assignment": expected
    }
    assert json.loads((output / "manifest.json").read_text()) == manifest


def test_dynamic_resume_keeps_assignment_before_task_metadata_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = {
        "tasks": [{"name": "task0", "checkpoint_path": "weights"}],
        "seeds": [0],
    }
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(manifest))
    output = tmp_path / "matrix"
    output.mkdir()
    write_json(output / "gpu_allocation.json", {"task_gpu_assignment": {"task0": 5}})
    observed: list[int] = []

    class Process:
        returncode = 1

    def launch(command: list[str], **kwargs: Any) -> Process:
        observed.append(int(command[-3]))
        return Process()

    monkeypatch.setattr(
        "omniroboagent.evals.benchmarks.robosynchallenge.matrix.subprocess.run", launch
    )
    for gpus in ([4, 5], [5, 4]):
        result = run_matrix(
            input_path,
            output,
            ["python"],
            resume=True,
            matrix_gpus=gpus,
            matrix_scheduling="dynamic",
        )
        assert result["complete"] is False
        assert result["task_gpu_assignment"] == {"task0": 5}
    assert observed == [5, 5]
    assert not (output / "task0/metadata.json").exists()


@pytest.mark.parametrize(
    ("assigned_gpu", "metadata_gpu"), [(99, None), (None, 99), (5, 4)]
)
def test_dynamic_rejects_invalid_or_conflicting_gpu_assignments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    assigned_gpu: int | None,
    metadata_gpu: int | None,
) -> None:
    input_path = tmp_path / "input.json"
    input_path.write_text(
        json.dumps({"tasks": [{"name": "task0", "checkpoint_path": "weights"}]})
    )
    output = tmp_path / "matrix"
    output.mkdir()
    if assigned_gpu is not None:
        write_json(
            output / "gpu_allocation.json",
            {"task_gpu_assignment": {"task0": assigned_gpu}},
        )
    if metadata_gpu is not None:
        (output / "task0").mkdir()
        write_json(output / "task0/metadata.json", {"gpu_id": metadata_gpu})
    monkeypatch.setattr(
        "omniroboagent.evals.benchmarks.robosynchallenge.matrix.subprocess.run",
        lambda *args, **kwargs: pytest.fail("Invalid allocation must not launch tasks"),
    )
    with pytest.raises(ValueError, match="GPU allocation"):
        run_matrix(
            input_path,
            output,
            ["python"],
            resume=True,
            matrix_gpus=[5, 4],
            matrix_scheduling="dynamic",
        )


def test_persistent_matrix_keeps_all_100_seeds(tmp_path: Path) -> None:
    seeds = list(range(100))
    path = tmp_path / "manifest.json"
    write_json(path, {"seeds": seeds})
    assert json.loads(path.read_text())["seeds"] == seeds


def test_resume_repairs_legacy_truncated_100_seed_metadata(tmp_path: Path) -> None:
    seeds = list(range(100))
    run_evaluation(FakeEnvironment(error_seed=0), tmp_path, seeds=seeds)
    path = tmp_path / "metadata.json"
    previous = json.loads(path.read_text())
    previous["seeds"] = to_jsonable(seeds)
    path.write_text(json.dumps(previous))
    result = run_evaluation(
        FakeEnvironment(error_seed=0), tmp_path, seeds=seeds, resume=True
    )
    assert result["requested_episodes"] == 100
    assert result["attempted_episodes"] == 1
    assert len(result["missing_seeds"]) == 99
    assert json.loads(path.read_text())["seeds"] == seeds


def test_resume_repairs_legacy_truncated_matrix_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = {
        "seeds": list(range(100)),
        "tasks": [{"name": "click_bell", "checkpoint_path": "weights"}],
    }
    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(manifest))
    output = tmp_path / "matrix"
    output.mkdir()
    (output / "manifest.json").write_text(json.dumps(to_jsonable(manifest)))

    class Process:
        returncode = 1

    monkeypatch.setattr(
        "omniroboagent.evals.benchmarks.robosynchallenge.matrix.subprocess.run",
        lambda *args, **kwargs: Process(),
    )
    result = run_matrix(input_path, output, ["python"], resume=True)
    assert result["requested_episodes"] == 100
    assert result["complete"] is False
    assert json.loads((output / "manifest.json").read_text()) == manifest
