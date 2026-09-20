# Add Procedural Memory And Label Injected Working Frames

Date: 2026-09-20
Related plan: `impl_docs/plans/0017-procedural-memory-and-labelled-frames.md`

## Changed

- Added `track_procedures`, `procedure_recall_limit`, `procedure_min_support` and `procedure_limit` to `ReflectiveMemory`, plus a third semantic partition `procedures` that `recall()` always returns. Until now memory's only reaction to a `task_success` was to cast a refutation vote against a lesson; the successful path itself was discarded with the episode.
- Induced each procedure from `state["completed_executions"]` at `task_success`. Every step reuses `_grounded_slots()` to produce a signature of the same shape as the attempt signature, so coordinates and other volatile numbers stay out and the same solution aligns across episodes.
- Keyed procedures by normalised task text plus the ordered step signatures. A repeat of the same solution increments `support_count` and appends to `session_ids`; a different step sequence is stored as a separate entry, because several working paths through one task are all facts.
- Ranked recall on content words taken from each step's skill name and object slot values rather than the raw instruction. Matching on instruction text made "put the mug on the tray" and "turn on the stove" overlap on `the` and `on`; a unit test caught this and the matching signal was changed rather than the test.
- Filtered out procedures with zero content-word overlap when the query carries a task, so an unrelated task's solution is treated as noise instead of weak evidence.
- Kept procedures across `reset()`, matching lessons and opposing `object_state`: a procedure describes how the task is solved, not what the current scene looks like.
- Returned an empty partition for `recall({"phase": "verify"})`, consistent with the other two `ReflectiveMemory` partitions.
- Added `agent_core/prompting.py::working_frame_content()`, which emits one line of `step/event/status` text before each frame's images, and switched `LanguageSkillPlanner`, `SubtaskSkillPlanner` and `SubtaskVerifier` to it. The per-frame `event_type`, `status` and `pinned` fields added by plan 0015 were previously computed and then dropped at the prompt boundary, so a model receiving several near-identical views could not tell which one was the failure. Image count and order are unchanged.
- Removed `LanguageSkillPlanner._memory_images`, now fully replaced by the shared renderer.
- Extended `LanguageSkillPlanner._memory_prompt` with a `procedures` block carrying only the single-line `text` of each entry, emitted only when the partition is non-empty.

## Files

- `src/omniroboagent/agent_core/prompting.py`
- `src/omniroboagent/agent_core/memories/reflective.py`
- `src/omniroboagent/agent_core/planners/language_skill.py`
- `src/omniroboagent/agent_core/planners/subtask_skill.py`
- `src/omniroboagent/agent_core/verifiers/subtask.py`
- `tests/unit/test_reflective_memory.py`
- `tests/unit/test_memory_prompting.py`
- `tests/unit/test_llm_and_planner.py`
- `docs/agent_core/memory.md`
- `docs/configuration.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/TODO.md`
- `impl_docs/README.md`
- `impl_docs/plans/0017-procedural-memory-and-labelled-frames.md`
- `impl_docs/changes/2026-09-20-procedural-memory-and-labelled-frames.md`

## Verification

- `PYTHONPATH=src python -m pytest -q`: passed, 163 tests (149 before this change, 14 added).
- Two pre-existing tests were edited: `test_reflective_memory_keeps_the_stable_recall_partitions`, which asserts the exact set of recall keys and now also expects `procedures`; and `test_language_skill_planner_uses_explicit_memory_context`, which now asserts the frame label precedes the frame image. No other existing assertion changed.
- `ruff check src tests` (ruff 0.16.8): passed.
- `ruff format --check` on the touched files: clean except `src/omniroboagent/agent_core/verifiers/subtask.py`, which was already failing before this change at four unrelated hunks. The lines edited here are correctly formatted and the pre-existing drift was deliberately left alone to avoid polluting the diff.
- `MYPYPATH=src mypy` (mypy 1.20.2, strict, Python 3.11): 62 source files checked, no error in any file touched by this change.

## Remaining Work

- `mypy` still reports the two pre-existing `no-any-return` errors at `src/omniroboagent/observability/video.py:171` and `:177`, from the Pillow stub version in the local tool environment. That file is untouched here.
- Checks were run in a local virtualenv, not in the `omniagent` Conda environment described in `README.md`, which does not exist on this machine.
- No benchmark run was performed. `track_procedures` is not enabled in any `configs/agents/*.yaml`, so no evaluation behaviour changed there.
- The frame labels, unlike the procedure partition, are **not** behind a flag and take effect for every existing planner and verifier config. Prompt content therefore changed for all runs. The added cost is a few text tokens per frame against thousands of image tokens, but this was reasoned about, not measured.
- `task_success` may be extremely rare in practice. The earlier audit recorded 1 success in 40 composite RoboCasa episodes, so the partition may stay empty or hold only single-support entries. Whether a one-off success is safe to surface is the experience-following risk documented in the plan and is unmeasured.
- Step signatures drop `expected_outcome`. Two paths with the same skill and object sequence but different goals collapse into one procedure.
- Procedures do not persist across processes. Lessons have `lesson_path` and `lesson_reload`; procedures accumulate only within one process, across episodes.
- Content-word matching assumes object slot values are meaningful nouns, which inherits the slot-whitelist question already recorded for the object state ledger.
