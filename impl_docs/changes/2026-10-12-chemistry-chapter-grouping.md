# Chemistry platform README chapter grouping

Date: 2026-10-12
Related plan: [0020](../plans/0020-demo-and-benchmark-documentation.md)

## Changed

Group the README under one chemistry-platform chapter with two subsections:
chemistry demo and OmniRoboAgent running official RoboSynChallenge tasks. Adjust
detail headings and add an introduction distinguishing environments and score attribution.
Existing instructions, links and results remain unchanged.

## Files

`README.md`, `impl_docs/TODO.md`, the related plan and this record.

## Verification

- `awk` heading check: exactly two third-level subsections.
- `diff` of fenced blocks extracted by `awk` from HEAD/current README: identical.
- `awk` Bash-fence extraction piped to `bash -n`: passed.
- `git diff --check`: passed.

## Remaining Work

No new runtime capability; no GPU runs or source changes were needed for this regrouping.
