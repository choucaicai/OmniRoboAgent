# RoboSynChallenge integration and evaluation

Status: DONE — upstream checkouts aligned with the repository submodule layout.

## Scope

Add native RoboSynChallenge Environment, local ACT/DP SkillBackend, seeded
evaluation/matrix runner, isolated locked runtime, example AgentConfig and ten-task
manifest. Reuse existing Planner/Verifier/Memory/Pipeline contracts. Keep simulator
and policy imports optional and outside core. Do not copy other benchmark changes,
weights, generated runs or model services into this PR.

## Validation

- [x] Full visual Qwen3.5-9B + ACT evaluation: ten official tasks, random, explicit
  seeds 0–99 per task, 412/1000 successes (41.2%).
- [x] All valid seeds, authoritative success, reset v2, artifacts and identities
  audited; old reset-protocol results and incomplete attempts excluded.
- [x] Preserve native teardown SIGSEGV evidence; strict cached resume exited 0
  without rerunning valid episodes. Do not claim native GC has been fixed.
- [x] Verify isolated changes against latest upstream master `c01a6bd`: 37
  focused tests; 182 full-suite tests passed, 1 optional test skipped; Ruff/mypy passed.
- [x] Prepare only intended PR files on `feat/robosynchallenge`; leave commit,
  push to the upstream feature branch and PR publication to the user.

## Submodule layout follow-up

- [x] Add `benchmarks/RoboSynChallenge` and `benchmarks/EmbodiChain` as gitlinks
  to their official URLs, pinned to the same evaluated upstream commits.
- [x] Move isolated runtime references, SDK discovery and instructions to the
  repository-local submodules; retain our own `robosyn-runtime` dependency lock.
- [x] Revalidate CPU tests (38 focused; 183 full-suite passed, 1 optional skip),
  Ruff/mypy and offline locked-runtime consistency without rerunning GPU evaluation.

The user's integration commit is preserved. Stage a follow-up rather than
rewriting history; do not push automatically or copy upstream source into parent Git.

## Boundaries

This is a custom unfiltered Agent evaluation, not a reproduction of organizer
expert-feasibility-filtered paper scores. ACT is not language-conditioned; DP
support is unit-tested but did not receive a full matrix evaluation. Remote model
services remain user-managed. Upstream code is pinned through submodules; model
checkpoints are downloaded separately at documented revisions. Original workspace
changes/results are retained.
