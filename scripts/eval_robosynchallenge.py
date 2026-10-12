"""Evaluate RoboSynChallenge policies through the OmniRoboAgent closed loop."""

import argparse
import hashlib
import sys
from pathlib import Path

from omniroboagent.agent_core import (
    DefaultAgent,
    EnvironmentVerifier,
    InMemoryMemory,
    TaskSkillPlanner,
)
from omniroboagent.backends.skills.robosyn import RoboSynPolicyBackend
from omniroboagent.config import build_agent, load_yaml
from omniroboagent.environments.benchmarks.robosynchallenge import (
    RoboSynChallengeEnvironment,
)
from omniroboagent.evals.benchmarks.robosynchallenge import RoboSynChallengeEvaluator
from omniroboagent.evals.benchmarks.robosynchallenge.matrix import run_matrix
from omniroboagent.observability import LocalEpisodeRecorder
from omniroboagent.pipelines import DirectPipeline, SkillExecutionPipeline
from omniroboagent.runtimes import SyncRuntime


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--robosyn-root", required=True, type=Path)
    parser.add_argument("--embodichain-root", type=Path)
    parser.add_argument("--task")
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--checkpoint-revision")
    parser.add_argument("--policy", choices=["act", "dp"], default="act")
    parser.add_argument("--setting", choices=["random", "clear"], default="random")
    parser.add_argument("--output", required=True, type=Path)
    seed_options = parser.add_mutually_exclusive_group()
    seed_options.add_argument("--seeds", nargs="+", type=int)
    seed_options.add_argument("--episodes", type=int, default=100)
    parser.add_argument("--start-seed", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--agent-config", type=Path)
    parser.add_argument("--matrix-manifest", type=Path)
    parser.add_argument("--matrix-gpus", nargs="+", type=int)
    parser.add_argument(
        "--matrix-scheduling", choices=["fixed", "dynamic"], default="fixed"
    )
    parser.add_argument("--pipeline", choices=["direct", "skill"])
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--environment-device", default="cpu")
    parser.add_argument("--gpu", type=int, default=0)
    parser.add_argument("--renderer", default="hybrid")
    parser.add_argument("--display", action="store_true")
    parser.add_argument("--reset-sync-steps", type=int, default=1)
    parser.add_argument("--dp-num-inference-steps", type=int, default=10)
    parser.add_argument("--max-steps", type=int, default=10000)
    parser.add_argument("--timeout-seconds", type=float, default=1800)
    parser.add_argument("--record-video", action="store_true")
    parser.add_argument("--video-fps", type=int, default=10)
    args = parser.parse_args()
    if args.matrix_manifest:
        command = [sys.executable, str(Path(__file__).resolve())]
        for key in (
            "robosyn_root",
            "embodichain_root",
            "agent_config",
            "pipeline",
            "device",
            "environment_device",
            "gpu",
            "renderer",
            "reset_sync_steps",
            "dp_num_inference_steps",
            "max_steps",
            "timeout_seconds",
            "video_fps",
        ):
            value = getattr(args, key)
            if value is not None:
                command.extend(["--" + key.replace("_", "-"), str(value)])
        for key in ("display", "record_video"):
            if getattr(args, key):
                command.append("--" + key.replace("_", "-"))
        summary = run_matrix(
            args.matrix_manifest,
            args.output.resolve(),
            command,
            resume=args.resume,
            matrix_gpus=args.matrix_gpus,
            matrix_scheduling=args.matrix_scheduling,
        )
    else:
        if not args.task or not args.checkpoint:
            parser.error("Single-task evaluation requires --task and --checkpoint")
        if args.episodes <= 0:
            parser.error("--episodes must be positive")
        seeds = (
            args.seeds
            if args.seeds is not None
            else list(range(args.start_seed, args.start_seed + args.episodes))
        )
        checkpoint = args.checkpoint.resolve()
        checkpoint_sha256 = {}
        for path in sorted(checkpoint.iterdir()):
            if path.is_file():
                with path.open("rb") as file:
                    checkpoint_sha256[path.name] = hashlib.file_digest(
                        file, "sha256"
                    ).hexdigest()
        if args.agent_config:
            config = load_yaml(args.agent_config)
            backend = config.get("skill_backend", {})
            if backend.get("class_path", "").endswith(".RoboSynPolicyBackend"):
                backend.setdefault("init_args", {}).update(
                    checkpoint_path=str(checkpoint),
                    policy_name=args.policy,
                    device=args.device,
                    dp_num_inference_steps=args.dp_num_inference_steps,
                )
            agent = build_agent(config)
        else:
            agent = DefaultAgent(
                planner=TaskSkillPlanner(),
                verifier=EnvironmentVerifier(),
                memory=InMemoryMemory(),
                skill_backend=RoboSynPolicyBackend(
                    checkpoint_path=str(checkpoint),
                    policy_name=args.policy,
                    device=args.device,
                    dp_num_inference_steps=args.dp_num_inference_steps,
                ),
            )
        environment = RoboSynChallengeEnvironment(
            robosyn_root=str(args.robosyn_root.resolve()),
            embodichain_root=(
                str(args.embodichain_root.resolve()) if args.embodichain_root else None
            ),
            setting=args.setting,
            device=args.environment_device,
            headless=not args.display,
            renderer=args.renderer,
            gpu_id=args.gpu,
            reset_sync_steps=args.reset_sync_steps,
        )
        pipeline_name = args.pipeline or ("skill" if args.agent_config else "direct")
        pipeline = (
            SkillExecutionPipeline() if pipeline_name == "skill" else DirectPipeline()
        )
        runtime = SyncRuntime(
            output_dir=args.output,
            max_steps=args.max_steps,
            timeout_seconds=args.timeout_seconds,
            observability=LocalEpisodeRecorder(
                record_video=args.record_video,
                video_camera_keys=["head_rgb"],
                video_fps=args.video_fps,
            ),
        )
        evaluator = RoboSynChallengeEvaluator(
            environment,
            args.output,
            args.task,
            seeds,
            setting=args.setting,
            resume=args.resume,
            run_metadata={
                "agent_mode": (
                    "configured_agent"
                    if args.agent_config
                    else "learned_policy_baseline"
                ),
                "policy": args.policy,
                "checkpoint_path": str(checkpoint),
                "checkpoint_revision": args.checkpoint_revision,
                "checkpoint_sha256": checkpoint_sha256,
                "policy_device": args.device,
                "agent_config_sha256": (
                    hashlib.sha256(args.agent_config.read_bytes()).hexdigest()
                    if args.agent_config
                    else None
                ),
                "runtime_max_steps": args.max_steps,
                "runtime_timeout_seconds": args.timeout_seconds,
                "record_video": args.record_video,
            },
        )
        try:
            summary = evaluator.run(agent, pipeline, runtime)
        finally:
            try:
                agent.close()
            finally:
                environment.close()
    if not summary["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
