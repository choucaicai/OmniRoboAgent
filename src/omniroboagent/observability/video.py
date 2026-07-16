import io
import subprocess
import textwrap
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


class EpisodeVideoWriter:
    def __init__(
        self,
        output_path: Path,
        camera_keys: list[str],
        fps: int,
        ffmpeg_path: str,
    ) -> None:
        self.output_path = output_path
        self.camera_keys = camera_keys
        self.fps = fps
        self.ffmpeg_path = ffmpeg_path
        self.frame_count = 0
        self.process: Any = None
        self.frame_size: tuple[int, int] | None = None

    def add_frame(self, observation: Any, labels: list[str]) -> None:
        frame = self._compose_frame(observation, labels)
        if frame is None:
            return
        if self.process is None:
            self._start(frame.size)
        elif self.frame_size is not None and frame.size != self.frame_size:
            frame = frame.resize(self.frame_size, Image.Resampling.LANCZOS)
        if self.process.stdin is None:
            raise RuntimeError("FFmpeg video stdin is unavailable")
        try:
            self.process.stdin.write(frame.tobytes())
        except BrokenPipeError as error:
            message = self._stderr()
            raise RuntimeError(f"FFmpeg video encoding failed: {message}") from error
        self.frame_count += 1

    def close(self) -> dict[str, Any]:
        if self.process is None:
            return {
                "path": None,
                "frames": 0,
                "error": "no configured camera frames were found",
            }
        if self.process.stdin is not None:
            self.process.stdin.close()
        return_code = self.process.wait()
        error = self._stderr()
        if return_code != 0:
            self.output_path.unlink(missing_ok=True)
            return {
                "path": None,
                "frames": self.frame_count,
                "error": f"FFmpeg exited with code {return_code}: {error}",
            }
        return {
            "path": self.output_path,
            "frames": self.frame_count,
            "error": None,
        }

    def _start(self, frame_size: tuple[int, int]) -> None:
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.frame_size = frame_size
        width, height = frame_size
        command = [
            self.ffmpeg_path,
            "-loglevel",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pixel_format",
            "rgb24",
            "-video_size",
            f"{width}x{height}",
            "-framerate",
            str(self.fps),
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(self.output_path),
        ]
        try:
            self.process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
        except OSError as error:
            raise RuntimeError(
                f"Failed to start FFmpeg executable {self.ffmpeg_path!r}: {error}"
            ) from error

    def _compose_frame(self, observation: Any, labels: list[str]) -> Image.Image | None:
        if not isinstance(observation, Mapping):
            return None
        images: list[Image.Image] = []
        for key in self.camera_keys:
            value = observation.get(key)
            if isinstance(value, list):
                value = value[-1] if value else None
            image = self._to_image(value)
            if image is not None:
                images.append(image.convert("RGB"))
        if not images:
            return None

        target_height = max(image.height for image in images)
        resized = [
            image.resize(
                (
                    max(1, round(image.width * target_height / image.height)),
                    target_height,
                ),
                Image.Resampling.LANCZOS,
            )
            if image.height != target_height
            else image
            for image in images
        ]
        width = sum(image.width for image in resized)
        banner_height = 84
        canvas = Image.new("RGB", (width, target_height + banner_height), "black")
        offset = 0
        for image in resized:
            canvas.paste(image, (offset, banner_height))
            offset += image.width

        draw = ImageDraw.Draw(canvas)
        line_width = max(40, width // 8)
        lines: list[str] = []
        for label in labels[:4]:
            ascii_label = str(label).encode("ascii", "replace").decode("ascii")
            lines.extend(textwrap.wrap(ascii_label, width=line_width) or [""])
        draw.multiline_text((8, 6), "\n".join(lines[:4]), fill="white", spacing=3)

        even_width = canvas.width + canvas.width % 2
        even_height = canvas.height + canvas.height % 2
        if (even_width, even_height) != canvas.size:
            padded = Image.new("RGB", (even_width, even_height), "black")
            padded.paste(canvas, (0, 0))
            canvas = padded
        return canvas

    @staticmethod
    def _to_image(value: Any) -> Image.Image | None:
        if value is None:
            return None
        if isinstance(value, Image.Image):
            return value.copy()
        if isinstance(value, (bytes, bytearray)):
            with Image.open(io.BytesIO(bytes(value))) as image:
                return image.copy()
        if isinstance(value, (str, Path)):
            path = Path(value)
            if not path.is_file():
                return None
            with Image.open(path) as image:
                return image.copy()
        try:
            return Image.fromarray(value)
        except Exception:
            return None

    def _stderr(self) -> str:
        if self.process is None or self.process.stderr is None:
            return ""
        value = self.process.stderr.read()
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace").strip()
        return str(value).strip()
