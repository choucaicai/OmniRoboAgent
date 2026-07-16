---
name: update-omniroboagent-user-docs
description: Update and audit OmniRoboAgent user-facing framework documentation under `docs/` and user-facing sections of the root `README.md`. Use when installation, configuration, public interfaces, examples, model or policy providers, benchmark usage, outputs, or troubleshooting change; when users ask to update or fix tutorials; or when docs are too specific to one maintainer's model, provider, serving stack, endpoint, path, environment, hardware, or checkpoint.
---

# Update OmniRoboAgent User Docs

Work from the OmniRoboAgent repository root.

## Workflow

1. Read `AGENTS.md` and `rules/README.md` completely before editing.
2. Inspect `docs/README.md`, `docs/_sidebar.md`, affected user documents, and the implementation, configuration, and tests that define current behavior.
3. Treat executable code, checked-in configuration, CLI help, and tests as the source of truth. Do not document planned behavior as available.
4. Identify the affected audience and task before editing: first-time users, model or benchmark users, or component authors. Ask the user only when the intended audience, support claim, or treatment of maintainer-specific examples would materially change the result.
5. Separate stable framework behavior, user-configurable values, provider-specific instructions, and verified maintainer examples. Lead with the stable workflow and choices.
6. Update only affected files under `docs/` and user-facing sections of `README.md`.
7. Keep commands runnable from the repository root. Preserve identifiers, config keys, class paths, actual defaults, and output filenames exactly.
8. Update `docs/README.md`, `docs/_sidebar.md`, and root `README.md` links when adding, removing, or renaming a page.
9. When public behavior or architecture also changed, invoke or follow `$update-omniroboagent-impl-docs` in the same task.
10. Add the required record under `impl_docs/changes/`. Update an existing relevant item in `impl_docs/TODO.md`; do not invent a task solely for documentation editing.

## Framework Documentation

- Organize guidance by user goal and required capability, not by the maintainer's current machine or preferred provider.
- Give first-time users a minimal path from installation to one successful command. Put benchmark-specific setup and advanced extension details in their own sections or pages.
- Describe model integration in three layers: the `LLMBackend` framework contract, built-in adapters and their protocol requirements, then optional provider examples.
- Present `OpenAICompatibleLLMBackend` as a provider-neutral protocol adapter, not as an integration for any single serving stack. A local server, hosted API, gateway, or other serving stack may use it when the required OpenAI-compatible endpoints and capabilities match; state the validation status of each concrete example.
- Document a custom `LLMBackend` selected through `class_path` as the extension path for providers or protocols not covered by a built-in adapter. Do not imply that the framework architecture is limited to OpenAI-compatible services.
- Do not make any model provider or serving stack a project-wide prerequisite, default, or primary documentation path unless the affected page is specifically about that integration.
- For configurable model IDs, endpoints, ports, checkpoint paths, Conda environments, GPU IDs, and dataset roots, explain what the value means and how users replace it.
- Use repository-relative commands and portable placeholders such as `<MODEL_ID>` or `<PROJECT_ROOT>` when a literal value is not required. Do not publish the maintainer's absolute paths as general instructions.
- When checked-in smoke configs contain concrete local values, link to them as examples, label their tested scope, and distinguish those values from framework defaults.
- Keep reproducibility evidence such as an exact tested model, checkpoint, endpoint, hardware setup, or result in a clearly labeled verified-example section. Do not let it replace the general workflow.
- State provider requirements in terms of protocol and capabilities. Do not claim native support from third-party compatibility claims alone, and mark compatible but unverified providers as unverified.
- Preserve concise, copy-pasteable paths for common tasks, with advanced alternatives discoverable without forcing every reader through them.

## Content Rules

- Write for users installing, configuring, running, extending, or debugging OmniRoboAgent.
- Prefer copy-pasteable commands and minimal complete examples.
- Separate prerequisites, commands, expected outputs, and limitations.
- Mark unimplemented or unverified behavior explicitly.
- Do not call an example value a default unless code or checked-in configuration makes it the default in that documented scope.
- Keep internal architecture decisions, implementation plans, and historical changes out of `docs/`.
- Preserve unrelated user edits and avoid broad rewrites.

## Verification

- Run commands or focused tests affected by the documentation when practical.
- Check local Markdown links in changed files.
- Search for stale renamed paths, config keys, class paths, and commands.
- Review every changed occurrence of provider or serving-stack names, maintainer-specific model names, loopback endpoints, absolute paths, environment names, checkpoint paths, and GPU IDs. Keep only values that are necessary and correctly labeled.
- Run `git diff --check`.
- Record exact commands, results, and unrun checks in `impl_docs/changes/`.
