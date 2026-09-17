"""Evaluate a schedule LoRA through the real Omni loop on replayed observations."""

from __future__ import annotations

import argparse
import base64
import datetime
import io
import json
import os
import random
import traceback
from pathlib import Path
from typing import Any

import torch

# flash-linear-attention detects its backend at import time.
if torch.cuda.is_available():
    torch.cuda.init()

# The training environment is Python 3.10; Omni itself targets Python 3.11+.
if not hasattr(datetime, "UTC"):
    datetime.UTC = datetime.timezone.utc  # type: ignore[attr-defined]  # noqa: UP017

from build_fixed_schedule_sft import CAMERAS, ReplayEnvironment, ReplayPolicy
from peft import PeftModel
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor

from omniroboagent.agent_core import (
    DefaultAgent,
    SubtaskPlanPlanner,
    SubtaskVerifier,
    TieredMemory,
)
from omniroboagent.backends.llm.base import LLMBackend
from omniroboagent.pipelines import SkillExecutionPipeline
from omniroboagent.runtimes import SyncRuntime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_MODEL = (
    Path(os.environ["QWEN35_BASE_MODEL"]) if "QWEN35_BASE_MODEL" in os.environ else None
)
DEFAULT_DATASET = (
    PROJECT_ROOT / "runs/data/omni_full_plan_select_schedule_sft_2486_20260913"
)
DEFAULT_ADAPTER = (
    PROJECT_ROOT / "runs/sft/qwen35_9b_omni_full_plan_select_3gpu_20260913/checkpoints/"
    "checkpoint-3500"
)
DEFAULT_CASES = ("place_mouse_pad:episode0017", "dump_bin_bigbin:episode0015")
IMAGE_MAX_PIXELS = 589824


