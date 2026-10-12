# RoboSynChallenge upstream submodule layout

Align the integration with the repository's existing third-party benchmark
convention. `.gitmodules` records public upstream URLs; parent Git stores only
mode-160000 gitlinks, not vendored source files:

- `benchmarks/RoboSynChallenge` → EDEM-AI/RoboSynChallenge,
  `8818c82df5fa2522809b8105e7018950dcc9a9a8`.
- `benchmarks/EmbodiChain` → DexForce/EmbodiChain,
  `89c14da8d0221dc4ee2a4a3e0ba1078b16d447bd` (v0.2.4.post1).

Keep `benchmarks/robosyn-runtime` as our own dependency specification/lock. Change
its editable paths to `../RoboSynChallenge` and `../EmbodiChain`, adjust SDK
default discovery to the sibling `EmbodiChain` submodule, and update installation
and CLI examples. Add one regression test for SDK path inference. No checkpoint,
physics, reset-state protocol or evaluation seed change is made.

Validation: both submodules initialized at their pinned upstream commits; 38
RoboSyn tests and 183 full-suite tests passed (1 optional skip); Ruff lint/format
and mypy (7 sources) passed. `uv lock --check --offline` resolves the unchanged
281-package runtime successfully. Clone checkout permissions were normalized to
their stored Git modes; upstream source content is unchanged. This does not rerun
the historical 1000-episode GPU matrix or repair the known native GC issue.

Keep the user's existing integration commit unchanged. This follow-up is staged
for a new commit and push to the same upstream feature branch; no commit, push
or PR mutation is performed automatically. Original workspaces/results remain.
