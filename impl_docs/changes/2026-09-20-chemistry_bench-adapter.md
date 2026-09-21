# Chemistry bench adapter

Plan: [0014](../plans/0014-chemistry_bench-titration.md), IN_PROGRESS pending real
Isaac Sim and model-driven validation.

Implemented the environment adapter, fixed task/configuration, optional transport,
CPU tests and loopback serialization test. Agent, Pipeline and Runtime are unchanged.
Truth is private to grading and uncertain RPC actions are never automatically replayed.

Initial verification: 141 unit tests passed, plus the optional gRPC test; Ruff and
mypy passed. An Isaac startup attempt reported shared DerivedDataCache lock errors
before readiness; it was stopped without repairing or deleting shared caches.
These errors alone do not establish a fatal simulator failure. Real smoke remains
unverified. Naming and local worker packaging are tracked in plan 0015.

No commit, push or remote PR was made.
