# Add Reflective Memory With Evidence-Gated Lessons

Date: 2026-09-20
Related plan: `impl_docs/plans/0014-reflective-memory.md`

## Changed

- Added `ReflectiveMemory`, a `TieredMemory` subclass that distils repeated failures into evidence-gated lessons and exposes them as an additional `lessons` partition in `recall()`.
- Added a deterministic attempt signature built from the skill and the string-valued slots of `grounded_arguments`, ignoring volatile numeric grounding such as coordinates, so semantically equivalent repeated attempts aggregate onto one lesson.
- Added a deterministic failure classifier driven by `environment_result["control_failure"]` and a fixed verifier-reason keyword table, with an explicit `unclassified` fallback. No LLM call and no visual reasoning inside Memory.
- Added the lesson lifecycle: `add` and `upvote` on `subtask_failed` or `execution_aborted`, `refute` on a later `subtask_completed` with the same signature, plus `promote`, `demote`, `retire` and `evict` status transitions. Lessons are retired and versioned through a `revision` counter, never deleted in place.
- Gated lesson recall on evidence: a lesson stays `candidate` and is withheld from `recall()` until `support_count - refutation_count` reaches `lesson_min_support`.
- Gated lesson recall on phase: `recall({"phase": "verify"})` returns an empty `lessons` list so the Verifier is not primed by prior failures, using a query key the pipeline already passes but no Memory previously read.
- Ranked recalled lessons by lexical overlap with the task, then by net evidence, then by recency, and capped the injected count at `lesson_recall_limit` (default 3).
- Bounded the lesson store at `lesson_limit` with deterministic eviction of the weakest retired or low-evidence entries.
- Added an optional `lesson_path` JSONL audit log recording every lifecycle operation with full lesson provenance, routed through `to_jsonable`.
- Extended `LanguageSkillPlanner._memory_prompt` to append a `lessons` block containing only `lesson_id` and the single-line factual `text`, and only when the partition is non-empty, so `TieredMemory` prompts are unchanged.
- Exported `ReflectiveMemory` from `omniroboagent.agent_core.memories` and `omniroboagent.agent_core`.
- Documented the new implementation in the Memory guide, the configuration guide and the architecture overview.

## Files

- `src/omniroboagent/agent_core/memories/reflective.py`
- `src/omniroboagent/agent_core/memories/__init__.py`
- `src/omniroboagent/agent_core/__init__.py`
- `src/omniroboagent/agent_core/planners/language_skill.py`
- `tests/unit/test_reflective_memory.py`
- `docs/agent_core/memory.md`
- `docs/configuration.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/TODO.md`
- `impl_docs/plans/0014-reflective-memory.md`
- `impl_docs/changes/2026-09-20-reflective-memory.md`

## Verification

- `PYTHONPATH=src python -m pytest -q`: passed, 136 tests (124 before this change, 12 added).
- `PYTHONPATH=src python -m pytest tests/unit/test_reflective_memory.py -q`: passed, 12 tests.
- `ruff check src tests` (ruff 0.16.8): passed.
- `ruff format` applied to `src/omniroboagent/agent_core/memories/reflective.py` and `tests/unit/test_reflective_memory.py`; `ruff format --check` on all files touched by this change: passed.
- `MYPYPATH=src mypy` (mypy 1.20.2, strict, Python 3.11): 61 source files checked, no error in any file touched by this change.

## Remaining Work

- `mypy` still reports two pre-existing `no-any-return` errors at `src/omniroboagent/observability/video.py:171` and `:177`. That file is untouched by this change; the errors come from the Pillow stub version in the local tool environment, not from this work. They were not fixed here to keep the change scoped.
- Checks were run with the repository's declared tool version ranges but in a local virtualenv, not in the `omniagent` Conda environment described in `README.md`, which does not exist on this machine. The `omniagent` environment was therefore not used and `uv` was not involved.
- No benchmark run was performed. `ReflectiveMemory` is not wired into any `configs/agents/*.yaml`; the existing RoboCasa and EB-ALFRED configs still use their previous Memory, so no evaluation behaviour changed. The `TieredMemory` versus `ReflectiveMemory` comparison recorded in `impl_docs/TODO.md` section 5.1 is still open.
- Cross-episode lesson loading from a previous run's `lesson_path` is not implemented; lessons only persist within one process lifetime.
- The failure-class keyword table is a minimal hand-written set. It has not been validated against a corpus of real RoboCasa verifier reasons, so the `unclassified` rate in practice is unknown.
