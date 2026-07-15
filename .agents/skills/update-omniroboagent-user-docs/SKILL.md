---
name: update-omniroboagent-user-docs
description: Update OmniRoboAgent user-facing documentation in `tutorial_docs/` and user-facing sections of the root `README.md`. Use when commands, installation, configuration, public interfaces, examples, benchmark usage, outputs, or troubleshooting change, or when the user asks to update, audit, or fix OmniRoboAgent user docs.
---

# Update OmniRoboAgent User Docs

Work from the OmniRoboAgent repository root.

## Workflow

1. Read `AGENTS.md` and `rules/README.md` completely before editing.
2. Inspect `tutorial_docs/README.md`, affected user documents, and the implementation, configuration, and tests that define current behavior.
3. Treat executable code, checked-in configuration, CLI help, and tests as the source of truth. Do not document planned behavior as available.
4. Update only affected files under `tutorial_docs/` and user-facing sections of `README.md`.
5. Keep commands runnable from the repository root. Preserve identifiers, paths, config keys, class paths, defaults, and output filenames exactly.
6. Update navigation links when adding, removing, or renaming a page.
7. When public behavior or architecture also changed, invoke or follow `$update-omniroboagent-impl-docs` in the same task.
8. Add the required record under `impl_docs/changes/`. Update an existing relevant item in `impl_docs/TODO.md`; do not invent a task solely for documentation editing.

## Content Rules

- Write for users installing, configuring, running, extending, or debugging OmniRoboAgent.
- Prefer copy-pasteable commands and minimal complete examples.
- Separate prerequisites, commands, expected outputs, and limitations.
- Mark unimplemented or unverified behavior explicitly.
- Keep internal architecture decisions, implementation plans, and historical changes out of `tutorial_docs/`.
- Preserve unrelated user edits and avoid broad rewrites.

## Verification

- Run commands or focused tests affected by the documentation when practical.
- Check local Markdown links in changed files.
- Search for stale renamed paths, config keys, class paths, and commands.
- Run `git diff --check`.
- Record exact commands, results, and unrun checks in `impl_docs/changes/`.
