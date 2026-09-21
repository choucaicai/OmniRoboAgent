"""Validate a dedicated real worker; never starts or stops external services."""

import argparse
import importlib
import json
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat

from omniroboagent.agent_core import (
    DefaultAgent,
    EnvironmentVerifier,
    InMemoryMemory,
    Planner,
)
from omniroboagent.backends.skills import LanguageSkillBackend
from omniroboagent.config import build_agent, load_yaml
from omniroboagent.environments.benchmarks.chemistry_bench import (
    ChemistryBenchEnvironment,
)
from omniroboagent.observability import LocalEpisodeRecorder
from omniroboagent.pipelines import DirectPipeline
from omniroboagent.runtimes import SyncRuntime


class ScriptedPlanner(Planner):
    def __init__(self) -> None:
        self.actions = iter(
            [
                "pick naoh_bottle",
                "pour 30 ml into beaker",
                "pour 30 ml into beaker",
                "place bottle on table",
                "record finding: beaker is pink",
            ]
        )

    def plan(self, inputs: dict[str, Any]) -> dict[str, Any]:
        return {"skill": next(self.actions)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:50051")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--agent-config", type=Path)
    parser.add_argument("--base-url")
    parser.add_argument("--episodes", type=int, default=2)
    parser.add_argument("--rpc-timeout", type=float, default=600)
    args = parser.parse_args()
    if args.episodes < 1:
        parser.error("episodes must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    task = load_yaml("configs/runs/chemistry_bench_titration.yaml")["task"]
    results = []
    for index in range(args.episodes):
        env = ChemistryBenchEnvironment(
            address=args.address, timeout_seconds=args.rpc_timeout
        )
        try:
            initial = env.reset(task)
            # Diagnostic only: raw truth never enters the agent, its trace or memory.
            grpc = importlib.import_module("grpc")
            pb = importlib.import_module("chemistry_bench_proto.embodiment_pb2")
            services = importlib.import_module(
                "chemistry_bench_proto.embodiment_pb2_grpc"
            )
            with grpc.insecure_channel(
                args.address, options=(("grpc.enable_http_proxy", 0),)
            ) as channel:
                stub = services.SimBackendStub(channel)
                version = stub.Health(pb.Empty(), timeout=10).version
                message = stub.Observe(pb.Empty(), timeout=120)
            if len(message.proprio.joint_positions) < 7:
                raise RuntimeError(
                    "Robot joint state missing; robot smoke not verified"
                )
            truth = json.loads(message.privileged_json)
            if truth["findings"] or truth["vessels"]["beaker"]["volume_ml"] != 50:
                raise RuntimeError("Episode did not reset to initial chemistry")
            with Image.open(BytesIO(initial["head_rgb"])) as image:
                if max(ImageStat.Stat(image.convert("RGB")).stddev) < 5:
                    raise RuntimeError("Camera is blank or placeholder")
                image.save(args.output / f"initial-{index}.png")
            if args.agent_config:
                config = load_yaml(args.agent_config)
                if args.base_url:
                    config["planner"]["init_args"]["backend"]["init_args"][
                        "base_url"
                    ] = args.base_url
                agent = build_agent(config)
            else:
                agent = DefaultAgent(
                    planner=ScriptedPlanner(),
                    verifier=EnvironmentVerifier(),
                    memory=InMemoryMemory(),
                    skill_backend=LanguageSkillBackend(),
                )
            result = SyncRuntime(
                output_dir=args.output,
                max_steps=30,
                timeout_seconds=1800,
                observability=LocalEpisodeRecorder(
                    record_video=True, video_camera_keys=["head_rgb"]
                ),
            ).run(agent, DirectPipeline(), env, task)
            results.append(
                {
                    "worker_version": version,
                    "mode": "model" if args.agent_config else "scripted",
                    "robot_joints": len(message.proprio.joint_positions),
                    "reset_verified": True,
                    "result": result,
                }
            )
            print(
                json.dumps(
                    {
                        "episode": index,
                        "success": result["success"],
                        "steps": result["steps"],
                    }
                ),
                flush=True,
            )
            if not result["success"]:
                break
        finally:
            env.close()
    # Runtime owns detailed traces and video; this file contains only summary data.
    from omniroboagent.serialization import to_jsonable

    (args.output / "smoke_summary.json").write_text(
        json.dumps(to_jsonable(results), indent=2), encoding="utf-8"
    )
    if len(results) != args.episodes or not all(
        r["result"]["success"] for r in results
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
