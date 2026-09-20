import argparse
import json
from pathlib import Path
from typing import Any

from omniroboagent.config import (
    build_agent,
    build_run_components,
    instantiate,
    load_yaml,
    resolve_config_path,
)
from omniroboagent.serialization import to_jsonable


def main() -> None:
    parser = argparse.ArgumentParser(prog="omniroboagent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run one task or benchmark")
    run_parser.add_argument("--config", required=True, type=Path)

    health_parser = subparsers.add_parser("health", help="Check configured backends")
    health_parser.add_argument("--agent-config", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "health":
        agent = build_agent(load_yaml(args.agent_config))
        try:
            result = agent.healthcheck()
        finally:
            agent.close()
        print(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2))
        raise SystemExit(0 if result.get("healthy") else 1)

    result = run_config(args.config)
    print(json.dumps(to_jsonable(result), ensure_ascii=False, indent=2))


def run_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path)
    config = load_yaml(config_path)
    if "agent_config" not in config:
        raise ValueError("Run config requires agent_config")
    agent_path = resolve_config_path(config["agent_config"], config_path)
    agent = build_agent(load_yaml(agent_path))
    pipeline, runtime, environment = build_run_components(config)

    if "benchmark" in config:
        benchmark = instantiate(config["benchmark"], environment=environment)
        if environment is None:
            raise ValueError("Benchmark run requires environment")
        result = benchmark.run(agent, pipeline, runtime)
        if not isinstance(result, dict):
            raise TypeError("Benchmark run() must return a dict")
        return result
    if environment is None:
        raise ValueError("Run config requires environment")
    if "task" not in config:
        raise ValueError("Single run requires task")
    return runtime.run(agent, pipeline, environment, config["task"])

