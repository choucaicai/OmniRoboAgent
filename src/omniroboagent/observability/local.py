import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from omniroboagent.observability.base import EpisodeRecorder
from omniroboagent.observability.video import EpisodeVideoWriter
from omniroboagent.serialization import to_jsonable


class LocalEpisodeRecorder(EpisodeRecorder):
    def __init__(
        self,
        record_agent_trace: bool = True,
        record_video: bool = False,
        video_camera_keys: list[str] | None = None,
        video_fps: int = 2,
        ffmpeg_path: str = "ffmpeg",
    ) -> None:
        if not isinstance(record_agent_trace, bool) or not isinstance(
            record_video, bool
        ):
            raise TypeError("record_agent_trace and record_video must be booleans")
        if video_fps <= 0:
            raise ValueError("video_fps must be positive")
        resolved_keys = (
            ["head_rgb", "images"] if video_camera_keys is None else video_camera_keys
        )
        if (
            not isinstance(resolved_keys, list)
            or not resolved_keys
            or any(not isinstance(key, str) or not key for key in resolved_keys)
            or len(set(resolved_keys)) != len(resolved_keys)
        ):
            raise ValueError("video_camera_keys must contain unique non-empty strings")
        if not isinstance(ffmpeg_path, str) or not ffmpeg_path:
            raise ValueError("ffmpeg_path must be a non-empty string")
        self.record_agent_trace = record_agent_trace
        self.record_video = record_video
        self.video_camera_keys = list(resolved_keys)
        self.video_fps = video_fps
        self.ffmpeg_path = ffmpeg_path
        self.session_dir: Path | None = None
        self.session_id: str | None = None
        self.agent_trace_path: Path | None = None
        self.video_writer: EpisodeVideoWriter | None = None
        self.errors: list[str] = []

    def start(self, session_dir: Path, session_id: str, task: Any) -> None:
        if self.session_dir is not None:
            raise RuntimeError("Episode recorder is already active")
        self.session_dir = session_dir
        self.session_id = session_id
        self.errors = []
        try:
            if self.record_agent_trace:
                self.agent_trace_path = session_dir / "agent_trace.jsonl"
                self.agent_trace_path.write_text("", encoding="utf-8")
                self._append(
                    {
                        "event": "episode_start",
                        "timestamp": self._timestamp(),
                        "session_id": session_id,
                        "task": to_jsonable(task),
                    }
                )
            if self.record_video:
                self.video_writer = EpisodeVideoWriter(
                    output_path=session_dir / "episode.mp4",
                    camera_keys=self.video_camera_keys,
                    fps=self.video_fps,
                    ffmpeg_path=self.ffmpeg_path,
                )
        except Exception:
            self._reset()
            raise

    def record_observation(
        self,
        observation: Any,
        *,
        step: int,
        labels: list[str] | None = None,
    ) -> None:
        if self.video_writer is None:
            return
        try:
            self.video_writer.add_frame(
                observation,
                labels or [f"step={step}", "episode observation"],
            )
        except Exception as error:
            self.errors.append(
                f"video frame step={step}: {type(error).__name__}: {error}"
            )

    def record_step(
        self,
        step: int,
        output: dict[str, Any],
        observation: Any,
    ) -> None:
        planner_output = output.get("planner_output")
        planner = planner_output if isinstance(planner_output, Mapping) else {}
        raw_response = planner.get("raw_response")
        backend = (
            raw_response.get("_backend") if isinstance(raw_response, Mapping) else None
        )
        verification = output.get("verification")
        environment_result = output.get("environment_result")
        environment = (
            environment_result if isinstance(environment_result, Mapping) else {}
        )
        skill = output.get("skill", planner.get("skill"))
        subtask = output.get("subtask", planner.get("subtask"))
        event = {
            "event": "agent_step",
            "timestamp": self._timestamp(),
            "session_id": self.session_id,
            "step": step,
            "planner": {
                "called": bool(
                    output.get("planner_called", "planner_output" in output)
                ),
                "replanned": bool(output.get("replanned", False)),
                "skill": skill,
                "skill_id": planner.get("skill_id"),
                "subtask": subtask,
                "reasoning": planner.get("reasoning"),
                "expected_outcome": planner.get("expected_outcome"),
                "backend": to_jsonable(backend),
            },
            "execution": {
                "execution_id": output.get("execution_id"),
                "attempt_id": output.get("attempt_id"),
                "previous_status": output.get("previous_status"),
                "next_status": output.get("next_status"),
                "transition_reason": output.get("transition_reason"),
                "recovery_action": output.get("recovery_action"),
            },
            "action": to_jsonable(output.get("action")),
            "verification": to_jsonable(verification),
            "environment": to_jsonable(
                {
                    key: environment.get(key)
                    for key in (
                        "task_success",
                        "task_progress",
                        "last_action_success",
                        "done",
                        "executed_steps",
                        "environment_steps",
                        "env_feedback",
                    )
                    if key in environment
                }
            ),
            "decision": output.get("decision"),
            "event_type": output.get("event_type"),
            "success": bool(output.get("success", False)),
            "termination_reason": output.get("termination_reason"),
        }
        self._append(event)
        reason = output.get("transition_reason")
        if reason is None and isinstance(verification, Mapping):
            reason = verification.get("reason") or verification.get("env_feedback")
        status = (
            output.get("next_status")
            or output.get("decision")
            or output.get("event_type")
        )
        self.record_observation(
            observation,
            step=step,
            labels=[
                f"step={step} skill={skill}",
                f"subtask={subtask}",
                f"status={status}",
                f"reason={reason or environment.get('env_feedback', '')}",
            ],
        )

    def record_exception(self, step: int, error: Exception) -> None:
        self._append(
            {
                "event": "exception",
                "timestamp": self._timestamp(),
                "session_id": self.session_id,
                "step": step,
                "error_type": type(error).__name__,
                "error": str(error),
            }
        )

    def finish(self, result: dict[str, Any]) -> dict[str, Any]:
        if self.session_dir is None or self.session_id is None:
            raise RuntimeError("Episode recorder is not active")
        try:
            return self._finish(result)
        finally:
            self._reset()

    def _finish(self, result: dict[str, Any]) -> dict[str, Any]:
        assert self.session_dir is not None
        assert self.session_id is not None
        video_result: dict[str, Any] = {"path": None, "frames": 0, "error": None}
        if self.video_writer is not None:
            try:
                video_result = self.video_writer.close()
            except Exception as error:
                video_result = {
                    "path": None,
                    "frames": self.video_writer.frame_count,
                    "error": f"{type(error).__name__}: {error}",
                }
            if video_result["error"]:
                self.errors.append(str(video_result["error"]))

        self._append(
            {
                "event": "episode_end",
                "timestamp": self._timestamp(),
                "session_id": self.session_id,
                "result": to_jsonable(
                    {
                        key: result.get(key)
                        for key in (
                            "success",
                            "task_progress",
                            "steps",
                            "invalid_actions",
                            "replans",
                            "planner_calls",
                            "action_chunks",
                            "environment_steps",
                            "latency_seconds",
                            "termination_reason",
                            "error_type",
                            "error",
                        )
                        if key in result
                    }
                ),
            }
        )

        manifest_path = self.session_dir / "artifact_manifest.json"
        manifest = {
            "schema_version": 1,
            "session_id": self.session_id,
            "artifacts": {
                "result": "result.json",
                "trace": "trace.jsonl",
                "agent_trace": (
                    self.agent_trace_path.name
                    if self.agent_trace_path is not None
                    else None
                ),
                "video": (
                    Path(video_result["path"]).name if video_result["path"] else None
                ),
                "artifacts_dir": (
                    "artifacts" if (self.session_dir / "artifacts").is_dir() else None
                ),
            },
            "video": {
                "frames": int(video_result["frames"]),
                "fps": self.video_fps if self.record_video else None,
                "camera_keys": self.video_camera_keys if self.record_video else [],
            },
            "errors": list(self.errors),
        }
        manifest_path.write_text(
            json.dumps(to_jsonable(manifest), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        artifacts: dict[str, Any] = {
            "artifact_manifest_path": str(manifest_path),
            "agent_trace_path": (
                str(self.agent_trace_path)
                if self.agent_trace_path is not None
                else None
            ),
            "video_path": (str(video_result["path"]) if video_result["path"] else None),
            "video_frames": int(video_result["frames"]),
        }
        if self.errors:
            artifacts["observability_errors"] = list(self.errors)
        return artifacts

    def _reset(self) -> None:
        self.session_dir = None
        self.session_id = None
        self.agent_trace_path = None
        self.video_writer = None
        self.errors = []

    def _append(self, event: dict[str, Any]) -> None:
        if self.agent_trace_path is None:
            return
        with self.agent_trace_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(to_jsonable(event), ensure_ascii=False) + "\n")

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(UTC).isoformat()
