# Document Repository-Wide Project Overview

Date: 2026-08-30
Related plan: N/A

## Changed

- Added a source-verified overview of the framework, benchmark paths, two standalone real-robot workspaces, dependency environments, validation status, risks, and recommended work order.
- Clarified that `RobotWorkspace/` and `RobotWorkspace_nav/` are colocated deployments rather than implemented OmniRoboAgent integrations.
- Updated the implementation documentation index to include repository-wide technical analysis.
- Linked the overview from the root documentation index.

## Files

- `impl_docs/reference/project-overview-2026-08-30.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/README.md`
- `README.md`
- `impl_docs/changes/2026-08-30-project-overview.md`

## Verification

- `PYTHONPATH=src uv run --isolated --no-project --with pytest --with httpx --with Pillow --with PyYAML --with numpy python -m pytest -q`: passed, 124 tests.
- `uv run --isolated --no-project --with ruff ruff check src tests`: passed.
- `uv run --isolated --no-project --with ruff ruff format --check src tests`: failed because four pre-existing source/test files require formatting.
- `MYPYPATH=src uv run --isolated --no-project --with mypy --with types-PyYAML --with httpx --with Pillow --with PyYAML --with numpy mypy --strict src/omniroboagent`: passed, 60 source files.
- `PYTHONPATH=src uv run --isolated --no-project --with httpx --with Pillow --with PyYAML python -m omniroboagent --help`: passed.
- `uv run --isolated --no-project python -m compileall -q RobotWorkspace_nav/robot RobotWorkspace_nav/server/streamvln RobotWorkspace/local RobotWorkspace/src/application/robot_bringup/scripts`: passed.
- `uv run --project . --group dev ...` and `uv lock --check`: failed because the uninitialized `benchmarks/EmbodiedBench` submodule has no local package metadata.
- Checked local Markdown links in changed files.
- `git diff --check`: passed.

External model services, benchmark simulators, CUDA inference, ROS2, and physical robots were not run because their submodules, dependencies, checkpoints, hardware, and safety environment are unavailable on this macOS host.

## Remaining Work

- Resolve the P0 security, robot safety, and licensing items in the overview before release or hardware deployment.
- Restore the default `uv` workflow when benchmark submodules are not initialized, then add CI.
- Consolidate and test the LatentPilot robot clients before implementing an OmniRoboAgent adapter.
