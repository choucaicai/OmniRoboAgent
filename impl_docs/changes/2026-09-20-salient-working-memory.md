# Add Salience-Gated Working Memory And Cross-Run Lesson Persistence

Date: 2026-09-20
Related plan: `impl_docs/plans/0015-salient-working-memory-and-lesson-persistence.md`

## Changed

- Added `frame_selection` to `TieredMemory`, accepting `recent` (default, unchanged sliding window) or `event`. The window capacity stays `visual_window_size` under both, so the image token cost of a planner prompt is identical and only the choice of frames differs.
- Added `TieredMemory._is_salient()`, which marks a frame as a boundary when the transition produced a key event or when the verifier status differs from the previous frame in the window. The judgement uses only structured fields the Pipeline already emits; Memory performs no pixel comparison and calls no model.
- Added `TieredMemory._admit_frame()`, which lets consecutive steady-state frames share the last window slot while boundary frames take a slot of their own. The newest observation is always present, but it no longer evicts an earlier failure frame just by being new.
- Moved `event_type` extraction and validation, and `status` extraction, to the start of `TieredMemory.update()` so the admission policy can read them. An invalid `event_type` now raises before any frame is recorded instead of after.
- Added `event_type`, `status` and `pinned` to each working frame record so the retained window is auditable. The four existing recall partitions keep their keys and semantics.
- Forwarded `frame_selection` through `ReflectiveMemory`, keeping it orthogonal to the lesson mechanism so the two can be ablated independently.
- Added `lesson_reload` to `ReflectiveMemory`. When enabled it replays the `lesson_path` audit log at construction time and rebuilds the lesson partition, making the accumulation survive across processes. It requires `lesson_path` and raises otherwise.
- Rebuilt lessons take the last record per `lesson_id`, honour `evict` records as deletions, skip unparsable lines and lines missing evidence counts, re-resolve `status` against the currently configured `lesson_min_support`, and continue the `lesson_id` sequence so new lessons cannot collide with restored ones.
- Added `carried_over` to the lesson schema, `true` for restored lessons and `false` for lessons created in the current run.

## Files

- `src/omniroboagent/agent_core/memories/tiered.py`
- `src/omniroboagent/agent_core/memories/reflective.py`
- `tests/unit/test_tiered_memory.py`
- `tests/unit/test_reflective_memory.py`
- `docs/agent_core/memory.md`
- `docs/configuration.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/TODO.md`
- `impl_docs/README.md`
- `impl_docs/plans/0015-salient-working-memory-and-lesson-persistence.md`
- `impl_docs/changes/2026-09-20-salient-working-memory.md`

## Verification

- `PYTHONPATH=src python -m pytest -q`: passed, 141 tests (136 before this change, 5 added).
- The 136 pre-existing tests passed unchanged before any new test was added, confirming that `frame_selection` defaults to behaviour-preserving.
- `ruff check src tests` (ruff 0.16.8): passed.
- `ruff format --check` on the four touched source and test files: passed.
- `MYPYPATH=src mypy` (mypy 1.20.2, strict, Python 3.11): 61 source files checked, no error in any file touched by this change.

## Remaining Work

- `mypy` still reports the two pre-existing `no-any-return` errors at `src/omniroboagent/observability/video.py:171` and `:177`. That file is untouched here; the errors come from the Pillow stub version in the local tool environment.
- Checks were run in a local virtualenv, not in the `omniagent` Conda environment described in `README.md`, which does not exist on this machine.
- No benchmark run was performed. Neither `frame_selection: event` nor `lesson_reload` is wired into any `configs/agents/*.yaml`, so no evaluation behaviour changed. The share of boundary frames in a real RoboCasa rollout is therefore unmeasured, and the claim that `event` retains more useful frames rests on unit tests plus the chunked-execution argument, not on measured success rate.
- Cross-run lesson reuse does not distinguish tasks. Pointing several tasks at one `lesson_path` will mix unrelated lessons; only the lexical ranking and the recall cap of 3 limit the damage.
- The audit log is read in full at construction time and has no rotation. Lesson count is bounded by `lesson_limit` but log length is not.
- Working frames are still passed to the Planner as plain image content with no per-frame label, so the Planner cannot currently tell a boundary frame from the current frame. Adding that labelling was deliberately left out of this change.
