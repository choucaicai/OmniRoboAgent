#!/usr/bin/env python3
"""Build, validate, and audit the AdaptivePromptSkill Composite-Seen run."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

PACKAGE = Path(
    "/root/autodl-tmp/OmniRoboAgent-AdaptivePromptSkill-Transfer_20260827"
)
LAB = Path("/root/autodl-tmp/OmniRoboAgent-RoboCasa365-Lab")
CODE = PACKAGE / "code_variants" / "robocasa03_goalcontract_jointjudge_partial_reset_seen"
ROBOCASA_ROOT = LAB / "third_party/robocasa-1.0.1"
BASE_AGENT_CONFIG = (
    CODE / "configs/agents/robocasa03_gpt56_sol_adaptive_prompt_skill_seen_noreset.yaml"
)
MODE = os.environ.get("ROBOCASA_JOINT_MODE", "formal")
if MODE not in {"canary", "pilot", "formal"}:
    raise RuntimeError(f"invalid ROBOCASA_JOINT_MODE: {MODE!r}")
CANARY = MODE == "canary"
PILOT = MODE == "pilot"
DEFAULT_RUN_ROOT = PACKAGE / "runs" / (
    "_canary_goalcontract_jointjudge_partialreset_sol_seen_9gpu_18worker_20260828"
    if CANARY
    else "robocasa03_goalcontract_jointjudge_partialreset_sol_composite_seen_pilot160_9gpu_36worker_20260828"
    if PILOT
    else "robocasa03_goalcontract_jointjudge_partialreset_sol_composite_seen_9gpu_36worker_20260828"
)
RUN_ROOT = Path(os.environ.get("ROBOCASA_RUN_ROOT", str(DEFAULT_RUN_ROOT)))
AGENT_CONFIG = RUN_ROOT / "configs" / "agent.yaml"
COMMON_MANIFEST = RUN_ROOT / "canonical_manifest.json"
PHASE_MANIFEST = RUN_ROOT / "sol" / "primary" / "episode_manifest.json"

MODEL = "gpt-5.6-sol"
API_BASE_URL = "https://shuliuyun.com/v1"
SEED = 7
SEED_STRIDE = 50
TASK_START = 18
TASK_STOP = 27 if CANARY else 34
EPISODES_PER_TASK = 2 if CANARY else 10 if PILOT else 50
NUM_GPUS = 9
WORKERS_PER_GPU = 2 if CANARY else 4
NUM_WORKERS = NUM_GPUS * WORKERS_PER_GPU
HORIZON_MULTIPLIER = 0.20 if CANARY else 4.0
PARTIAL_RESET_TRIGGER_MULTIPLIER = 0.05 if CANARY else 2.0
PLANNER_CHECK_INTERVAL_CHUNKS = 4 if CANARY else 64
VERIFIER_CHECK_INTERVAL_CHUNKS = 4 if CANARY else 64
BASE_PORT = 19301
API_RETRY_PHASES = 0 if CANARY else 1


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_yaml(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100000),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"JSON root must be an object: {path}")
    return payload


def requested_agent_config() -> dict[str, Any]:
    payload = yaml.safe_load(BASE_AGENT_CONFIG.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("base agent config must be a mapping")
    payload["task_decomposer"]["init_args"]["max_nodes"] = 8
    payload["verifier"]["init_args"][
        "check_interval_chunks"
    ] = VERIFIER_CHECK_INTERVAL_CHUNKS
    return payload


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise RuntimeError(f"invalid JSONL {path}:{line_number}") from error
        if not isinstance(row, dict):
            raise RuntimeError(f"JSONL row must be an object: {path}:{line_number}")
        rows.append(row)
    return rows


def identity(item: dict[str, Any]) -> tuple[str, int, int]:
    return (
        str(item["task_name"]),
        int(item["episode_index"]),
        int(item["seed"]),
    )


def worker_output(worker: int) -> Path:
    return RUN_ROOT / "sol" / "primary" / f"worker_{worker}"


def worker_config(worker: int) -> Path:
    return RUN_ROOT / "configs" / "sol" / "primary" / f"worker_{worker}.yaml"


def load_manifest() -> dict[str, Any]:
    if not COMMON_MANIFEST.exists():
        raise RuntimeError("canonical manifest is missing; run prepare first")
    return read_json(COMMON_MANIFEST)


def build_manifest() -> dict[str, Any]:
    source_path = str(CODE / "src")
    if source_path not in sys.path:
        sys.path.insert(0, source_path)
    from omniroboagent.environments.benchmarks.robocasa import RoboCasaEnvironment

    environment = RoboCasaEnvironment(
        robocasa_root=ROBOCASA_ROOT,
        enable_render=False,
    )
    target50 = environment.resolve_task_set("target50")
    if len(target50) != 50 or len(set(target50)) != 50:
        raise RuntimeError(f"target50 must resolve exactly 50 tasks, got {len(target50)}")
    tasks = target50[TASK_START:TASK_STOP]
    entries: list[dict[str, Any]] = []
    for episode_index in range(EPISODES_PER_TASK):
        for task_index in range(TASK_START, TASK_STOP):
            task_name = target50[task_index]
            registry_horizon = int(environment.get_task_horizon(task_name))
            entries.append(
                {
                    "task_name": task_name,
                    "task_index": task_index,
                    "task_group": "composite_seen",
                    "episode_index": episode_index,
                    "global_episode_index": task_index * SEED_STRIDE + episode_index,
                    "seed": SEED + task_index * SEED_STRIDE + episode_index,
                    "registry_horizon": registry_horizon,
                    "effective_horizon": math.ceil(
                        registry_horizon * HORIZON_MULTIPLIER
                    ),
                    "horizon_multiplier": HORIZON_MULTIPLIER,
                    "assigned_worker": -1,
                }
            )
    worker_loads = [0] * NUM_WORKERS
    worker_counts = [0] * NUM_WORKERS
    for item in sorted(
        entries,
        key=lambda row: (
            -int(row["effective_horizon"]),
            str(row["task_name"]),
            int(row["episode_index"]),
            int(row["seed"]),
        ),
    ):
        worker = min(
            range(NUM_WORKERS),
            key=lambda candidate: (
                worker_loads[candidate],
                worker_counts[candidate],
                candidate,
            ),
        )
        item["assigned_worker"] = worker
        worker_loads[worker] += int(item["effective_horizon"])
        worker_counts[worker] += 1
    expected = len(tasks) * EPISODES_PER_TASK
    if len(entries) != expected or len({identity(item) for item in entries}) != expected:
        raise RuntimeError("canonical manifest identities are not unique and complete")
    return {
        "schema_version": 1,
        "mode": MODE,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "task_set": "target50",
        "split": "pretrain",
        "task_group": "composite_seen",
        "robocasa_version": "1.0.1",
        "robosuite_version": "1.5.2",
        "mujoco_version": "3.3.1",
        "task_names": tasks,
        "episodes_per_task": EPISODES_PER_TASK,
        "required_episode_count": expected,
        "seed": SEED,
        "seed_episode_stride": SEED_STRIDE,
        "horizon_multiplier": HORIZON_MULTIPLIER,
        "num_gpus": NUM_GPUS,
        "workers_per_gpu": WORKERS_PER_GPU,
        "num_workers": NUM_WORKERS,
        "assignment_policy": "greedy_effective_horizon_balanced_v1",
        "full_environment_reset": False,
        "partial_semantic_reset": True,
        "immutable_goal_contract": "official_task_instruction",
        "mutable_task_graph_max_nodes": 8,
        "task_decomposer_recovery_mode": "temporal_evidence_plan_revision",
        "transition_policy": "verifier_advisory_planner_joint_accept",
        "prompt_skill_registry_version": "adaptive-prompt-registry-0.2.0",
        "partial_reset_trigger_multiplier": PARTIAL_RESET_TRIGGER_MULTIPLIER,
        "episode_restart": False,
        "api_retry_phases": API_RETRY_PHASES,
        "episodes": entries,
    }


def make_worker_config(worker: int, manifest: dict[str, Any]) -> dict[str, Any]:
    output = worker_output(worker)
    gpu = worker // WORKERS_PER_GPU
    maximum_horizon = max(
        int(item["effective_horizon"]) for item in manifest["episodes"]
    )
    return {
        "blocked": False,
        "agent_config": str(AGENT_CONFIG),
        "protocol": {
            "name": f"robocasa03-adaptive-prompt-skill-partial-reset-sol-seen-worker{worker}",
            "mode": MODE,
            "agent_variant": "robocasa03_goalcontract_jointjudge_partial_reset",
            "planner_verifier_model": MODEL,
            "api_base_url": API_BASE_URL,
            "task_set": "target50",
            "split": "pretrain",
            "task_group": "composite_seen",
            "episodes_per_task": EPISODES_PER_TASK,
            "seed": SEED,
            "seed_episode_stride": SEED_STRIDE,
            "horizon_multiplier": HORIZON_MULTIPLIER,
            "partial_reset_trigger_multiplier": PARTIAL_RESET_TRIGGER_MULTIPLIER,
            "continuous_episode_budget": True,
            "full_environment_reset": False,
            "partial_semantic_reset": True,
            "preserved_physical_state": [
                "mujoco_environment",
                "robot",
                "objects",
                "current_observation",
                "official_goal_contract",
                "bounded_recovery_evidence_bundle",
            ],
            "reset_semantic_state": [
                "memory",
                "planner_execution_state",
                "verifier_execution_state",
                "pipeline_execution_state",
                "xiaomi_observation_history",
            ],
            "task_decomposer_initial_calls": 1,
            "task_decomposer_recovery_graph_regeneration_calls": 0,
            "task_decomposer_recovery_progress_reconciliation_calls": 1,
            "task_decomposer_recovery_plan_revision_calls": 1,
            "recovery_temporal_frames": 4,
            "recovery_temporal_frame_age_units": [
                "environment_steps",
                "action_chunks",
            ],
            "recovery_graph_mutation_allowed": True,
            "recovery_graph_max_nodes": 8,
            "verifier_authority": "advisory_only",
            "terminal_transition_rule": "verifier_planner_exact_status_agreement",
            "memory_reset": True,
            "memory_handoff_policy": "bounded_joint_evidence_outside_memory",
            "episode_restart": False,
            "api_error_policy": (
                "defer_without_retry"
                if API_RETRY_PHASES == 0
                else "defer_then_retry_once_at_end"
            ),
            "valid_task_failure_policy": "no_retry",
            "prompt_skill_roles": ["task_decomposer", "planner", "verifier"],
            "prompt_skill_registry_version": "adaptive-prompt-registry-0.2.0",
            "prompt_skill_block_rendering": True,
            "prompt_skill_per_call_sanitized_diff": True,
            "task_decomposer_initial_images": 3,
            "planner_check_interval_chunks": PLANNER_CHECK_INTERVAL_CHUNKS,
            "verifier_check_interval_chunks": VERIFIER_CHECK_INTERVAL_CHUNKS,
            "execute_steps": 16,
            "num_gpus": NUM_GPUS,
            "workers_per_gpu": WORKERS_PER_GPU,
            "num_workers": NUM_WORKERS,
            "worker_index": worker,
            "render_gpu": gpu,
            "xiaomi_port": BASE_PORT + gpu,
            "trace_compression": "gzip",
        },
        "pipeline": {
            "class_path": "omniroboagent.pipelines.SkillExecutionWithMemPipeline",
            "init_args": {
                "action_execution_mode": "receding_horizon",
                "execute_steps": 16,
                "planner_check_interval_chunks": PLANNER_CHECK_INTERVAL_CHUNKS,
                "max_attempts_per_execution": 3,
                "max_uncertain_verifications": 3,
                "max_no_progress_steps": 2,
                "replan_on_no_progress": True,
                "replan_on_uncertain_exhaustion": True,
                "fallback_to_original_task_prompt": True,
                "high_level_replan_limit": 3,
                "recovery_enabled": True,
                "recovery_strategy": "bounded",
                "max_recoveries_per_subtask": 2,
                "max_recoveries_per_episode": 30,
                "require_action_summary": False,
                "max_dynamic_nodes": 8,
                "require_joint_adjudication": True,
            },
        },
        "runtime": {
            "class_path": "omniroboagent.runtimes.SyncRuntime",
            "init_args": {
                "max_environment_steps": maximum_horizon,
                "max_action_chunks": maximum_horizon,
                "max_pipeline_iterations": maximum_horizon,
                "max_invalid_actions": 3,
                "max_retries": 3,
                "timeout_seconds": 21600,
                "restart_at_registry_horizon_multiplier": (
                    PARTIAL_RESET_TRIGGER_MULTIPLIER
                ),
                "preserve_environment_on_horizon_restart": True,
                "trace_compression": "gzip",
                "output_dir": str(output / "traces"),
                "observability": {
                    "class_path": "omniroboagent.observability.LocalEpisodeRecorder",
                    "init_args": {
                        "record_agent_trace": True,
                        "record_video": False,
                        "video_camera_keys": [
                            "video.robot0_agentview_left",
                            "video.robot0_agentview_right",
                            "video.robot0_eye_in_hand",
                        ],
                        "video_fps": 4,
                        "trace_compression": "gzip",
                    },
                },
            },
        },
        "environment": {
            "class_path": (
                "omniroboagent.environments.benchmarks.robocasa."
                "RoboCasaEnvironment"
            ),
            "init_args": {
                "robocasa_root": str(ROBOCASA_ROOT),
                "enable_render": True,
                "render_gpu_device_id": 0,
                "camera_height": 256,
                "camera_width": 256,
                "action_range_policy": "official_controller_clip",
            },
        },
        "benchmark": {
            "class_path": (
                "omniroboagent.evals.benchmarks.robocasa.RoboCasa365Evaluator"
            ),
            "init_args": {
                "task_set": "target50",
                "split": "pretrain",
                "task_names": manifest["task_names"],
                "episodes_per_task": EPISODES_PER_TASK,
                "episode_indices": list(range(EPISODES_PER_TASK)),
                "seed": SEED,
                "seed_episode_stride": SEED_STRIDE,
                "episode_manifest_path": str(PHASE_MANIFEST),
                "worker_index": worker,
                "num_workers": NUM_WORKERS,
                "horizon_multiplier": HORIZON_MULTIPLIER,
                "resume": True,
                "write_checkpoint": False,
                "collect_provenance_hashes": False,
                "defer_api_errors": True,
                "continue_on_action_range_error": True,
                "output_dir": str(output),
            },
        },
    }


def prepare() -> dict[str, Any]:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    requested_agent = requested_agent_config()
    if AGENT_CONFIG.exists():
        if yaml.safe_load(AGENT_CONFIG.read_text(encoding="utf-8")) != requested_agent:
            raise RuntimeError("existing generated agent config differs")
    else:
        write_yaml(AGENT_CONFIG, requested_agent)
    manifest = build_manifest()
    if COMMON_MANIFEST.exists():
        existing = read_json(COMMON_MANIFEST)
        immutable_fields = (
            "mode",
            "task_names",
            "episodes_per_task",
            "required_episode_count",
            "seed",
            "seed_episode_stride",
            "horizon_multiplier",
            "num_gpus",
            "workers_per_gpu",
            "num_workers",
            "full_environment_reset",
            "partial_semantic_reset",
            "partial_reset_trigger_multiplier",
            "episode_restart",
            "api_retry_phases",
        )
        if any(existing.get(field) != manifest.get(field) for field in immutable_fields):
            raise RuntimeError("existing manifest metadata differs from requested protocol")
        if existing.get("episodes") != manifest.get("episodes"):
            raise RuntimeError("existing canonical manifest differs from requested protocol")
        manifest = existing
    else:
        write_json(COMMON_MANIFEST, manifest)
    if PHASE_MANIFEST.exists():
        if read_json(PHASE_MANIFEST).get("episodes") != manifest["episodes"]:
            raise RuntimeError("phase manifest differs from canonical manifest")
    else:
        write_json(PHASE_MANIFEST, manifest)
    for worker in range(NUM_WORKERS):
        config = worker_config(worker)
        requested = make_worker_config(worker, manifest)
        if config.exists():
            if yaml.safe_load(config.read_text(encoding="utf-8")) != requested:
                raise RuntimeError(f"existing worker config differs: {config}")
        else:
            write_yaml(config, requested)
    payload = {
        "mode": manifest["mode"],
        "run_root": str(RUN_ROOT),
        "tasks": len(manifest["task_names"]),
        "episodes": manifest["required_episode_count"],
        "gpus": NUM_GPUS,
        "workers_per_gpu": WORKERS_PER_GPU,
        "workers": NUM_WORKERS,
        "horizon_multiplier": HORIZON_MULTIPLIER,
        "full_environment_reset": False,
        "partial_semantic_reset": True,
        "partial_reset_trigger_multiplier": PARTIAL_RESET_TRIGGER_MULTIPLIER,
        "api_retry_phases": API_RETRY_PHASES,
    }
    print(json.dumps(payload, ensure_ascii=False))
    return payload


def _role_backend_args(agent: dict[str, Any], role: str) -> dict[str, Any]:
    return agent[role]["init_args"]["backend"]["init_args"]


def validate() -> None:
    manifest = load_manifest()
    entries = manifest["episodes"]
    expected_tasks = 9 if CANARY else 16
    expected_episodes = 18 if CANARY else 160 if PILOT else 800
    assert manifest["mode"] == MODE
    assert manifest["task_group"] == "composite_seen"
    assert len(manifest["task_names"]) == expected_tasks
    assert len(entries) == expected_episodes
    assert len({identity(item) for item in entries}) == expected_episodes
    assert manifest["horizon_multiplier"] == HORIZON_MULTIPLIER
    assert manifest["full_environment_reset"] is False
    assert manifest["partial_semantic_reset"] is True
    assert (
        manifest["partial_reset_trigger_multiplier"]
        == PARTIAL_RESET_TRIGGER_MULTIPLIER
    )
    assert manifest["episode_restart"] is False
    assert manifest["api_retry_phases"] == API_RETRY_PHASES
    for item in entries:
        assert TASK_START <= int(item["task_index"]) < TASK_STOP
        assert item["task_group"] == "composite_seen"
        assert int(item["assigned_worker"]) in range(NUM_WORKERS)
        assert int(item["seed"]) == (
            SEED + int(item["task_index"]) * SEED_STRIDE + int(item["episode_index"])
        )
        assert int(item["effective_horizon"]) == math.ceil(
            int(item["registry_horizon"]) * HORIZON_MULTIPLIER
        )

    agent = yaml.safe_load(AGENT_CONFIG.read_text(encoding="utf-8"))
    roles = ("task_decomposer", "planner", "verifier")
    for role in roles:
        backend = _role_backend_args(agent, role)
        assert backend["base_url"] == API_BASE_URL
        assert backend["model"] == MODEL
        assert "api_key" not in backend
        prompt_skill = agent[role]["init_args"]["prompt_skill"]
        assert prompt_skill["class_path"].endswith("AdaptivePromptSkill")
        assert prompt_skill["init_args"]["default_task_shape"] == "composite"
    assert agent["task_decomposer"]["init_args"]["max_images"] == 3
    assert agent["task_decomposer"]["init_args"]["max_nodes"] == 8
    assert agent["task_decomposer"]["init_args"]["recovery_max_frames"] == 4
    assert agent["task_decomposer"]["init_args"]["recovery_images_per_frame"] == 3
    assert agent["task_decomposer"]["init_args"]["max_tokens"] == 3072
    assert agent["planner"]["init_args"]["max_tokens"] == 2048
    assert agent["verifier"]["init_args"]["max_tokens"] == 2048
    assert (
        agent["verifier"]["init_args"]["check_interval_chunks"]
        == VERIFIER_CHECK_INTERVAL_CHUNKS
    )
    assert agent["skill_backend"]["init_args"]["ports"] == list(
        range(BASE_PORT, BASE_PORT + 9)
    )

    for worker in range(NUM_WORKERS):
        config = yaml.safe_load(worker_config(worker).read_text(encoding="utf-8"))
        protocol = config["protocol"]
        pipeline = config["pipeline"]["init_args"]
        runtime = config["runtime"]["init_args"]
        benchmark = config["benchmark"]["init_args"]
        assert config["agent_config"] == str(AGENT_CONFIG)
        assert protocol["planner_verifier_model"] == MODEL
        assert protocol["horizon_multiplier"] == HORIZON_MULTIPLIER
        assert protocol["full_environment_reset"] is False
        assert protocol["partial_semantic_reset"] is True
        assert (
            protocol["partial_reset_trigger_multiplier"]
            == PARTIAL_RESET_TRIGGER_MULTIPLIER
        )
        assert protocol["episode_restart"] is False
        assert protocol["api_error_policy"] == (
            "defer_without_retry"
            if API_RETRY_PHASES == 0
            else "defer_then_retry_once_at_end"
        )
        assert protocol["recovery_graph_mutation_allowed"] is True
        assert protocol["task_decomposer_recovery_graph_regeneration_calls"] == 0
        assert protocol["task_decomposer_recovery_progress_reconciliation_calls"] == 1
        assert protocol["task_decomposer_recovery_plan_revision_calls"] == 1
        assert protocol["verifier_authority"] == "advisory_only"
        assert protocol["prompt_skill_registry_version"] == (
            "adaptive-prompt-registry-0.2.0"
        )
        assert protocol["prompt_skill_roles"] == list(roles)
        assert protocol["render_gpu"] == worker // WORKERS_PER_GPU
        assert protocol["xiaomi_port"] == BASE_PORT + worker // WORKERS_PER_GPU
        assert pipeline["planner_check_interval_chunks"] == PLANNER_CHECK_INTERVAL_CHUNKS
        assert pipeline["require_joint_adjudication"] is True
        assert (
            runtime["restart_at_registry_horizon_multiplier"]
            == PARTIAL_RESET_TRIGGER_MULTIPLIER
        )
        assert runtime["preserve_environment_on_horizon_restart"] is True
        assert runtime["max_environment_steps"] == max(
            int(item["effective_horizon"]) for item in entries
        )
        assert benchmark["worker_index"] == worker
        assert benchmark["num_workers"] == NUM_WORKERS
        assert benchmark["horizon_multiplier"] == HORIZON_MULTIPLIER
        assert benchmark["defer_api_errors"] is True
        assert benchmark["resume"] is True
        assert benchmark["write_checkpoint"] is False
        assert benchmark["collect_provenance_hashes"] is False
    print(
        "VALIDATION_OK "
        f"mode={manifest['mode']} tasks={expected_tasks} episodes={expected_episodes} "
        f"robocasa=1.0.1 horizon={HORIZON_MULTIPLIER}x "
        f"partial_reset_at={PARTIAL_RESET_TRIGGER_MULTIPLIER}x "
        f"environment_reset=disabled retries={API_RETRY_PHASES} "
        f"gpus={NUM_GPUS} workers={NUM_WORKERS} prompt_skill_roles=3"
    )


def _expected_specs() -> dict[tuple[str, int, int], tuple[int, int]]:
    return {
        identity(item): (int(item["effective_horizon"]), int(item["assigned_worker"]))
        for item in load_manifest()["episodes"]
    }


def protocol_rows(filename: str) -> tuple[list[dict[str, Any]], int]:
    expected = _expected_specs()
    accepted: list[dict[str, Any]] = []
    rejected = 0
    for worker in range(NUM_WORKERS):
        for row in read_jsonl(worker_output(worker) / filename):
            specification = expected.get(identity(row))
            if specification is None:
                rejected += 1
                continue
            horizon, assigned_worker = specification
            if assigned_worker != worker or int(row.get("horizon", -1)) != horizon:
                rejected += 1
                continue
            accepted.append(row)
    return accepted, rejected


def dedupe(rows: list[dict[str, Any]]) -> dict[tuple[str, int, int], dict[str, Any]]:
    unique: dict[tuple[str, int, int], dict[str, Any]] = {}
    for row in rows:
        unique.setdefault(identity(row), row)
    return unique


def status_payload() -> dict[str, Any]:
    manifest = load_manifest()
    valid_rows, rejected_valid = protocol_rows("episodes.jsonl")
    deferred_rows, rejected_deferred = protocol_rows("api_deferred.jsonl")
    valid = dedupe(valid_rows)
    deferred = dedupe(deferred_rows)
    covered = set(valid) | set(deferred)
    successes = sum(bool(row.get("success")) for row in valid.values())
    skill_enabled = 0
    manifest_roles = {role: 0 for role in ("task_decomposer", "planner", "verifier")}
    no_reset_violations = 0
    partial_reset_triggered = 0
    partial_reset_successes = 0
    action_episodes = 0
    rendered_prompt_episodes = 0
    prompt_audit_episodes = 0
    graph_revised_recoveries = 0
    goal_contract_preserved_recoveries = 0
    graph_regeneration_violations = 0
    progress_reconciliation_episodes = 0
    temporal_recovery_episodes = 0
    memory_reset_recoveries = 0
    evidence_bundle_recoveries = 0
    post_recovery_action_episodes = 0
    joint_adjudication_mismatches = 0
    verifier_only_transition_violations = 0
    for row in valid.values():
        joint_adjudication_mismatches += int(
            int(row.get("verifier_calls", 0) or 0)
            != int(row.get("planner_adjudication_calls", 0) or 0)
        )
        verifier_only_transition_violations += int(
            row.get("verifier_only_transition_violations", 0) or 0
        )
        snapshot = row.get("adaptive_prompt_skill") or {}
        enabled_roles = set(snapshot.get("enabled_roles") or [])
        if enabled_roles == set(manifest_roles):
            skill_enabled += 1
        manifests = snapshot.get("last_manifests") or {}
        required_runtime_roles = {"task_decomposer", "planner"}
        if (
            enabled_roles == set(manifest_roles)
            and required_runtime_roles <= set(manifests)
            and all(
                str(manifest.get("version_manifest", {}).get("registry_version", ""))
                == "adaptive-prompt-registry-0.2.0"
                for manifest in manifests.values()
                if isinstance(manifest, Mapping)
            )
        ):
            rendered_prompt_episodes += 1
        audit_history = snapshot.get("prompt_audit_history") or {}
        calls_by_role = snapshot.get("calls_by_role") or {}
        if (
            enabled_roles == set(manifest_roles)
            and all(audit_history.get(role) for role in required_runtime_roles)
            and all(
                int(calls_by_role.get(role, 0)) == 0 or audit_history.get(role)
                for role in enabled_roles
            )
        ):
            prompt_audit_episodes += 1
        last_manifests = snapshot.get("last_manifests") or {}
        for role in manifest_roles:
            if last_manifests.get(role):
                manifest_roles[role] += 1
        partial_reset = (
            bool(row.get("horizon_recovery_triggered"))
            and bool(row.get("horizon_recovery_partial_reset"))
            and not bool(row.get("horizon_recovery_environment_reset"))
            and int(row.get("horizon_recovery_count", 0) or 0) > 0
        )
        if partial_reset:
            partial_reset_triggered += 1
            partial_reset_successes += int(bool(row.get("success")))
            graph_revised_recoveries += int(
                bool(row.get("horizon_recovery_task_graph_revised"))
            )
            goal_contract_preserved_recoveries += int(
                bool(row.get("horizon_recovery_goal_contract_preserved"))
            )
            progress_reconciliation_episodes += int(
                int(row.get("horizon_recovery_progress_reconciliation_calls", 0))
                > 0
            )
            temporal_context = row.get("horizon_recovery_visual_context", [])
            temporal_recovery_episodes += int(
                isinstance(temporal_context, list) and len(temporal_context) >= 2
            )
            memory_reset_recoveries += int(
                bool(row.get("horizon_recovery_memory_reset"))
            )
            evidence_bundle_recoveries += int(
                bool(row.get("horizon_recovery_evidence_bundle_present"))
            )
            recovery_steps = row.get("horizon_recovery_environment_steps", [])
            post_recovery_action_episodes += int(
                isinstance(recovery_steps, list)
                and bool(recovery_steps)
                and int(row.get("environment_steps", 0) or 0)
                > max(int(step) for step in recovery_steps)
            )
        if bool(row.get("horizon_recovery_task_graph_regenerated")):
            graph_regeneration_violations += 1
        if bool(row.get("horizon_recovery_environment_reset")):
            no_reset_violations += 1
        environment_steps = int(
            row.get("environment_steps", row.get("num_environment_steps", 0)) or 0
        )
        action_chunks = int(row.get("action_chunks", 0) or 0)
        if environment_steps > 0 or action_chunks > 0:
            action_episodes += 1
    worker_rows = []
    expected = _expected_specs()
    for worker in range(NUM_WORKERS):
        assigned = {key for key, (_, owner) in expected.items() if owner == worker}
        worker_covered = assigned & covered
        worker_rows.append(
            {
                "worker": worker,
                "assigned": len(assigned),
                "covered": len(worker_covered),
                "remaining": len(assigned - worker_covered),
            }
        )
    return {
        "mode": manifest["mode"],
        "run_root": str(RUN_ROOT),
        "expected": len(expected),
        "valid": len(valid),
        "successes": successes,
        "failures": len(valid) - successes,
        "api_deferred": len(set(deferred) - set(valid)),
        "covered": len(covered),
        "remaining": len(expected) - len(covered),
        "adaptive_prompt_skill_enabled": skill_enabled,
        "rendered_prompt_episodes": rendered_prompt_episodes,
        "prompt_audit_episodes": prompt_audit_episodes,
        "adaptive_prompt_manifest_roles": manifest_roles,
        "action_episodes": action_episodes,
        "partial_reset_triggered": partial_reset_triggered,
        "partial_reset_successes": partial_reset_successes,
        "graph_revised_recoveries": graph_revised_recoveries,
        "goal_contract_preserved_recoveries": goal_contract_preserved_recoveries,
        "graph_regeneration_violations": graph_regeneration_violations,
        "progress_reconciliation_episodes": progress_reconciliation_episodes,
        "temporal_recovery_episodes": temporal_recovery_episodes,
        "memory_reset_recoveries": memory_reset_recoveries,
        "evidence_bundle_recoveries": evidence_bundle_recoveries,
        "post_recovery_action_episodes": post_recovery_action_episodes,
        "joint_adjudication_mismatches": joint_adjudication_mismatches,
        "verifier_only_transition_violations": verifier_only_transition_violations,
        "no_reset_violations": no_reset_violations,
        "rejected_rows": rejected_valid + rejected_deferred,
        "workers": worker_rows,
    }


def status() -> None:
    print(json.dumps(status_payload(), ensure_ascii=False))


def worker_progress(worker: int) -> None:
    payload = status_payload()
    print(json.dumps(payload["workers"][worker], ensure_ascii=False))


def finalize() -> None:
    payload = status_payload()
    payload["finalized_at"] = datetime.now(timezone.utc).isoformat()
    write_json(RUN_ROOT / "FINAL_SUMMARY.json", payload)
    rate = (
        100.0 * payload["successes"] / payload["valid"] if payload["valid"] else 0.0
    )
    report = (
        "# AdaptivePromptSkill Composite-Seen result\n\n"
        "| Expected | Valid | Success | Failure | API deferred | Remaining | Success rate |\n"
        "|---:|---:|---:|---:|---:|---:|---:|\n"
        f"| {payload['expected']} | {payload['valid']} | {payload['successes']} | "
        f"{payload['failures']} | {payload['api_deferred']} | {payload['remaining']} | "
        f"{rate:.2f}% |\n\n"
        f"Prompt Skill enabled results: {payload['adaptive_prompt_skill_enabled']}\n\n"
        f"No-reset violations: {payload['no_reset_violations']}\n"
    )
    (RUN_ROOT / "FINAL_REPORT.md").write_text(report, encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare")
    subparsers.add_parser("validate")
    subparsers.add_parser("status")
    subparsers.add_parser("finalize")
    progress = subparsers.add_parser("worker-progress")
    progress.add_argument("--worker", type=int, choices=range(NUM_WORKERS), required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare()
    elif args.command == "validate":
        validate()
    elif args.command == "status":
        status()
    elif args.command == "finalize":
        finalize()
    elif args.command == "worker-progress":
        worker_progress(args.worker)


if __name__ == "__main__":
    main()
