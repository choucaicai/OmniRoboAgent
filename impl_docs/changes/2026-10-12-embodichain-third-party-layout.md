# Separate simulator SDK and consolidate module README

Move the existing pinned EmbodiChain submodule from `benchmarks/EmbodiChain` to
`third_party/EmbodiChain` using Git's submodule-aware move. Retain the official
URL, upstream commit `89c14da8d0221dc4ee2a4a3e0ba1078b16d447bd`, clean source tree,
and stable submodule identifier. RoboSynChallenge stays under `benchmarks/`;
`benchmarks/robosyn-runtime` remains our own isolated dependency configuration.

Update editable paths in pyproject/uv.lock, SDK default discovery from the supplied
benchmark root, its existing regression test, installation/CLI examples and
architecture tree. No action, reset protocol, checkpoint, physics or seed change.

Add a dedicated `RoboSynChallenge：为智能体提供标准化机器人仿真评测` README
chapter following SpatialMemory's structure. It consolidates purpose, closed-loop
flow, component ownership, directory layout, setup/weights/service requirements,
single-task/matrix/resume commands, historical scores and known limitations.
The main Clone section keeps only general checkout instructions. Clarify that
omitting AgentConfig selects a direct baseline only in single-task mode; the
matrix reads its visual AgentConfig from the manifest.

Validation: 38 focused tests; 183 full-suite tests passed / 1 optional skip; Ruff
lint/format (9 Python files) and mypy (7 sources) passed using explicit PR-worktree
imports. Offline `uv lock --check` resolves 281 packages; moved submodule HEAD and
clean status verified, and README CLI/path instructions checked against the code.
No GPU matrix was rerun; historical 412/1000 results and native GC limitation stand.

Preserve the user's existing commits and original evaluation workspace. Stage the
follow-up only; no automatic commit, push or PR mutation.
