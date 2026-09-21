# Chemistry bench naming and worker packaging

Plan: [0015](../plans/0015-chemistry-bench-naming.md).

Unified the environment class/module, agent/run configs, tests, docs and optional
dependency under chemistry bench naming. Removed the newly added cross-project
provenance notice after the author clarified ownership; third-party dependency
terms remain unchanged. Regenerated the protobuf service namespace and matching
client/server bindings rather than editing serialized descriptors by hand.

Added standalone simulator and chemistry packages under
`benchmarks/chemistry-bench-sim`, separate from the Python 3.11 agent. Worker imports
the matching local protocol package, binds loopback and disables multi-GPU rendering.
Existing model/simulator services were not changed. Older differently named gRPC
workers are not compatible with the renamed service.

Verification: 143 tests passed in the base environment, one optional test skipped;
20 focused adapter/chemistry/protocol tests passed in the independently installed client
environment. Ruff and mypy passed. Added Python 3.10 source syntax and actual
chemistry engine titration checks. Standalone worker wheel/sdist build succeeded.
No old project names remain in scoped source,
configuration, lockfile or documentation. Existing ignored development environments
outside the delivered source were retained, not destructively removed.

Real Isaac rendering/robot and VLM validation remain pending under plan 0014.
No commit, push or remote PR was created.
