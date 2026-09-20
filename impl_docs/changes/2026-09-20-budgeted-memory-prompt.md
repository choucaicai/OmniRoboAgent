# De-duplicate And Budget The Memory Prompt

Date: 2026-09-20
Related plan: `impl_docs/plans/0018-budgeted-memory-prompt.md`

## Changed

- Added `agent_core/prompting.py::memory_text_payload()`, which renders a recalled memory context into a compact, de-duplicated, character-budgeted payload, plus `DEFAULT_MEMORY_CHAR_BUDGET = 4096`, `EVENT_RENDER_LIMIT = 10` and `MEMORY_PARTITION_PRIORITY`.
- Stopped re-sending key events that `summary` already contains. `summary` is built by concatenating the same `text_summary` strings, so the records were pure duplication. A covered event now contributes only its `evidence_summary`, which is the one field `summary` drops; a covered event with no evidence is omitted entirely.
- Compared coverage against the untrimmed `summary`. `summary` is trimmed oldest-first while this renders the newest events, so the events checked are the ones whose summary lines survive.
- Compressed `recent_events` into one `step/event/status/reason` line each, dropping `artifact_refs`, `timestamp` and `session_id`, which do not inform the next decision.
- Filled partitions in decision-value order: `object_state` → `lessons` → `procedures` → `key_events` → `recent_events` → `summary`. `summary` is deliberately last because it is the most duplicative block; an earlier revision of this change put it fourth and it consumed 2907 of the 4096 budget, leaving `key_events` and `recent_events` with nothing.
- Reported truncation under a `dropped` key rather than silently shortening: `"name[oldest N]"` for partial loss, `"name"` when a partition does not fit at all.
- Added `memory_char_budget` (default 4096, must be positive) to `LanguageSkillPlanner`, `SubtaskSkillPlanner` and `SubtaskVerifier`. The budget belongs to the injection site, not to Memory: Memory decides what is remembered, the caller decides how much of it is sent.
- Converted `LanguageSkillPlanner._memory_prompt` from a `@staticmethod` to an instance method so it can read the configured budget, and removed the per-partition assembly it used to do inline.
- Removed `SubtaskVerifier`'s own memory rendering, which covered only `summary`, `recent_events` and `key_events` and therefore never saw the `lessons`, `object_state` or `procedures` partitions added since plan 0014.
- Measured in characters rather than tokens. The core dependency set is `httpx`, `Pillow` and `PyYAML`; adding a tokenizer to count tokens would break that boundary, and character count is a stable upper bound.
- No `Memory` implementation was modified. `recall()` returns exactly what it returned before.

## Files

- `src/omniroboagent/agent_core/prompting.py`
- `src/omniroboagent/agent_core/planners/language_skill.py`
- `src/omniroboagent/agent_core/planners/subtask_skill.py`
- `src/omniroboagent/agent_core/verifiers/subtask.py`
- `tests/unit/test_memory_prompting.py`
- `tests/unit/test_llm_and_planner.py`
- `tests/unit/test_subtask_verifier.py`
- `docs/agent_core/memory.md`
- `docs/configuration.md`
- `impl_docs/architecture/overview.md`
- `impl_docs/TODO.md`
- `impl_docs/README.md`
- `impl_docs/plans/0018-budgeted-memory-prompt.md`
- `impl_docs/changes/2026-09-20-budgeted-memory-prompt.md`

## Measurement

A throwaway script fed 30 synthetic transitions through `ReflectiveMemory(track_object_state=True, track_procedures=True)` and rendered the same recalled context both ways.

Before, by partition:

| Partition | Chars | Share |
| --- | --- | --- |
| `key_events` | 7774 | 42.1% |
| `recent_events` | 5294 | 28.7% |
| `summary` | 4104 | 22.2% |
| `lessons` | 627 | 3.4% |
| `object_state` | 595 | 3.2% |
| total | 18473 | |

All 10 of the rendered key events had their `text_summary` appear verbatim inside `summary`.

After de-duplication alone, with no budget applied: 7490 chars, 59.5% smaller. `key_events` 7774 → 1024, `recent_events` 5294 → 1166; `summary`, `lessons` and `object_state` unchanged.

After the default 4096-char budget: 4115 chars, 77.7% smaller than before. The distilled partitions (`object_state`, `lessons`, `procedures`) went from 6.6% of the payload to 27%. `summary` was trimmed and the payload reported `dropped: ["summary[oldest 20]"]`.

These are offline character counts on synthetic data. No rollout was run and no effect on decision quality was measured.

## Verification

- `PYTHONPATH=src python -m pytest -q`: passed, 175 tests (163 before this change, 12 added).
- Two pre-existing tests were extended rather than changed: `test_subtask_verifier_calls_vlm_with_before_after_images` and `test_language_skill_planner_uses_explicit_memory_context` still assert the same strings reach the prompt and both still pass unmodified.
- `ruff check src tests` (ruff 0.16.8): passed.
- `ruff format --check` on the touched files: clean except `src/omniroboagent/agent_core/verifiers/subtask.py` and `tests/unit/test_subtask_verifier.py`, both of which were already failing before this change at hunks unrelated to it. The lines edited here are correctly formatted and the pre-existing drift was deliberately left alone to avoid polluting the diff.
- `MYPYPATH=src mypy` (mypy 1.20.2, strict, Python 3.11): 62 source files checked, no error in any file touched by this change.
- `git diff --check`: clean.

## Remaining Work

- `mypy` still reports the two pre-existing `no-any-return` errors at `src/omniroboagent/observability/video.py:171` and `:177`, from the Pillow stub version in the local tool environment. That file is untouched here.
- Checks were run in a local virtualenv, not in the `omniagent` Conda environment described in `README.md`, which does not exist on this machine.
- The default budget of 4096 characters is uncalibrated. The earlier audit put planner prompts at 22k–24k tokens; 4096 characters is roughly 1k–1.5k tokens, chosen as a conservative starting point and not measured against success rate.
- **This change is not behind a flag.** Every existing planner and verifier config now sends a different memory payload. The payload is a strict subset of the old one in information terms — nothing is dropped except text that `summary` already carried verbatim — but the JSON shape the model sees did change, and no rollout has confirmed that models read the compacted form as well as the old one.
- Coverage is decided by `text in summary` substring matching. That is exact today because both strings come from the same code path, but a future summariser that paraphrases would silently make every key event look uncovered, falling back to the old verbose behaviour.
- Budget accounting uses `json.dumps` length, so quoting and escaping are counted. Relative ordering is unaffected; absolute figures run slightly above plain text length.
- There is no per-partition floor. Under a very small budget only the priority order protects the distilled partitions; nothing guarantees `summary` keeps a minimum slice.
- `EVENT_RENDER_LIMIT` is a module constant, not a configuration field, matching the hard-coded `[-10:]` it replaces.
