# Chemistry demo video link

Date: 2026-10-12
Related plan: [0020](../plans/0020-demo-and-benchmark-documentation.md)

## Changed

Add a viewing link under the README chemistry demo, reusing the existing stable
[video attachment](https://github.com/user-attachments/assets/41eb9447-0ff1-4551-b0b2-a2b8e4931c01)
from [PR #8](https://github.com/choucaicai/OmniRoboAgent/pull/8). No video binary,
temporary signed URL, simulator or evaluation change is included.

## Files

`README.md`, `impl_docs/TODO.md`, the related plan and this record.

## Verification

- `curl --proxy http://127.0.0.1:13001 --range 0-0 -o /dev/null` with redirect
  following: HTTP 206, attachment readable. The preceding HEAD-only check returned 403.
- `diff` of fenced blocks extracted by `awk` from HEAD/current README: identical.
- `git diff --check`: passed.

## Remaining Work

No runtime changes or GPU reruns are required. The user explicitly requested
committing and normally pushing this update to the existing upstream feature branch.
