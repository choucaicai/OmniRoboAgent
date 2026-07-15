import argparse
import importlib
import inspect
import subprocess
import sys
from pathlib import Path
from typing import Any


def load_object(class_path: str) -> Any:
    module_name, name = class_path.rsplit(".", 1)
    return getattr(importlib.import_module(module_name), name)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a RoboCasa GR00T policy")
    parser.add_argument("--groot-root", type=Path, required=True)
    parser.add_argument("--model-path", required=True)
    parser.add_argument(
        "--policy-class-path",
        default="gr00t.model_moe_v1.policy.Gr00tPolicy",
    )
    parser.add_argument(
        "--data-config-module",
        default="gr00t.experiment.data_config_mem_groot",
    )
    parser.add_argument("--data-config", default="panda_omron")
    parser.add_argument("--embodiment-tag", default="new_embodiment")
    parser.add_argument("--denoising-steps", type=int, default=4)
    parser.add_argument("--memory-queue-size", type=int, default=0)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--api-token", default=None)
    args = parser.parse_args()

    groot_root_path = args.groot_root.expanduser().resolve()
    groot_root = str(groot_root_path)
    if groot_root in sys.path:
        sys.path.remove(groot_root)
    sys.path.insert(0, groot_root)

    config_module = importlib.import_module(args.data_config_module)
    config = config_module.DATA_CONFIG_MAP[args.data_config]
    policy_class = load_object(args.policy_class_path)
    server_class = load_object("gr00t.eval.robot.RobotInferenceServer")
    policy = policy_class(
        model_path=args.model_path,
        modality_config=config.modality_config(),
        modality_transform=config.transform(),
        embodiment_tag=args.embodiment_tag,
        denoising_steps=args.denoising_steps,
        device=args.device,
        memory_queue_size=args.memory_queue_size,
    )
    try:
        groot_commit = subprocess.run(
            ["git", "-C", groot_root, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        groot_dirty = bool(
            subprocess.run(
                ["git", "-C", groot_root, "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        groot_commit = None
        groot_dirty = None
    server = server_class(
        policy,
        host=args.host,
        port=args.port,
        api_token=args.api_token,
    )
    policy_reset = getattr(policy, "reset_episode_memory", None)

    def reset_episode_memory() -> dict[str, Any]:
        result = policy_reset() if callable(policy_reset) else None
        return result if isinstance(result, dict) else {"status": "ok"}

    server.register_endpoint(
        "reset_episode_memory",
        reset_episode_memory,
        requires_input=False,
    )
    server.register_endpoint(
        "metadata",
        lambda: {
            "protocol": "groot-zmq-torch",
            "model_path": args.model_path,
            "policy_class_path": args.policy_class_path,
            "data_config": args.data_config,
            "embodiment_tag": args.embodiment_tag,
            "action_horizon": len(config.modality_config()["action"].delta_indices),
            "groot_root": groot_root,
            "groot_commit": groot_commit,
            "groot_dirty": groot_dirty,
            "policy_module_file": inspect.getfile(policy_class),
            "data_config_module_file": inspect.getfile(config_module),
        },
        requires_input=False,
    )
    server.run()


if __name__ == "__main__":
    main()
