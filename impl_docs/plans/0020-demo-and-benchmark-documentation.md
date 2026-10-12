# Separate chemistry demo and official-task evaluation

Status: DONE

Change record: [documentation separation](../changes/2026-10-12-demo-and-benchmark-documentation.md).

## Goal

Document the self-developed chemistry simulation demo separately from OmniRoboAgent's
evaluation on official RoboSynChallenge tasks.

## Confirmed Decisions

- Keep both integrations and their instructions.
- Describe chemistry as a fixed titration demo, not an original benchmark.
- Attribute the 1000-episode result to RoboSynChallenge's own simulation environment.
- Preserve existing package/API paths and upstream names.

## Open Questions

None.

## Scope

README chapters, user-document introductions/navigation, architecture boundaries
and implementation records.

## Out of Scope

Code changes, simulator migration, rerunning GPU evaluation, commits and pushes.

## Tasks

- [x] Separate public descriptions and navigation.
- [x] Check documentation links, command syntax and diff whitespace.
- [x] Record verification and mark the task complete.

## Acceptance Criteria

Readers can distinguish the chemistry demo from official-task evaluation; no text
attributes the 41.2% result to the chemistry simulator or claims exact paper reproduction.

## Risks

Existing `chemistry_bench` paths remain compatibility identifiers, not a benchmark claim.
