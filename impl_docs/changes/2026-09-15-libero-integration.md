# LIBERO environment, pi0.5 backend, and evaluator

Date: 2026-09-15
Related plan: `impl_docs/plans/0019-libero-integration.md`

## Changed

Added a LIBERO benchmark vertical slice without adding benchmark branches to the
core Runtime, Pipeline, Planner, or Verifier. The environment reuses ClawVLA's
official LIBERO adapter, exposes two image paths and the 8D robot state, validates
source-observation-bound 7D relative action chunks, and preserves
`env.check_success()` as the authoritative task result.

Added a resident local pi0.5 SkillBackend that sends the active Omni subtask as the
policy prompt. Added an evaluator for official task suites and fixed initial states,
per-task and macro success metrics, atomic episode records, resolved metadata, and
an executable one-episode configuration. Atomic execution uses the complete
instruction as one subtask. The existing `SubtaskPlanPlanner` can be substituted for
LIBERO-Long without changing environment or policy interfaces; no unsupported frame
boundaries were introduced.

The host's OpenPI SentencePiece vocabulary was converted into a local
Transformers-readable tokenizer directory because direct Hub access to the gated
PaliGemma repository returned HTTP 403. The conversion preserves the 257,152-token
vocabulary. Real Torch compilation uses `/usr/bin/gcc-12` because the host's default
GCC returns exit code 255 for Triton builds.

## Files

- `src/omniroboagent/environments/benchmarks/libero/`
- `src/omniroboagent/backends/skills/pi05_libero.py`
- `src/omniroboagent/evals/benchmarks/libero/`
- `configs/agents/libero_pi05_atomic.yaml`
- `configs/runs/libero_spatial_pi05_smoke.yaml`
- `tests/unit/test_libero_integration.py`
- `docs/libero.md`

## Verification

- `PYTHONPATH=src pytest -q`: 152 passed and 1 skipped.
- `PYTHONPATH=src pytest -q tests/unit/test_libero_integration.py tests/unit/test_robotwin_subtask.py`: 21 passed.
- Scoped Ruff lint and format checks: passed.
- Scoped strict mypy check over all five new source files: passed.
- Installed LIBERO SDK resolved all four suites, 10 tasks per suite and 50 official fixed initial states per task.
- Real `libero_spatial[0]` reset returned agent-view and wrist images plus finite 8D state.
- A local pi0.5 checkpoint loaded through `LIBERO_PI05_BASE_CHECKPOINT`, emitted a `50 x 7` action chunk, and the simulator executed the first five actions successfully. This checks integration, not task success.

## Remaining Work

Run the four complete suites with a frozen evaluation manifest. For learned
LIBERO-Long decomposition, derive and review subtask boundaries from official
demonstrations before creating planner or subtask-level VLA training data.
