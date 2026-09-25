# Chemistry bench integration naming

Status: DONE

## Goal

Expose the author's reused chemistry simulation as `chemistry_bench` inside this
project, including the standalone worker and protocol.

## Confirmed Decisions

The user clarified ownership of the implementation and requested neutral naming.
Remove the newly added cross-project branding and provenance discussion; retain
third-party dependency notices and accurate validation limits.

## Open Questions

None for renaming. Real Isaac Sim validation remains a separate pending task.

## Scope

Rename modules, configuration, optional dependency, protocol namespace and tests.
Bring the already prepared standalone worker into the repository so setup no longer
requires the other project's source. Regenerate bindings and update usage docs.

## Out of Scope

Changing chemistry or planner behavior; altering existing services; publishing a PR.

## Tasks

- [x] Rename implementation and migrate standalone worker.
- [x] Update docs, dependency lock and protocol bindings.
- [x] Run unit, protocol, formatting and typing checks.

Record: [changes](../changes/2026-09-20-chemistry-bench-naming.md).

## Acceptance Criteria

No old project naming remains in the newly added source/configuration/documentation.
Client and standalone worker use the same new protocol. Existing tests still pass.

## Risks

The renamed gRPC service requires the matching worker; older external workers are
not wire-compatible. Isaac SDK remains isolated from the Python 3.11 agent runtime.