class TransformersBackend(LLMBackend):
    """Run the Omni OpenAI-style request directly through Qwen3-VL and its LoRA."""

    def __init__(
        self,
        base_model: Path,
        adapter: Path,
        *,
        temperature: float,
        top_p: float,
        top_k: int,
        max_new_tokens: int,
        attn_implementation: str = "flash_attention_2",
    ) -> None:
        import fla.utils as fla_utils

        if torch.cuda.is_available():
            fla_utils.device = "cuda"
            fla_utils.device_name = "cuda"
            fla_utils.device_platform = "cuda"
            fla_utils.device_torch_lib = torch.cuda
            fla_utils.IS_NVIDIA = True
        self.processor = AutoProcessor.from_pretrained(
            base_model, trust_remote_code=True
        )
        self.processor.image_processor.max_pixels = IMAGE_MAX_PIXELS
        model = AutoModelForImageTextToText.from_pretrained(
            base_model,
            torch_dtype=torch.bfloat16,
            attn_implementation=attn_implementation,
            device_map={"": 0},
            trust_remote_code=True,
        )
        self.model = PeftModel.from_pretrained(
            model, adapter, is_trainable=False
        ).eval()
        self.device = next(self.model.parameters()).device
        if self.device.type != "cuda":
            raise RuntimeError(f"model loaded on unexpected device: {self.device}")
        self.generation = {
            "do_sample": True,
            "temperature": temperature,
            "top_p": top_p,
            "top_k": top_k,
            "max_new_tokens": max_new_tokens,
        }
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def _image(url: str) -> Image.Image:
        if url.startswith("data:image/"):
            try:
                _, encoded = url.split(",", 1)
                payload = base64.b64decode(encoded)
            except (ValueError, TypeError) as error:
                raise ValueError("Invalid image data URL") from error
            with Image.open(io.BytesIO(payload)) as source:
                return source.convert("RGB")
        path = Path(url)
        with Image.open(path) as source:
            return source.convert("RGB")

    @staticmethod
    def _messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        converted: list[dict[str, Any]] = []
        for message in messages:
            content = message["content"]
            if not isinstance(content, list):
                converted.append(
                    {
                        "role": message["role"],
                        "content": [{"type": "text", "text": str(content)}],
                    }
                )
                continue
            parts: list[dict[str, Any]] = []
            for index, item in enumerate(content):
                if index:
                    parts.append({"type": "text", "text": "\n"})
                if item["type"] == "image_url":
                    parts.append(
                        {
                            "type": "image",
                            "image": TransformersBackend._image(
                                item["image_url"]["url"]
                            ),
                        }
                    )
                else:
                    parts.append({"type": "text", "text": item["text"]})
            converted.append({"role": message["role"], "content": parts})
        return converted

    def complete(self, inputs: dict[str, Any]) -> dict[str, Any]:
        schema = inputs["response_format"]["json_schema"]["name"]
        call: dict[str, Any] = {"schema": schema}
        self.calls.append(call)
        try:
            messages = self._messages(inputs["messages"])
            batch = self.processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                enable_thinking=False,
                return_dict=True,
                return_tensors="pt",
            )
            system_text = "".join(
                part.get("text", "") for part in messages[0]["content"]
            )
            trailing_newlines = len(system_text) - len(system_text.rstrip("\n"))
            if trailing_newlines:
                end_id = self.processor.tokenizer.convert_tokens_to_ids("<|im_end|>")
                end_at = int((batch["input_ids"][0] == end_id).nonzero()[0])
                newline_ids = self.processor.tokenizer.encode(
                    "\n" * trailing_newlines, add_special_tokens=False
                )
                inserted = torch.tensor([newline_ids], dtype=batch["input_ids"].dtype)
                batch["input_ids"] = torch.cat(
                    (
                        batch["input_ids"][:, :end_at],
                        inserted,
                        batch["input_ids"][:, end_at:],
                    ),
                    dim=1,
                )
                batch["attention_mask"] = torch.cat(
                    (
                        batch["attention_mask"][:, :end_at],
                        torch.ones_like(inserted),
                        batch["attention_mask"][:, end_at:],
                    ),
                    dim=1,
                )
                if "mm_token_type_ids" in batch:
                    batch["mm_token_type_ids"] = torch.cat(
                        (
                            batch["mm_token_type_ids"][:, :end_at],
                            torch.zeros_like(inserted),
                            batch["mm_token_type_ids"][:, end_at:],
                        ),
                        dim=1,
                    )
            empty_think = self.processor.tokenizer.encode(
                "<think>\n\n</think>\n\n", add_special_tokens=False
            )
            suffix = torch.tensor(empty_think, dtype=batch["input_ids"].dtype)
            if torch.equal(batch["input_ids"][0, -len(empty_think) :], suffix):
                batch["input_ids"] = batch["input_ids"][:, : -len(empty_think)]
                batch["attention_mask"] = batch["attention_mask"][
                    :, : -len(empty_think)
                ]
                if "mm_token_type_ids" in batch:
                    batch["mm_token_type_ids"] = batch["mm_token_type_ids"][
                        :, : -len(empty_think)
                    ]
            batch = {
                key: value.to(self.device) if hasattr(value, "to") else value
                for key, value in batch.items()
            }
            generation = dict(self.generation)
            generation["max_new_tokens"] = min(
                generation["max_new_tokens"], int(inputs.get("max_tokens", 2048))
            )
            with torch.inference_mode():
                output_ids = self.model.generate(**batch, **generation)
            generated = output_ids[:, batch["input_ids"].shape[1] :]
            text = self.processor.batch_decode(
                generated,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            )[0].strip()
        except Exception as exc:
            call.update(
                error_type=type(exc).__name__,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            raise
        call["raw_output"] = text
        print(
            json.dumps(
                {"model_call": len(self.calls), "schema": schema, "output": text},
                ensure_ascii=False,
            ),
            flush=True,
        )
        return {"choices": [{"message": {"content": text}}]}

    def healthcheck(self) -> dict[str, Any]:
        return {"healthy": True, "backend": "transformers"}


class IndexedReplayPolicy(ReplayPolicy):
    """Keep scheduler fields in the replay action so transitions remain auditable."""

    def predict(self, inputs: dict[str, Any]) -> Any:
        return {
            "skill": inputs["skill"],
            "subtask": inputs["subtask"],
            "grounded_arguments": inputs["grounded_arguments"],
        }


class ScheduleReplayEnvironment(ReplayEnvironment):
    """Replay frames by schedule index while allowing harmless subtask paraphrases."""

    def execute(self, action: Any, execute_steps: int | None = None) -> dict[str, Any]:
        assert execute_steps is None
        if self.chunk == self.budgets[self.index]:
            self.index += 1
            self.chunk = 0
        segment = self.segments[self.index]
        actual_index = action.get("grounded_arguments", {}).get("subtask_index")
        assert actual_index == self.index, (
            f"planner selected subtask_index={actual_index}; expected {self.index}"
        )
        assert action["skill"] == segment["skill"], (
            f"planner selected skill={action['skill']!r}; expected {segment['skill']!r}"
        )
        self.chunk += 1
        frame = min(
            segment["frame_start"] + self.chunk * 32,
            segment["frame_end_exclusive"] - 1,
        )
        self.executions.append(
            {
                "subtask_index": self.index,
                "chunk": self.chunk,
                "chunk_budget": self.budgets[self.index],
                "before_frame": self.frame,
                "after_frame": frame,
                "skill": action["skill"],
                "expected_subtask": segment["subtask_instruction"],
                "actual_subtask": action["subtask"],
                "exact_subtask_match": (
                    action["subtask"] == segment["subtask_instruction"]
                ),
            }
        )
        return {
            "observation": self.observation(frame),
            "task_success": False,
            "done": False,
            "last_action_success": True,
            "executed_steps": 32,
            "env_feedback": "action_executed",
        }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open() as stream:
        return [json.loads(line) for line in stream if line.strip()]


def run_case(
    episode: dict[str, Any],
    dataset: Path,
    backend: TransformersBackend,
    output_dir: Path,
) -> dict[str, Any]:
    payload = json.loads(Path(episode["metadata_path"]).read_text())
    source_summary = json.loads((Path(dataset / "summary.json")).read_text())
    source_root = Path(source_summary["source"])
    source_catalog = json.loads((source_root / "summary.json").read_text())[
        "skill_catalog"
    ]
    skills = list(source_catalog.values())
    budgets = episode["task"]["chunk_budgets"]
    identity = episode["id"]
    env = ScheduleReplayEnvironment(
        payload,
        dataset
        / "images"
        / payload["task_name"]
        / f"episode{payload['episode_index']:04d}",
        skills,
        budgets=budgets,
        require_existing_images=True,
        trust_reused_images=True,
    )
    agent = DefaultAgent(
        planner=SubtaskPlanPlanner(
            backend=backend,
            camera_keys=list(CAMERAS),
            scheduled_chunks=True,
        ),
        verifier=SubtaskVerifier(
            backend=backend,
            camera_keys=list(CAMERAS),
            planned_chunk_schedule=True,
        ),
        memory=TieredMemory(camera_keys=list(CAMERAS), save_key_event_artifacts=False),
        skill_backend=IndexedReplayPolicy(),
    )
    task = dict(episode["task"])
    call_start = len(backend.calls)
    try:
        result = SyncRuntime(
            max_steps=sum(budgets) + 2,
            output_dir=output_dir / "traces",
        ).run(
            agent,
            SkillExecutionPipeline(max_chunks_per_skill=50),
            env,
            task,
            session_id=identity,
        )
        if result.get("termination_reason") == "exception":
            error = f"{result.get('error_type')}: {result.get('error')}"
        else:
            error = None
    except Exception as exc:  # Keep the exact failed call and partial trajectory.
        result = None
        error = f"{type(exc).__name__}: {exc}"
    finally:
        env.close()

    expected = [
        {"subtask_index": index, "chunks": budget}
        for index, budget in enumerate(budgets)
    ]
    expected_rows = [
        row
        for row in read_jsonl(dataset / "requests.jsonl")
        if row["id"].startswith(identity + ":")
    ]
    expected_outputs = [
        {
            "schema": row["request"]["response_format"]["json_schema"]["name"],
            "answer": row["answer"],
        }
        for row in expected_rows
    ]
    actual_outputs = []
    for call in backend.calls[call_start:]:
        try:
            parsed = json.loads(call["raw_output"])
        except (KeyError, TypeError, ValueError):
            parsed = None
        actual_outputs.append({"schema": call["schema"], "answer": parsed})
    output_checks = [
        {
            "call_index": index,
            "schema": expected_output["schema"],
            "exact": actual_output == expected_output,
            "expected": expected_output["answer"],
            "actual": actual_output["answer"],
        }
        for index, (expected_output, actual_output) in enumerate(
            zip(expected_outputs, actual_outputs, strict=False)
        )
    ]
    all_outputs_exact = len(actual_outputs) == len(expected_outputs) and all(
        check["exact"] for check in output_checks
    )
    plan_exact = bool(output_checks) and output_checks[0]["exact"]
    all_executed_subtasks_exact = all(
        record["exact_subtask_match"] for record in env.executions
    )
    actual = []
    for record in env.executions:
        if not actual or actual[-1]["subtask_index"] != record["subtask_index"]:
            actual.append({"subtask_index": record["subtask_index"], "chunks": 0})
        actual[-1]["chunks"] += 1
    passed = (
        error is None
        and plan_exact
        and all_outputs_exact
        and all_executed_subtasks_exact
        and actual == expected
        and result is not None
        and result.get("termination_reason") == "plan_exhausted"
        and result.get("action_chunks") == sum(budgets)
    )
    return {
        "id": identity,
        "schedule_id": episode["schedule_id"],
        "instruction": payload["instruction"],
        "expected_transitions": expected,
        "actual_transitions": actual,
        "plan_exact": plan_exact,
        "all_model_outputs_exact": all_outputs_exact,
        "all_executed_subtasks_exact": all_executed_subtasks_exact,
        "model_output_checks": output_checks,
        "passed": passed,
        "error": error,
        "runtime_result": result,
        "executions": env.executions,
        "model_calls": backend.calls[call_start:],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", type=Path, default=DEFAULT_BASE_MODEL)
    parser.add_argument("--adapter", type=Path, default=DEFAULT_ADAPTER)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cases", nargs="+", default=list(DEFAULT_CASES))
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--seed", type=int, default=20260913)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.base_model is None:
        raise ValueError("--base-model or QWEN35_BASE_MODEL is required")
    random.seed(args.seed)
    torch.manual_seed(args.seed)
    torch.cuda.manual_seed_all(args.seed)
    dataset = args.dataset.resolve()
    selected = {
        row["id"]: row
        for row in read_jsonl(dataset / "episodes.jsonl")
        if row["id"] in set(args.cases)
    }
    missing = sorted(set(args.cases) - set(selected))
    if missing:
        raise ValueError(f"Missing cases: {missing}")
    backend = TransformersBackend(
        args.base_model.resolve(),
        args.adapter.resolve(),
        temperature=args.temperature,
        top_p=args.top_p,
        top_k=args.top_k,
        max_new_tokens=args.max_new_tokens,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results = []
    for index, identity in enumerate(args.cases, start=1):
        result = run_case(selected[identity], dataset, backend, args.output.parent)
        results.append(result)
        print(
            json.dumps(
                {
                    "case": f"{index}/{len(args.cases)}",
                    "id": identity,
                    "passed": result["passed"],
                    "expected": result["expected_transitions"],
                    "actual": result["actual_transitions"],
                    "error": result["error"],
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        args.output.write_text(
            json.dumps({"results": results}, ensure_ascii=False, indent=2) + "\n"
        )
    report = {
        "base_model": str(args.base_model.resolve()),
        "adapter": str(args.adapter.resolve()),
        "dataset": str(dataset),
        "generation": backend.generation,
        "passed": sum(result["passed"] for result in results),
        "total": len(results),
        "results": results,
    }
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
