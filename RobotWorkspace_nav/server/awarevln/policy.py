"""AwareVLN model adapter for real-world image-by-image inference."""

from __future__ import annotations

import os
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image

from .action_parser import (
    ACTION_STOP,
    ParsedAwareVLNOutput,
    parse_awarevln_output,
)

DEFAULT_REASON_TOKEN = "<BEGIN_OF_REASONING>"
DEFAULT_ACTION_TOKEN = "<BEGIN_OF_ACTION>"


@dataclass
class AwareVLNSession:
    instruction: str
    frames: deque[Image.Image] = field(default_factory=deque)
    frame_step: int = 0
    last_reasoning: str = ""
    last_reason_step: int = 0


@dataclass(frozen=True)
class AwareVLNPrediction:
    actions: tuple[int, ...]
    raw_output: str
    reasoning: tuple[str, ...]
    terminal: bool
    mode: str


class AwareVLNPolicy:
    """Load the official AwareVLN package and run its reason-act loop."""

    def __init__(
        self,
        *,
        awarevln_root: str | Path,
        model_path: str | Path,
        device: str = "cuda:0",
        max_new_tokens: int = 256,
        max_reasoning_turns: int = 4,
        max_history_frames: int = 128,
    ) -> None:
        if max_new_tokens <= 0:
            raise ValueError("max_new_tokens must be positive")
        if max_reasoning_turns <= 0:
            raise ValueError("max_reasoning_turns must be positive")
        if max_history_frames <= 0:
            raise ValueError("max_history_frames must be positive")

        self.awarevln_root = Path(awarevln_root).expanduser().resolve()
        self.model_path = Path(model_path).expanduser().resolve()
        self.device = device
        self.max_new_tokens = max_new_tokens
        self.max_reasoning_turns = max_reasoning_turns
        self.max_history_frames = max_history_frames

        if not (self.awarevln_root / "llava" / "model" / "builder.py").is_file():
            raise FileNotFoundError(
                "AwareVLN source tree is missing llava/model/builder.py: "
                f"{self.awarevln_root}"
            )
        if not (self.model_path / "config.json").is_file():
            raise FileNotFoundError(
                f"AwareVLN checkpoint is missing config.json: {self.model_path}"
            )

        self._load_official_model()

    def _load_official_model(self) -> None:
        sys.path.insert(0, str(self.awarevln_root))

        import llava
        import torch
        from llava.constants import IMAGE_TOKEN_INDEX
        from llava.conversation import SeparatorStyle, conv_templates
        from llava.mm_utils import (
            KeywordsStoppingCriteria,
            process_images,
            tokenizer_image_token,
        )
        from llava.model.builder import load_pretrained_model

        llava_path = Path(llava.__file__).resolve()
        if self.awarevln_root not in llava_path.parents:
            raise RuntimeError(
                "Imported llava does not belong to the requested AwareVLN repository: "
                f"{llava_path}. Start the service with start_awarevln_server.sh."
            )
        if self.device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(f"CUDA device requested but unavailable: {self.device}")

        model_name = os.path.basename(os.path.normpath(self.model_path))
        tokenizer, model, image_processor, _ = load_pretrained_model(
            str(self.model_path),
            model_name,
            device=self.device,
        )
        if image_processor is None:
            raise RuntimeError("AwareVLN checkpoint did not load an image processor")

        reason_token = (
            getattr(
                model.config,
                "reason_token",
                DEFAULT_REASON_TOKEN,
            )
            or DEFAULT_REASON_TOKEN
        )
        action_token = (
            getattr(
                model.config,
                "act_token",
                DEFAULT_ACTION_TOKEN,
            )
            or DEFAULT_ACTION_TOKEN
        )
        reason_token_id = tokenizer.convert_tokens_to_ids(reason_token)
        action_token_id = tokenizer.convert_tokens_to_ids(action_token)
        unknown_token_id = getattr(tokenizer, "unk_token_id", None)
        invalid_ids = {None, -1, unknown_token_id}
        if reason_token_id in invalid_ids or action_token_id in invalid_ids:
            raise ValueError(
                "AwareVLN tokenizer is missing reasoning/action special tokens; "
                "load the tokenizer saved with the official checkpoint"
            )
        model.config.reason_token_id = reason_token_id
        model.config.act_token_id = action_token_id
        model.eval()

        num_video_frames = int(getattr(model.config, "num_video_frames", 8))
        if num_video_frames <= 0:
            raise ValueError(
                "model.config.num_video_frames must be positive, "
                f"got {num_video_frames}"
            )

        self._torch = torch
        self._image_token_index = IMAGE_TOKEN_INDEX
        self._separator_style = SeparatorStyle
        self._conv_templates = conv_templates
        self._stopping_criteria_class = KeywordsStoppingCriteria
        self._process_images = process_images
        self._tokenizer_image_token = tokenizer_image_token
        self.tokenizer = tokenizer
        self.model = model
        self.image_processor = image_processor
        self.reason_token = reason_token
        self.action_token = action_token
        self.num_video_frames = num_video_frames

    def new_session(self, instruction: str) -> AwareVLNSession:
        instruction = instruction.strip()
        if not instruction:
            raise ValueError("instruction must not be empty")
        return AwareVLNSession(
            instruction=instruction,
            frames=deque(maxlen=self.max_history_frames),
        )

    def _sample_and_pad_frames(self, frames: list[Image.Image]) -> list[Image.Image]:
        if not frames:
            raise ValueError("At least one frame is required")

        frames = [frame.convert("RGB") for frame in frames]
        while len(frames) < self.num_video_frames:
            width, height = frames[-1].size
            frames.insert(0, Image.new("RGB", (width, height), color=(0, 0, 0)))

        if self.num_video_frames == 1:
            return [frames[-1]]
        if len(frames) == self.num_video_frames:
            return frames

        historical_count = self.num_video_frames - 1
        sample_span = len(frames) - 1
        sampled_indices = [
            int(index * sample_span / historical_count)
            for index in range(historical_count)
        ]
        return [frames[index] for index in sampled_indices] + [frames[-1]]

    def _build_question(
        self,
        session: AwareVLNSession,
        frame_count: int,
    ) -> str:
        historical_images = "<image>\n" * (frame_count - 1)
        prefix = (
            "Imagine you are a robot programmed for navigation tasks. "
            "You have been given a video of historical observations "
            f"{historical_images}, "
            "and current observation <image>\n. "
            f'Your assigned task is: "{session.instruction}". '
        )
        if session.last_reasoning:
            related_step = session.frame_step - session.last_reason_step
            prefix += (
                f"The reasoning from {related_step} steps ago was: "
                f'"{session.last_reasoning}". '
            )
        return (
            prefix
            + "Analyze this series of images to decide whether to predict the next "
            "action or to perform reasoning. If action prediction, decide your next "
            "action, which could be turning left or right by a specific degree, "
            "moving forward a certain distance, or stop if the task is completed. "
            "If reasoning, describe your current observations, assess task progress, "
            "and provide a high-level plan for the next steps."
        )

    def _generate_once(
        self,
        session: AwareVLNSession,
        image: Image.Image,
    ) -> str:
        frames = self._sample_and_pad_frames([*session.frames, image])
        question = self._build_question(session, len(frames))

        conversation = self._conv_templates["llama_3"].copy()
        conversation.append_message(conversation.roles[0], question)
        conversation.append_message(conversation.roles[1], None)
        prompt = conversation.get_prompt()

        images_tensor = self._process_images(
            frames,
            self.image_processor,
            self.model.config,
        ).to(self.device, dtype=self._torch.float16)
        input_ids = (
            self._tokenizer_image_token(
                prompt,
                self.tokenizer,
                self._image_token_index,
                return_tensors="pt",
            )
            .unsqueeze(0)
            .to(self.device)
        )
        stop_text = (
            conversation.sep
            if conversation.sep_style != self._separator_style.TWO
            else conversation.sep2
        )
        stopping_criteria = self._stopping_criteria_class(
            [stop_text],
            self.tokenizer,
            input_ids,
        )

        with self._torch.inference_mode():
            output_ids = self.model.generate(
                input_ids,
                images=images_tensor,
                do_sample=False,
                temperature=0.0,
                max_new_tokens=self.max_new_tokens,
                use_cache=True,
                stopping_criteria=[stopping_criteria],
                pad_token_id=self.tokenizer.eos_token_id,
            )

        output = self.tokenizer.batch_decode(
            output_ids,
            skip_special_tokens=False,
        )[0].strip()
        for separator in (stop_text, conversation.sep2):
            if separator and output.endswith(separator):
                output = output[: -len(separator)].strip()
        return output

    def predict(
        self,
        session: AwareVLNSession,
        image: Image.Image,
    ) -> AwareVLNPrediction:
        image = image.convert("RGB")
        reasoning_outputs: list[str] = []
        raw_output = ""

        for _ in range(self.max_reasoning_turns):
            raw_output = self._generate_once(session, image)
            parsed: ParsedAwareVLNOutput = parse_awarevln_output(raw_output)
            if parsed.mode == "act":
                session.frames.append(image.copy())
                session.frame_step += max(1, len(parsed.actions))
                return AwareVLNPrediction(
                    actions=parsed.actions,
                    raw_output=raw_output,
                    reasoning=tuple(reasoning_outputs),
                    terminal=parsed.actions == (ACTION_STOP,),
                    mode="act",
                )

            session.last_reasoning = parsed.content
            session.last_reason_step = session.frame_step
            reasoning_outputs.append(parsed.content)

        session.frames.append(image.copy())
        return AwareVLNPrediction(
            actions=(ACTION_STOP,),
            raw_output=raw_output,
            reasoning=tuple(reasoning_outputs),
            terminal=True,
            mode="reasoning_limit",
        )

    def health(self) -> dict[str, Any]:
        return {
            "status": "ok",
            "model": self.model_path.name,
            "device": self.device,
            "num_video_frames": self.num_video_frames,
        }
