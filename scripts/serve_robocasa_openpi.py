import argparse
import subprocess
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve a RoboCasa OpenPI policy")
    parser.add_argument("--openpi-root", type=Path, required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--default-prompt", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    openpi_root_path = args.openpi_root.expanduser().resolve()
    openpi_root = str(openpi_root_path)
    source_root = str((args.openpi_root / "src").expanduser().resolve())
    for path in (source_root, openpi_root):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)

    from openpi.policies import policy_config
    from openpi.serving.websocket_policy_server import WebsocketPolicyServer
    from openpi.training import config

    policy = policy_config.create_trained_policy(
        config.get_config(args.config),
        args.checkpoint,
        default_prompt=args.default_prompt,
    )
    try:
        openpi_commit = subprocess.run(
            ["git", "-C", openpi_root, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        openpi_dirty = bool(
            subprocess.run(
                ["git", "-C", openpi_root, "status", "--porcelain"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        )
    except (OSError, subprocess.CalledProcessError):
        openpi_commit = None
        openpi_dirty = None
    metadata = {
        **policy.metadata,
        "protocol": "openpi-websocket-msgpack",
        "config": args.config,
        "checkpoint": args.checkpoint,
        "openpi_root": openpi_root,
        "openpi_commit": openpi_commit,
        "openpi_dirty": openpi_dirty,
    }
    WebsocketPolicyServer(
        policy=policy,
        host=args.host,
        port=args.port,
        metadata=metadata,
    ).serve_forever()


if __name__ == "__main__":
    main()
