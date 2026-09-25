"""Continuous simulation-frame recording; never used as planner input."""

from __future__ import annotations

import json
import subprocess
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


class DemoRecorder:
    def __init__(self, directory: str, fps: int = 20) -> None:
        directory_path = Path(directory)
        directory_path.mkdir(parents=True, exist_ok=True)
        self.path = directory_path / f"demo-{uuid.uuid4().hex[:12]}.mp4"
        self.fps = fps
        self.frames = 0
        self.process: subprocess.Popen | None = None
        self.actions: list[str] = []
        self.success = False
        try:
            self.font = ImageFont.truetype("DejaVuSans.ttf", 22)
            self.small_font = ImageFont.truetype("DejaVuSans.ttf", 17)
        except OSError:
            self.font = self.small_font = ImageFont.load_default()

    def add(self, png: bytes, action: str, status: str, success: bool) -> None:
        with Image.open(BytesIO(png)) as source:
            image = source.convert("RGB")
        canvas = Image.new("RGB", (image.width, image.height + 112), (15, 23, 36))
        canvas.paste(image, (0, 80))
        draw = ImageDraw.Draw(canvas)
        draw.text(
            (20, 12),
            "OmniRoboAgent | Chemistry Bench",
            font=self.font,
            fill=(225, 236, 247),
        )
        draw.text((20, 45), action, font=self.small_font, fill=(120, 204, 248))
        draw.text(
            (canvas.width - 220, 20),
            status,
            font=self.small_font,
            fill=(105, 233, 164) if success else (232, 234, 240),
        )
        draw.text(
            (20, canvas.height - 26),
            "Scripted motion | Symbolic chemistry | No fluid/contact simulation",
            font=self.small_font,
            fill=(175, 188, 205),
        )
        if self.process is None:
            self.process = subprocess.Popen(
                [
                    "ffmpeg",
                    "-loglevel",
                    "error",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-s",
                    f"{canvas.width}x{canvas.height}",
                    "-r",
                    str(self.fps),
                    "-i",
                    "pipe:0",
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    str(self.path),
                ],
                stdin=subprocess.PIPE,
            )
        assert self.process.stdin is not None
        self.process.stdin.write(canvas.tobytes())
        self.frames += 1
        self.success = success
        if not self.actions or self.actions[-1] != action:
            self.actions.append(action)

    def close(self) -> None:
        if self.process is None:
            return
        process, self.process = self.process, None
        assert process.stdin is not None
        process.stdin.close()
        try:
            code = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise RuntimeError("Demo encoder did not finish") from None
        if code:
            raise RuntimeError(f"Demo encoder failed with exit code {code}")
        self.path.with_suffix(".json").write_text(
            json.dumps(
                {
                    "video": self.path.name,
                    "fps": self.fps,
                    "frames": self.frames,
                    "duration_seconds": self.frames / self.fps,
                    "actions": self.actions,
                    "task_success": self.success,
                    "timing": "simulation time; model inference pauses omitted",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
