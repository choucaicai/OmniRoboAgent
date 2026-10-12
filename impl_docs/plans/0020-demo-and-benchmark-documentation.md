# Separate chemistry demo and official-task evaluation

Status: DONE — documentation separation, README grouping and video-link follow-ups complete.

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

Code changes, simulator migration and rerunning GPU evaluation. Earlier documentation
follow-ups excluded commits/pushes; the user explicitly authorized them for the video-link update.

## Tasks

- [x] Separate public descriptions and navigation.
- [x] Check documentation links, command syntax and diff whitespace.
- [x] Record verification and mark the task complete.

## Acceptance Criteria

Readers can distinguish the chemistry demo from official-task evaluation; no text
attributes the 41.2% result to the chemistry simulator or claims exact paper reproduction.

## Risks

Existing `chemistry_bench` paths remain compatibility identifiers, not a benchmark claim.

## README grouping follow-up

The user requested one chemistry-platform chapter with two distinct subsections:
the chemistry demo and OmniRoboAgent running official RoboSynChallenge tasks.
Keep their simulation environments and score attribution separate, and preserve
all existing commands and result details.

- [x] Group README headings, check hierarchy/unchanged command blocks and record verification.

Follow-up record: [README grouping](../changes/2026-10-12-chemistry-chapter-grouping.md).

## Video-link follow-up

- [x] Link the existing PR #8 video attachment from the README chemistry demo;
  preserve the stable GitHub URL without uploading the video again.
- [x] Check attachment access and unchanged command blocks.

Follow-up record: [demo video link](../changes/2026-10-12-chemistry-demo-video-link.md).
