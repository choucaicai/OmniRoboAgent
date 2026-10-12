# Chemistry demo and official-task evaluation documentation

Date: 2026-10-12
Related plan: [0020](../plans/0020-demo-and-benchmark-documentation.md)

## Changed

- Give the self-developed chemistry simulation platform its own README chapter:
  fixed titration demo, installation, scripted/model paths and actual verification scope.
- Keep RoboSynChallenge in a separate chapter as OmniRoboAgent running official
  tasks in EmbodiChain/DexSim. The historical 412/1000 result does not evaluate
  the chemistry simulator and is not exact paper-score reproduction.
- Move chemistry from benchmark navigation to Simulation Demo; keep API/package
  identifiers, commands and all historical results intact.
- Replace the README clone placeholder with the actual upstream repository URL.

## Files

`README.md`, `docs/README.md`, `docs/_sidebar.md`, `docs/chemistry_bench.md`,
`docs/robosynchallenge.md`, `docs/robosynchallenge-results.md`,
`impl_docs/architecture/overview.md`, `impl_docs/TODO.md`, the related plan and this record.

## Verification

- `awk` extraction of Bash fences piped to `bash -n` for the root README and
  three integration/result guides: passed after replacing the clone placeholder.
- `perl -MFile::Basename=dirname -MFile::Spec` local Markdown link check on the
  six public documents: 77 checked, zero missing.
- `git diff --check`: passed.
- Source/configuration and GPU runs were not changed; no runtime tests or GPU
  evaluation were rerun for this documentation-only update.

## Remaining Work

The articulated chemistry demo's model loop remains unvalidated after camera/motion
updates. A wider implementation-document link check found two pre-existing missing
targets (`plans/0013-awarevln-realworld-server.md` and
`reference/project-overview-2026-08-30.md`), confirmed in `git show HEAD:...`;
unrelated historical links are left unchanged.
