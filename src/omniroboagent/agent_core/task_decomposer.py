import json
import re
from collections.abc import Mapping
from typing import Any

from omniroboagent.agent_core.adaptive_prompt_skill import (
    AdaptivePromptSkill,
    CallMode,
    GenerateRequest,
    Role,
    SkillSpec,
)
from omniroboagent.backends.llm.base import LLMBackend
from omniroboagent.exceptions import ConfigError, PlannerOutputError
from omniroboagent.serialization import to_jsonable


TASK_DECOMPOSER_PROMPT = """You create one compact, advisory reference DAG for an
embodied manipulation episode. The official task instruction defines every required task
goal. The initial camera views are evidence only for facts that are directly and
unambiguously visible in those views.

Goal coverage:
- Preserve every explicit official task goal, including named objects, required final
  states, destinations, quantities, and relations. Do not silently drop, weaken, or
  replace an official goal with an inferred prerequisite.
- A source or container phrase in the instruction describes task semantics; it is not
  proof that opening, closing, searching, navigating, or repositioning is required.
- Add a prerequisite only when it is an explicit official goal, or when the initial view
  directly proves its state must change before an official goal can be achieved.
- If the initial view clearly proves an added prerequisite is already satisfied, omit it.

Initial-view evidence rules:
- Do not infer hidden contents, object locations, container state, grasp state,
  accessibility, failure, or completion from task wording, common sense, missing pixels,
  occlusion, or an unclear image.
- Unknown is not evidence that a prerequisite is false. When evidence is absent or
  unclear, do not invent a mandatory prerequisite; defer the decision to the online
  planner after it re-observes the environment.
- Available skill names are capabilities, not observations of the world.

DAG rules:
- Each node is one atomic, externally observable state transition with one observable
  expected outcome.
- Include only necessary dependency edges. Do not add loops, alternatives,
  verification-only nodes, duplicate goals, or compound actions.
- This DAG is advisory only. The online planner and verifier may skip, reorder, refine,
  or add task-relevant actions when later evidence warrants it. Do not encode guessed
  prerequisites as mandatory execution restrictions.

Return JSON with exactly this shape:
{
  "nodes": [
    {
      "id": "short_unique_id",
      "instruction": "one atomic action",
      "dependencies": ["earlier_node_id"],
      "expected_outcome": "one observable state"
    }
  ]
}
"""

RECOVERY_RECONCILIATION_PROMPT = """You reconcile progress against one frozen
embodied-task DAG. The DAG node IDs, instructions, dependencies, outcomes, and official
task goal are immutable. You must not add, delete, reorder, rename, rewrite, merge, or
split nodes.

You receive several time-labelled camera groups. Each label states how many environment
steps and action chunks ago the group was observed. Treat older views as history, not as
the current state. Use a node status only when supported by the time-ordered visual
trajectory and execution evidence. Not visible is unknown, not failed or absent.

Return JSON with exactly this shape:
{
  "node_updates": [
    {
      "id": "an existing frozen node id",
      "status": "completed, in_progress, pending, or unknown",
      "visible": true,
      "evidence": ["short time-grounded observation"]
    }
  ],
  "failure_summary": "what blocked progress, without inventing hidden state",
  "correctable_target": "smallest currently correctable target or empty string",
  "critical_unknowns": ["facts that require observation before acting"]
}
"""

RECOVERY_PLAN_REVISION_PROMPT = """You revise a mutable embodied-task plan after
partial recovery. The official instruction is the only immutable goal contract. The
existing DAG is a hypothesis and may contain a wrong prerequisite or miss a necessary
step. Use the time-labelled images and bounded evidence bundle to retain, add, delete,
rewrite, or reorder nodes. Do not change, weaken, or add to the official goal.

Keep 1..8 atomic nodes. A completed status is allowed only for an unchanged node whose
prior graph status was already completed; otherwise use in_progress, pending, or
unknown. Verifier statements are advisory and disputed evidence stays unknown.

Return JSON with exactly this shape:
{
  "task_graph": {"nodes": [{"id": "id", "instruction": "atomic action",
    "dependencies": [], "expected_outcome": "observable state"}]},
  "node_updates": [{"id": "id", "status": "completed, in_progress, pending, or unknown",
    "visible": true, "evidence": ["time-grounded evidence"]}],
  "revision_reason": "why the plan changed or was retained",
  "failure_summary": "current blocker without hidden-state invention",
  "correctable_target": "smallest current target or empty string",
  "critical_unknowns": ["fact requiring observation"]
}
"""


