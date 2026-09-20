# Add A Confirmed Object State Ledger To Reflective Memory

Date: 2026-09-20
Related plan: `impl_docs/plans/0016-confirmed-object-state-ledger.md`

## Changed

- Added `track_object_state` and `object_state_limit` to `ReflectiveMemory`, and a second semantic partition `object_state` that `recall()` always returns. The partition holds one entry per object, keyed by the string-valued grounding slots of the subtask that confirmed it.
- Extracted `_grounded_slots()` out of `_attempt_signature()` so the signature and the ledger share one deterministic slot extraction. `_attempt_signature()` produces byte-identical output to before, so all existing lesson behaviour is unchanged.
- Recorded a ledger entry for every string slot value on `subtask_completed`, using `expected_outcome` as the confirmed statement and falling back to `subtask`. When neither is present no entry is written, so Memory never invents a fact.
- Superseded rather than overwrote: a later confirmation about the same object increments `revision` and records the previous `confirmed_step` in `superseded_step`, matching the versioning discipline already used for lessons.
- Marked disturbance instead of invalidating: a later `subtask_failed` or `execution_aborted` involving an object sets `disturbed_step` on its existing entry but leaves `state` and `confirmed_step` intact, because a failed attempt confirms nothing about the world yet may have physically moved what was confirmed.
- Overrode `reset()` to clear the ledger while keeping lessons and key events. World state is scene-scoped and the environment is re-randomised per episode; lessons describe the agent's own competence and are deliberately carried across episodes.
- Gated the partition on phase: `recall({"phase": "verify"})` returns an empty `object_state`, so the Verifier judges the current observation without a prior about what the scene is supposed to look like.
- Bounded the ledger at `object_state_limit` (default 12), evicting the least recently confirmed object.
- Extended `LanguageSkillPlanner._memory_prompt` with an `object_state` block carrying only the single-line `text` of each entry, emitted only when the partition is non-empty.

## Files

- `src/omniroboagent/agent_core/memories/reflective.py`
- `src/omniroboagent/agent_core/planners/language_skill.py`
- `tests/unit/test_reflective_memory.py`
- `docs/agent_core/memory.md`
- `docs/configuration.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/TODO.md`
- `impl_docs/README.md`
- `impl_docs/plans/0016-confirmed-object-state-ledger.md`
- `impl_docs/changes/2026-09-20-object-state-ledger.md`

## Verification

- `PYTHONPATH=src python -m pytest -q`: passed, 149 tests (141 before this change, 8 added).
- The only pre-existing test that needed editing was `test_reflective_memory_keeps_the_stable_recall_partitions`, which asserts the exact set of recall keys and now also expects `object_state`. No other existing assertion changed, confirming the `_grounded_slots()` extraction did not alter signature behaviour.
- `ruff check src tests` (ruff 0.16.8): passed.
- `ruff format` on the three touched source and test files: no change needed.
- `MYPYPATH=src mypy` (mypy 1.20.2, strict, Python 3.11): 61 source files checked, no error in any file touched by this change.

## Remaining Work

- `mypy` still reports the two pre-existing `no-any-return` errors at `src/omniroboagent/observability/video.py:171` and `:177`, from the Pillow stub version in the local tool environment. That file is untouched here.
- Checks were run in a local virtualenv, not in the `omniagent` Conda environment described in `README.md`, which does not exist on this machine.
- No benchmark run was performed. `track_object_state` is not enabled in any `configs/agents/*.yaml`, so no evaluation behaviour changed. Whether the ledger actually reduces redundant subtask proposals is unmeasured; the claim rests on unit tests plus the partial-observability argument.
- Indexing by slot value assumes every string grounding argument is an object reference. A skill passing a non-object string (for example `direction=left`) will produce a meaningless entry. No slot whitelist exists and the real distribution of skill arguments has not been surveyed.
- Moving an object between receptacles leaves the old receptacle's entry pointing at the stale statement. Only `confirmed_step` lets the Planner tell which is current; no cross-entry consistency propagation is implemented.
- `disturbed_step` only annotates; it never expires an entry. Whether a disturbed fact should eventually be dropped needs real rollout data.
- This partition overlaps in intent with `breezexian`'s `spatial_memory` branch. Both add world or spatial state under `agent_core/memories/`; ownership needs to be settled before either is merged to master.
