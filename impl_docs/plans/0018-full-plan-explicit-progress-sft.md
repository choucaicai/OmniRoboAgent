# Full-plan explicit-progress SFT

Status: complete (2026-09-13).

## Goal

Replace the hidden-duration RoboTwin scheduler experiment with an easier,
deployment-consistent variant. Qwen generates the complete ordered plan and every
chunk budget once from the initial task and three camera images. Runtime caches that
model output. Each later verifier request receives the same plan plus explicit
completed-subtask, current-subtask and current-chunk state.

To preserve Omni's normal planning boundary, each subtask also starts with a new
image-conditioned Planner call. That call receives the cached model-generated plan,
explicit progress, recent history and current images, and must select the one current
plan item verbatim. Runtime never advances invisibly by indexing the cache alone.

## Scope

- Add an opt-in scheduled mode to `SubtaskPlanPlanner`; default Omni behavior stays
  unchanged.
- Add an opt-in planned-schedule input to `SubtaskVerifier`.
- Replay all 2486 existing expert episodes through the real synchronous Omni loop.
- Reuse the already audited RGB images and episode-level train/validation split.
- Add an independent audit for complete-plan identity, progress continuity, labels,
  splits and image references.

The verifier's `completed` label means that the generated chunk budget has been
consumed. It is not visual proof of physical success and does not replace RoboTwin's
benchmark success signal.

## Acceptance

- Exactly one model-generated complete plan per episode.
- Every plan item matches its source skill, subtask, completion condition and fixed
  maximum budget.
- Exactly one image-conditioned Planner selection is made before every subtask.
- Every selection exactly matches the current item in the cached plan.
- Every verifier request contains the identical plan and exact progress counters.
- Unit tests, Ruff and the independent full-data audit pass.

## Result

All 2486 episodes were replayed. The export contains 2486 initial full-plan
examples, 7645 image-conditioned subtask selections and 24897 verifier examples
(35028 total), with 69939 unique image references. The independent audit passed
every acceptance check. Fresh three-GPU LoRA training was then started from the
unmodified Qwen3-VL-8B base; it does not resume the old 3500-step adapter.
