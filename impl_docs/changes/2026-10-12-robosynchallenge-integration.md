# RoboSynChallenge integration and clean PR preparation

Add optional native Environment, local ACT/DP SkillBackend, seeded evaluator and
per-task multi-GPU matrix runner. Record full seed lists, authoritative success,
reset-state protocol, checkpoint/config/source identity and episode artifacts.
Strict resume rejects changed configuration and skips completed valid seeds;
dynamic scheduling retains previously assigned GPUs. Simulator dependencies are
isolated in `benchmarks/robosyn-runtime` with a committed uv lock.

The historical Qwen3.5-9B + ACT run completed ten official tasks, random setting,
explicit seeds 0–99 each: 412 successes / 1000 episodes (41.2%). All valid results
and artifacts were audited. One task's native garbage-collection exit SIGSEGV
occurred after all its episodes were persisted; original diagnostics remain in
the evaluation workspace. Cached strict resume exited 0 without rerunning valid
seeds or modifying result/trace/video bytes. This does not repair native GC or
reproduce organizer expert-feasibility-filtered scores. DP has unit validation,
not a full real matrix result.

The clean PR worktree starts at upstream master
`c01a6bdc615f4e886f1fd67b60e0d51cdd626e0e`, which already contains the chemistry
demo. Only this benchmark's files and narrowly scoped shared documentation are
carried over. No weights, upstream clones, caches, logs or videos are included.
The original workspace remains unchanged. No commit or push is performed.

Validation on the latest upstream base passed with explicit `PYTHONPATH=src`
and a verified import path pointing at the PR worktree: 37 focused tests,
182 full-suite tests passed / 1 optional skip, Ruff lint/format (9 Python files)
and mypy (7 sources) passed; staged diff check passed.
At the initial transfer, all 13 source/config/test/runtime files were byte-identical
to the evaluation workspace; the subsequent submodule layout changes are recorded
separately in `2026-10-12-robosynchallenge-submodules.md`.
Original checkout permission noise was normalized to the
upstream Git modes before staging; no unrelated source content changed.
The 1000-episode score belongs to the earlier evaluation workspace, not to a new
rollout on this PR worktree. Intended changes are staged; commit, fork push and
PR publication remain user actions.
