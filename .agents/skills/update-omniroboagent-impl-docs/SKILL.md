---
name: update-omniroboagent-impl-docs
description: Update OmniRoboAgent implementation documentation under `impl_docs/`, including architecture, TODO status, implementation plans, references, and change records. Use when code structure, dependency direction, contracts, runtime behavior, implementation status, plans, or repository rules change, or when the user asks to update, audit, or fix OmniRoboAgent implementation docs.
---

# Update OmniRoboAgent Implementation Docs

Work from the OmniRoboAgent repository root.

## Workflow

1. Read `AGENTS.md`, `rules/README.md`, `impl_docs/README.md`, and affected implementation documents completely before editing.
2. Inspect relevant source, configuration, tests, and Git diff. Document current verified behavior, not intent inferred from names.
3. Update the smallest applicable surfaces:
   - `impl_docs/architecture/` for current contracts, ownership, dependency direction, and system behavior.
   - `impl_docs/plans/` for scoped future or in-progress work, acceptance criteria, and status.
   - `impl_docs/TODO.md` for project-level status of existing work.
   - `impl_docs/reference/` for durable technical analysis that does not describe public usage.
   - `impl_docs/changes/` for completed modifications and actual verification.
4. Keep plan, TODO, architecture status, and change record consistent. Do not mark work `DONE` until implementation and required verification are complete.
5. When commands, configuration, public APIs, examples, outputs, or troubleshooting also changed, invoke or follow `$update-omniroboagent-user-docs` in the same task.

## Change Records

Create `impl_docs/changes/YYYY-MM-DD-short-name.md` with exactly these sections:

```text
# Title

Date: YYYY-MM-DD
Related plan: path or N/A

## Changed
## Files
## Verification
## Remaining Work
```

State actual commands and results. Explicitly list checks that were not run and why.

## Content Rules

- Preserve the dependency direction defined in `impl_docs/architecture/overview.md`.
- Use repository-relative paths and valid local Markdown links.
- Distinguish current behavior, planned work, and historical changes.
- Update existing plans and TODO entries instead of creating duplicate status sources.
- Keep runnable usage guidance in `tutorial_docs/`.
- Preserve unrelated user edits and avoid retrospective rewrites unless required for correctness.

## Verification

- Compare claims against relevant source, configuration, tests, and the current Git diff.
- Check local Markdown links and search for stale names or paths.
- Run focused tests or static checks appropriate to the documented change.
- Run `git diff --check`.