class TaskDecomposer:
    """Create and strictly validate one immutable episode task DAG."""

    def __init__(
        self,
        backend: LLMBackend,
        camera_keys: list[str] | None = None,
        max_images: int = 3,
        max_nodes: int = 32,
        system_prompt: str = TASK_DECOMPOSER_PROMPT,
        max_tokens: int = 3072,
        temperature: float = 0.0,
        extra_body: dict[str, Any] | None = None,
        response_format_mode: str = "json_schema",
        prompt_skill: AdaptivePromptSkill | None = None,
        recovery_max_frames: int = 4,
        recovery_images_per_frame: int = 3,
    ) -> None:
        resolved_keys = ["images", "head_rgb"] if camera_keys is None else camera_keys
        if not isinstance(resolved_keys, list) or any(
            not isinstance(key, str) or not key for key in resolved_keys
        ):
            raise ConfigError("TaskDecomposer camera_keys must be non-empty strings")
        if len(set(resolved_keys)) != len(resolved_keys):
            raise ConfigError("TaskDecomposer camera_keys must be unique")
        if not isinstance(max_images, int) or isinstance(max_images, bool) or max_images < 0:
            raise ConfigError("TaskDecomposer max_images must be a non-negative integer")
        if not isinstance(max_nodes, int) or isinstance(max_nodes, bool) or max_nodes < 1:
            raise ConfigError("TaskDecomposer max_nodes must be a positive integer")
        self.backend = backend
        self.camera_keys = list(resolved_keys)
        self.max_images = max_images
        self.max_nodes = max_nodes
        self.system_prompt = system_prompt
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra_body = extra_body or {}
        if response_format_mode not in {"json_schema", "json_object"}:
            raise ConfigError("response_format_mode must be json_schema or json_object")
        self.response_format_mode = response_format_mode
        if not isinstance(recovery_max_frames, int) or isinstance(
            recovery_max_frames, bool
        ) or recovery_max_frames <= 0:
            raise ConfigError("recovery_max_frames must be a positive integer")
        if not isinstance(recovery_images_per_frame, int) or isinstance(
            recovery_images_per_frame, bool
        ) or recovery_images_per_frame <= 0:
            raise ConfigError("recovery_images_per_frame must be a positive integer")
        self.recovery_max_frames = recovery_max_frames
        self.recovery_images_per_frame = recovery_images_per_frame
        self.prompt_skill = prompt_skill
        self.last_prompt_manifest: dict[str, Any] | None = None
        self.last_model_usage: dict[str, Any] | None = None

    def decompose(self, context: Mapping[str, Any]) -> dict[str, Any]:
        observation = context.get("initial_observation")
        prompt = json.dumps(
            to_jsonable(
                {
                    "task": context.get("task"),
                    "official_task_instruction": (
                        observation.get("annotation.human.task_description")
                        if isinstance(observation, Mapping)
                        else None
                    ),
                    "available_skills": self._available_skills(observation),
                }
            ),
            ensure_ascii=False,
        )
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for image in self._images(observation):
            content.append({"type": "image_url", "image_url": {"url": image}})
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": content},
        ]
        if self.prompt_skill is not None:
            skills = tuple(
                SkillSpec(skill_id=skill) for skill in self._available_skills(observation)
            )
            generated = self.prompt_skill.generate(
                GenerateRequest(
                    role=Role.TASK_DECOMPOSER,
                    task={
                        "task": context.get("task"),
                        "official_task_instruction": (
                            observation.get("annotation.human.task_description")
                            if isinstance(observation, Mapping)
                            else None
                        ),
                    },
                    observations=(observation if isinstance(observation, Mapping) else {}),
                    task_state={"available_skills": [skill.skill_id for skill in skills]},
                    execution_history=(),
                    failure_information=None,
                    available_skills=skills,
                    prompt_version=self.prompt_skill.default_version,
                    call_mode=CallMode.INITIAL_TASK_DECOMPOSITION,
                    prebuilt_messages=tuple(messages),
                )
            )
            messages = [dict(message) for message in generated.messages]
            self.last_prompt_manifest = {
                "content_hash": generated.content_hash,
                "call_mode": generated.call_mode.value,
                "task_shape": generated.task_shape.value,
                "selected_blocks": [
                    {
                        "block_id": block.block_id,
                        "version": block.version,
                        "digest": block.digest,
                    }
                    for block in generated.selected_blocks
                ],
                "version_manifest": dict(generated.version_manifest),
                "prompt_audit": dict(self.prompt_skill.last_audit or {}),
            }
        response = self.backend.complete(
            {
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "response_format": (
                    {"type": "json_object"}
                    if self.response_format_mode == "json_object"
                    else {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "episode_task_graph",
                        "schema": self._schema(),
                    },
                }
                ),
                "extra_body": self.extra_body,
            }
        )
        self.last_model_usage = self._response_usage(response)
        return self.validate_graph(self._parse_response(response), max_nodes=self.max_nodes)

    def reconcile_progress(self, context: Mapping[str, Any]) -> dict[str, Any]:
        graph = context.get("frozen_task_graph")
        nodes = graph.get("nodes") if isinstance(graph, Mapping) else None
        if not isinstance(nodes, list) or not nodes:
            raise PlannerOutputError("recovery reconciliation requires a frozen task graph")
        node_ids = {
            str(node.get("id"))
            for node in nodes
            if isinstance(node, Mapping) and isinstance(node.get("id"), str)
        }
        if len(node_ids) != len(nodes):
            raise PlannerOutputError("frozen task graph contains invalid node IDs")
        temporal_frames = context.get("temporal_frames", [])
        if not isinstance(temporal_frames, list) or not temporal_frames:
            raise PlannerOutputError("recovery reconciliation requires temporal frames")
        selected_frames = temporal_frames[-self.recovery_max_frames :]
        frame_metadata: list[dict[str, Any]] = []
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": json.dumps(
                    to_jsonable(
                        {
                            "task": context.get("task"),
                            "frozen_task_graph": graph,
                            "recovery_handoff": context.get("recovery_handoff"),
                            "invariant": "node identities and meanings must not change",
                        }
                    ),
                    ensure_ascii=False,
                ),
            }
        ]
        current_observation: Mapping[str, Any] = {}
        for index, frame in enumerate(selected_frames):
            if not isinstance(frame, Mapping):
                continue
            observation = frame.get("observation")
            if not isinstance(observation, Mapping):
                continue
            current_observation = observation
            metadata = {
                "frame_index": index,
                "phase": frame.get("phase", "historical"),
                "environment_steps": frame.get("environment_steps"),
                "action_chunks": frame.get("action_chunks"),
                "age_environment_steps": frame.get("age_environment_steps"),
                "age_action_chunks": frame.get("age_action_chunks"),
            }
            frame_metadata.append(metadata)
            content.append(
                {
                    "type": "text",
                    "text": "TEMPORAL_FRAME "
                    + json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                }
            )
            for image in self._images(observation)[: self.recovery_images_per_frame]:
                content.append({"type": "image_url", "image_url": {"url": image}})
        if not frame_metadata:
            raise PlannerOutputError("temporal frames contain no valid observations")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": RECOVERY_RECONCILIATION_PROMPT},
            {"role": "user", "content": content},
        ]
        if self.prompt_skill is not None:
            skills = tuple(
                SkillSpec(skill_id=skill)
                for skill in self._available_skills(current_observation)
            )
            generated = self.prompt_skill.generate(
                GenerateRequest(
                    role=Role.TASK_DECOMPOSER,
                    task={
                        "task": context.get("task"),
                        "official_task_instruction": context.get(
                            "official_task_instruction"
                        ),
                    },
                    observations={},
                    task_state={
                        "task_shape": "composite",
                        "task_graph": graph,
                        "temporal_frame_metadata": frame_metadata,
                        "recovery_handoff": context.get("recovery_handoff"),
                    },
                    execution_history=(),
                    failure_information={
                        "scope": "progress_reconciliation",
                        "failure_class": "horizon_partial_recovery",
                        "summary": context.get("recovery_handoff"),
                    },
                    available_skills=skills,
                    prompt_version=self.prompt_skill.default_version,
                    call_mode=CallMode.RECOVERY_PROGRESS_RECONCILIATION,
                    prebuilt_messages=tuple(messages),
                )
            )
            messages = [dict(message) for message in generated.messages]
            self.last_prompt_manifest = {
                "content_hash": generated.content_hash,
                "call_mode": generated.call_mode.value,
                "task_shape": generated.task_shape.value,
                "selected_blocks": [
                    {
                        "block_id": block.block_id,
                        "version": block.version,
                        "digest": block.digest,
                    }
                    for block in generated.selected_blocks
                ],
                "version_manifest": dict(generated.version_manifest),
                "prompt_audit": dict(self.prompt_skill.last_audit or {}),
            }
        response = self.backend.complete(
            {
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
                "extra_body": self.extra_body,
            }
        )
        self.last_model_usage = self._response_usage(response)
        return self.validate_reconciliation(self._parse_response(response), node_ids)

    def revise_plan_graph(self, context: Mapping[str, Any]) -> dict[str, Any]:
        """Revise the plan hypothesis while keeping the official goal immutable."""
        graph = context.get("current_task_graph")
        nodes = graph.get("nodes") if isinstance(graph, Mapping) else None
        if not isinstance(nodes, list) or not nodes:
            raise PlannerOutputError("recovery revision requires a current task graph")
        official_instruction = context.get("official_task_instruction")
        if not isinstance(official_instruction, str) or not official_instruction.strip():
            raise PlannerOutputError("recovery revision requires official task instruction")
        temporal_frames = context.get("temporal_frames", [])
        if not isinstance(temporal_frames, list) or not temporal_frames:
            raise PlannerOutputError("recovery revision requires temporal frames")
        selected_frames = temporal_frames[-self.recovery_max_frames :]
        frame_metadata: list[dict[str, Any]] = []
        current_observation: Mapping[str, Any] = {}
        content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": json.dumps(
                    to_jsonable(
                        {
                            "immutable_goal_contract": {
                                "official_instruction": official_instruction.strip(),
                                "immutable": True,
                            },
                            "current_mutable_task_graph": graph,
                            "recovery_evidence_bundle": context.get(
                                "recovery_evidence_bundle"
                            ),
                        }
                    ),
                    ensure_ascii=False,
                ),
            }
        ]
        for index, frame in enumerate(selected_frames):
            if not isinstance(frame, Mapping):
                continue
            observation = frame.get("observation")
            if not isinstance(observation, Mapping):
                continue
            current_observation = observation
            metadata = {
                "frame_index": index,
                "phase": frame.get("phase", "historical"),
                "environment_steps": frame.get("environment_steps"),
                "action_chunks": frame.get("action_chunks"),
                "age_environment_steps": frame.get("age_environment_steps"),
                "age_action_chunks": frame.get("age_action_chunks"),
            }
            frame_metadata.append(metadata)
            content.append(
                {
                    "type": "text",
                    "text": "TEMPORAL_FRAME "
                    + json.dumps(metadata, ensure_ascii=False, sort_keys=True),
                }
            )
            for image in self._images(observation)[: self.recovery_images_per_frame]:
                content.append({"type": "image_url", "image_url": {"url": image}})
        if not frame_metadata:
            raise PlannerOutputError("temporal frames contain no valid observations")
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": RECOVERY_PLAN_REVISION_PROMPT},
            {"role": "user", "content": content},
        ]
        if self.prompt_skill is not None:
            generated = self.prompt_skill.generate(
                GenerateRequest(
                    role=Role.TASK_DECOMPOSER,
                    task={"official_task_instruction": official_instruction.strip()},
                    observations={},
                    task_state={
                        "task_shape": "composite",
                        "goal_contract": {
                            "official_instruction": official_instruction.strip(),
                            "immutable": True,
                        },
                        "task_graph": graph,
                        "temporal_frame_metadata": frame_metadata,
                        "recovery_evidence_bundle": context.get(
                            "recovery_evidence_bundle"
                        ),
                    },
                    execution_history=tuple(
                        item
                        for item in (
                            context.get("recovery_evidence_bundle", {}).get(
                                "evidence_ledger", []
                            )
                            if isinstance(
                                context.get("recovery_evidence_bundle"), Mapping
                            )
                            else []
                        )
                        if isinstance(item, Mapping)
                    ),
                    failure_information={
                        "scope": "plan_graph_revision",
                        "failure_class": "horizon_partial_recovery",
                        "summary": context.get("recovery_evidence_bundle"),
                    },
                    available_skills=tuple(
                        SkillSpec(skill_id=skill)
                        for skill in self._available_skills(current_observation)
                    ),
                    prompt_version=self.prompt_skill.default_version,
                    call_mode=CallMode.RECOVERY_PLAN_REVISION,
                    prebuilt_messages=tuple(messages),
                )
            )
            messages = [dict(message) for message in generated.messages]
            self.last_prompt_manifest = {
                "content_hash": generated.content_hash,
                "call_mode": generated.call_mode.value,
                "task_shape": generated.task_shape.value,
                "selected_blocks": [
                    {
                        "block_id": block.block_id,
                        "version": block.version,
                        "digest": block.digest,
                    }
                    for block in generated.selected_blocks
                ],
                "version_manifest": dict(generated.version_manifest),
                "prompt_audit": dict(self.prompt_skill.last_audit or {}),
            }
        response = self.backend.complete(
            {
                "messages": messages,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
                "extra_body": self.extra_body,
            }
        )
        self.last_model_usage = self._response_usage(response)
        return self.validate_plan_revision(
            self._parse_response(response), graph, max_nodes=min(self.max_nodes, 8)
        )

    @classmethod
    def validate_plan_revision(
        cls, payload: Any, old_graph: Mapping[str, Any], *, max_nodes: int = 8
    ) -> dict[str, Any]:
        required = {
            "task_graph",
            "node_updates",
            "revision_reason",
            "failure_summary",
            "correctable_target",
            "critical_unknowns",
        }
        if not isinstance(payload, Mapping) or set(payload) != required:
            raise PlannerOutputError("plan revision response has invalid fields")
        graph = cls.validate_graph(payload.get("task_graph"), max_nodes=max_nodes)
        graph["revision"] = int(old_graph.get("revision", 0)) + 1
        old_completed = {
            str(node.get("id"))
            for node in old_graph.get("nodes", [])
            if isinstance(node, Mapping) and node.get("status") == "completed"
        }
        node_ids = {str(node["id"]) for node in graph["nodes"]}
        updates = payload.get("node_updates")
        if not isinstance(updates, list):
            raise PlannerOutputError("plan revision node_updates must be a list")
        by_id: dict[str, dict[str, Any]] = {}
        for update in updates:
            if not isinstance(update, Mapping) or set(update) != {
                "id",
                "status",
                "visible",
                "evidence",
            }:
                raise PlannerOutputError("plan revision node update has invalid fields")
            node_id = update.get("id")
            status = update.get("status")
            evidence = update.get("evidence")
            if node_id not in node_ids or node_id in by_id:
                raise PlannerOutputError("plan revision references unknown or duplicate node")
            if status not in {"completed", "in_progress", "pending", "unknown"}:
                raise PlannerOutputError("plan revision has invalid node status")
            if status == "completed" and node_id not in old_completed:
                raise PlannerOutputError(
                    "recovery cannot newly promote a node to completed"
                )
            if not isinstance(update.get("visible"), bool):
                raise PlannerOutputError("plan revision visible must be boolean")
            if not isinstance(evidence, list) or any(
                not isinstance(item, str) for item in evidence
            ):
                raise PlannerOutputError("plan revision evidence must be a string list")
            by_id[str(node_id)] = {
                "status": status,
                "visible": update["visible"],
                "evidence": [item[:512] for item in evidence[:6]],
            }
        for node in graph["nodes"]:
            update = by_id.get(node["id"])
            if update is not None:
                node.update(update)
        text_fields = ("revision_reason", "failure_summary", "correctable_target")
        if any(not isinstance(payload.get(key), str) for key in text_fields):
            raise PlannerOutputError("plan revision summaries must be strings")
        unknowns = payload.get("critical_unknowns")
        if not isinstance(unknowns, list) or any(
            not isinstance(item, str) for item in unknowns
        ):
            raise PlannerOutputError("plan revision critical_unknowns must be strings")
        return {
            "task_graph": graph,
            "node_updates": [
                {"id": node_id, **value} for node_id, value in by_id.items()
            ],
            "revision_reason": payload["revision_reason"][:2048],
            "failure_summary": payload["failure_summary"][:2048],
            "correctable_target": payload["correctable_target"][:1024],
            "critical_unknowns": [item[:512] for item in unknowns[:12]],
        }

    @staticmethod
    def validate_reconciliation(
        payload: Any, node_ids: set[str]
    ) -> dict[str, Any]:
        required = {
            "node_updates",
            "failure_summary",
            "correctable_target",
            "critical_unknowns",
        }
        if not isinstance(payload, Mapping) or set(payload) != required:
            raise PlannerOutputError("reconciliation response has invalid fields")
        updates = payload.get("node_updates")
        if not isinstance(updates, list):
            raise PlannerOutputError("reconciliation node_updates must be a list")
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for index, update in enumerate(updates):
            if not isinstance(update, Mapping) or set(update) != {
                "id",
                "status",
                "visible",
                "evidence",
            }:
                raise PlannerOutputError(
                    f"reconciliation node update {index} has invalid fields"
                )
            node_id = update.get("id")
            status = update.get("status")
            evidence = update.get("evidence")
            visible = update.get("visible")
            if node_id not in node_ids or node_id in seen:
                raise PlannerOutputError(
                    f"reconciliation referenced unknown or duplicate node: {node_id!r}"
                )
            if status not in {"completed", "in_progress", "pending", "unknown"}:
                raise PlannerOutputError(f"invalid reconciliation status: {status!r}")
            if not isinstance(visible, bool):
                raise PlannerOutputError("reconciliation visible must be boolean")
            if not isinstance(evidence, list) or any(
                not isinstance(item, str) for item in evidence
            ):
                raise PlannerOutputError("reconciliation evidence must be a string list")
            seen.add(node_id)
            normalized.append(
                {
                    "id": node_id,
                    "status": status,
                    "visible": visible,
                    "evidence": [item[:512] for item in evidence[:6]],
                }
            )
        unknowns = payload.get("critical_unknowns")
        if not isinstance(unknowns, list) or any(
            not isinstance(item, str) for item in unknowns
        ):
            raise PlannerOutputError("critical_unknowns must be a string list")
        failure_summary = payload.get("failure_summary")
        correctable_target = payload.get("correctable_target")
        if not isinstance(failure_summary, str) or not isinstance(
            correctable_target, str
        ):
            raise PlannerOutputError("reconciliation summaries must be strings")
        return {
            "node_updates": normalized,
            "failure_summary": failure_summary[:2048],
            "correctable_target": correctable_target[:1024],
            "critical_unknowns": [item[:512] for item in unknowns[:12]],
        }

    @staticmethod
    def _response_usage(response: Any) -> dict[str, Any] | None:
        if not isinstance(response, Mapping):
            return None
        usage = response.get("usage")
        if not isinstance(usage, Mapping):
            return None
        return to_jsonable(
            {
                key: response.get(key)
                for key in ("id", "model")
                if response.get(key) is not None
            }
            | {"usage": dict(usage)}
        )

    @classmethod
    def validate_graph(cls, graph: Any, *, max_nodes: int = 32) -> dict[str, Any]:
        if not isinstance(graph, Mapping) or set(graph) != {"nodes"}:
            raise PlannerOutputError("Task graph must contain exactly the nodes field")
        nodes = graph.get("nodes")
        if not isinstance(nodes, list) or not nodes or len(nodes) > max_nodes:
            raise PlannerOutputError(f"Task graph must contain 1..{max_nodes} nodes")
        normalized: list[dict[str, Any]] = []
        ids: list[str] = []
        required = {"id", "instruction", "dependencies", "expected_outcome"}
        for index, node in enumerate(nodes):
            if not isinstance(node, Mapping) or set(node) != required:
                raise PlannerOutputError(f"Task graph node {index} has invalid fields")
            node_id = node.get("id")
            instruction = node.get("instruction")
            outcome = node.get("expected_outcome")
            dependencies = node.get("dependencies")
            if not isinstance(node_id, str) or re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_-]{0,63}", node_id
            ) is None:
                raise PlannerOutputError(f"Task graph node {index} has invalid id")
            if node_id in ids:
                raise PlannerOutputError(f"Duplicate task graph node id: {node_id}")
            if not isinstance(instruction, str) or not instruction.strip():
                raise PlannerOutputError(f"Task graph node {node_id} has empty instruction")
            if not isinstance(outcome, str) or not outcome.strip():
                raise PlannerOutputError(
                    f"Task graph node {node_id} has empty expected_outcome"
                )
            if not isinstance(dependencies, list) or any(
                not isinstance(item, str) for item in dependencies
            ) or len(set(dependencies)) != len(dependencies):
                raise PlannerOutputError(
                    f"Task graph node {node_id} has invalid dependencies"
                )
            ids.append(node_id)
            normalized.append(
                {
                    "id": node_id,
                    "instruction": instruction.strip(),
                    "dependencies": list(dependencies),
                    "expected_outcome": outcome.strip(),
                    "status": "pending",
                }
            )
        id_set = set(ids)
        for node in normalized:
            unknown = set(node["dependencies"]) - id_set
            if unknown or node["id"] in node["dependencies"]:
                raise PlannerOutputError(
                    f"Task graph node {node['id']} has unknown or self dependency"
                )
        ordered = cls._stable_topological_sort(normalized)
        for order, node in enumerate(ordered):
            node["order"] = order
        return {"schema_version": 1, "revision": 0, "nodes": ordered}

    @staticmethod
    def _stable_topological_sort(
        nodes: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        dependencies = {node["id"]: set(node["dependencies"]) for node in nodes}
        input_order = {node["id"]: index for index, node in enumerate(nodes)}
        by_id = {node["id"]: node for node in nodes}
        remaining = set(dependencies)
        resolved: set[str] = set()
        ordered: list[dict[str, Any]] = []
        while remaining:
            ready = sorted(
                (
                    node_id
                    for node_id in remaining
                    if dependencies[node_id] <= resolved
                ),
                key=input_order.__getitem__,
            )
            if not ready:
                raise PlannerOutputError("Task graph must be acyclic")
            ordered.extend(by_id[node_id] for node_id in ready)
            resolved.update(ready)
            remaining.difference_update(ready)
        return ordered

    def healthcheck(self) -> dict[str, Any]:
        return self.backend.healthcheck()

    def close(self) -> None:
        self.backend.close()

    def _images(self, observation: Any) -> list[Any]:
        if not isinstance(observation, Mapping) or self.max_images == 0:
            return []
        images: list[Any] = []
        for key in self.camera_keys:
            value = observation.get(key)
            if value is not None:
                images.extend(value if isinstance(value, list) else [value])
        return images[: self.max_images]

    @staticmethod
    def _available_skills(observation: Any) -> list[str]:
        if not isinstance(observation, Mapping):
            return []
        skills = observation.get("available_skills", [])
        return (
            [item for item in skills if isinstance(item, str)]
            if isinstance(skills, list)
            else []
        )

    def _schema(self) -> dict[str, Any]:
        node = {
            "type": "object",
            "properties": {
                "id": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$"},
                "instruction": {"type": "string", "minLength": 1},
                "dependencies": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "expected_outcome": {"type": "string", "minLength": 1},
            },
            "required": ["id", "instruction", "dependencies", "expected_outcome"],
            "additionalProperties": False,
        }
        return {
            "type": "object",
            "properties": {
                "nodes": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": self.max_nodes,
                    "items": node,
                }
            },
            "required": ["nodes"],
            "additionalProperties": False,
        }

    @staticmethod
    def _parse_response(response: Any) -> dict[str, Any]:
        try:
            content = response["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise PlannerOutputError("TaskDecomposer response is missing content") from error
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", ""))
                for item in content
                if isinstance(item, Mapping)
            )
        if not isinstance(content, str):
            raise PlannerOutputError("TaskDecomposer response content must be text")
        stripped = content.strip()
        fenced = re.search(r"```(?:json)?\s*(.*?)```", stripped, re.DOTALL)
        if fenced:
            stripped = fenced.group(1).strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise PlannerOutputError("TaskDecomposer returned invalid JSON") from error
        if not isinstance(parsed, dict):
            raise PlannerOutputError("TaskDecomposer JSON must be an object")
        return parsed
