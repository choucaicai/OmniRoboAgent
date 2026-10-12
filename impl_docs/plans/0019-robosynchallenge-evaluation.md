# RoboSynChallenge integration and evaluation

Status: DONE — integration isolated and CPU-verified on a clean PR branch.

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
  push to the contributor fork and PR publication to the user.

## Boundaries

This is a custom unfiltered Agent evaluation, not a reproduction of organizer
expert-feasibility-filtered paper scores. ACT is not language-conditioned; DP
support is unit-tested but did not receive a full matrix evaluation. Remote model
services remain user-managed. Upstream benchmark code and checkpoints are obtained
separately at documented revisions. Original workspace changes/results are retained.
