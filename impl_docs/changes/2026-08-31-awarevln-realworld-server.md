# Add AwareVLN Real-World Inference Server

Date: 2026-08-31
Related plan: `impl_docs/plans/0013-awarevln-realworld-server.md`

## Changed

- Added an AwareVLN model adapter that loads the external official repository and checkpoint, maintains bounded RGB/reasoning history per session, and follows the official reason-act inference loop.
- Added a strict output parser for `<BEGIN_OF_REASONING>` / `[REASON]`, `<BEGIN_OF_ACTION>` / `[ACT]`, STOP, forward distance, and turn angle.
- Quantized AwareVLN text actions to the existing robot protocol: `0=STOP`, `1=forward 0.25 m`, `2=left 15 degrees`, and `3=right 15 degrees`.
- Added a session-aware `POST /eval_vln` endpoint and `/healthz` endpoint without changing the existing StreamVLN server.
- Added a launch helper and separate lightweight HTTP requirements for the official AwareVLN Python 3.10 environment.
- Updated the recommended Go2 client to send instruction/session metadata, convert SDK2 BGR frames to RGB, validate action IDs, retry initial reset correctly, and stop replanning after STOP.
- Added AwareVLN installation, protocol, parser, robot invocation, dependency isolation, and safety documentation.

## Files

- `RobotWorkspace_nav/server/awarevln/__init__.py`
- `RobotWorkspace_nav/server/awarevln/action_parser.py`
- `RobotWorkspace_nav/server/awarevln/policy.py`
- `RobotWorkspace_nav/server/awarevln/http_realworld_server.py`
- `RobotWorkspace_nav/scripts/start_awarevln_server.sh`
- `RobotWorkspace_nav/requirements/awarevln-server.txt`
- `RobotWorkspace_nav/robot/go2_3.py`
- `RobotWorkspace_nav/docs/awarevln.md`
- `RobotWorkspace_nav/docs/deployment.md`
- `RobotWorkspace_nav/docs/clients.md`
- `RobotWorkspace_nav/README.md`
- `RobotWorkspace_nav/.env.example`
- `RobotWorkspace_nav/tests/test_awarevln_action_parser.py`
- `RobotWorkspace_nav/tests/test_awarevln_policy.py`
- `RobotWorkspace_nav/tests/test_awarevln_server.py`
- `impl_docs/architecture/overview.md`
- `impl_docs/TODO.md`
- `impl_docs/plans/0013-awarevln-realworld-server.md`
- `impl_docs/README.md`
- `impl_docs/changes/2026-08-31-awarevln-realworld-server.md`

## Verification

- Main isolated unit suite: passed, 124 tests.
- Separate AwareVLN parser, reason-act loop, and Flask protocol suite: passed, 24 tests.
- Ruff check for `src`, `tests`, and the new AwareVLN server: passed.
- Ruff format check for all new AwareVLN Python and test files: passed.
- Main package mypy strict check under Python 3.11: passed, 60 source files.
- `python3 -m py_compile` for the new server and updated Go2 client: passed.
- AwareVLN server `--help` import smoke with isolated Flask/Pillow dependencies: passed.
- `bash -n RobotWorkspace_nav/scripts/start_awarevln_server.sh`: passed.
- Local Markdown link check and `git diff --check`: passed.

The official AwareVLN checkpoint is approximately 33 GB and was not downloaded.
CUDA model loading, model output quality, network deployment, ROS2, Unitree SDK2,
and physical robot motion were not validated on this macOS host.

## Remaining Work

- Run a fixed-frame smoke test with the official AwareVLN source commit and checkpoint on the target CUDA host.
- Verify that actual checkpoint generations retain the documented mode tokens and action wording.
- Run the Go2 client with wheels raised, then in a clear controlled area with a hardware e-stop and spotter.
- Add transport authentication before exposing either inference server outside a trusted network.
