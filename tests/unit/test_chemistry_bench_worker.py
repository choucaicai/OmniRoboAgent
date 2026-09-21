import ast
import importlib
import json
import shutil
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

WORKER_SOURCE = (
    Path(__file__).resolve().parents[2] / "benchmarks/chemistry-bench-sim/src"
)


def test_worker_source_remains_python310_compatible():
    for path in WORKER_SOURCE.rglob("*.py"):
        ast.parse(path.read_text(), filename=str(path), feature_version=(3, 10))


def test_standalone_chemistry_titration(monkeypatch):
    monkeypatch.syspath_prepend(str(WORKER_SOURCE))
    chemistry = importlib.import_module("chemistry_bench_chemistry")
    bottle = chemistry.Vessel(
        name="naoh_bottle", volume_ml=100, solute="NaOH", concentration=0.1
    )
    beaker = chemistry.Vessel(
        name="beaker",
        volume_ml=50,
        solute="HCl",
        concentration=0.1,
        indicator="phenolphthalein",
    )
    assert chemistry.color_of(beaker) != "pink"
    chemistry.mix(beaker, bottle, 30)
    assert chemistry.color_of(beaker) != "pink"
    chemistry.mix(beaker, bottle, 30)
    assert chemistry.color_of(beaker) == "pink"
    assert bottle.volume_ml == 40 and beaker.volume_ml == 110


def test_continuous_demo_recording(monkeypatch, tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is optional")
    monkeypatch.syspath_prepend(str(WORKER_SOURCE))
    recorder_type = importlib.import_module(
        "chemistry_bench_sim.recording"
    ).DemoRecorder
    recorder = recorder_type(str(tmp_path))
    png = BytesIO()
    Image.new("RGB", (640, 360), "gray").save(png, format="PNG")
    for index in range(6):
        recorder.add(
            png.getvalue(), "pick" if index < 3 else "place", "DONE", index == 5
        )
    recorder.close()
    recorder.close()
    metadata = json.loads(recorder.path.with_suffix(".json").read_text())
    assert recorder.path.stat().st_size > 0
    assert metadata["frames"] == 6
    assert metadata["actions"] == ["pick", "place"]
    assert metadata["task_success"] is True
