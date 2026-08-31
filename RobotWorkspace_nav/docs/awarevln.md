# AwareVLN real-world server

This server adapts the official
[GWxuan/AwareVLN](https://github.com/GWxuan/AwareVLN) checkpoint to the
existing `RobotWorkspace_nav` robot action protocol. The upstream model uses
NaVILA-style VILA with Llama-3 8B, SigLIP, eight RGB frames, and alternating
reasoning/action output.

The official source and checkpoint are external dependencies. They are not
copied into this repository.

## Environment

AwareVLN requires its own Python 3.10 environment. Do not install it into the
StreamVLN environment: the two models require different PyTorch, Transformers,
FlashAttention, model code, and `llava` packages.

On the CUDA server:

```bash
git clone https://github.com/GWxuan/AwareVLN.git /opt/AwareVLN
cd /opt/AwareVLN
git checkout 8f14eb8450cdd14ff4e3ba1ea04824255121e6be
./environment_setup.sh awarevln-realworld
conda activate awarevln-realworld

pip install -r \
  /path/to/OmniRoboAgent/RobotWorkspace_nav/requirements/awarevln-server.txt
```

Download the `awarevln/` checkpoint directory from
[`gwx22/AwareVLN-ck`](https://huggingface.co/gwx22/AwareVLN-ck). The path
passed to the server must point to the directory containing its top-level
`config.json`, `llm/`, `vision_tower/`, and `mm_projector/`.

The checkpoint is approximately 33 GB. Model loading and inference require a
CUDA Linux host supported by the upstream AwareVLN environment.

## Start

From `RobotWorkspace_nav`:

```bash
bash scripts/start_awarevln_server.sh \
  /opt/AwareVLN \
  /models/AwareVLN-ck/awarevln \
  cuda:0 \
  --host 127.0.0.1 \
  --port 5802
```

The helper starts from the official source directory so that Python imports
AwareVLN's `llava` package instead of the unrelated StreamVLN `server/llava`
package.

Check readiness:

```bash
curl http://127.0.0.1:5802/healthz
```

For a remote GPU host, keep the server bound to localhost and forward it from
the robot:

```bash
ssh -N -L 5802:127.0.0.1:5802 user@gpu-server
```

## HTTP request

`POST /eval_vln` uses the same multipart shape as the existing StreamVLN
server:

- `image`: current JPEG frame;
- `json`: object containing `reset`, `session_id`, and optional `instruction`.

First request:

```bash
curl -X POST http://127.0.0.1:5802/eval_vln \
  -F image=@frame.jpg \
  -F 'json={
    "reset": true,
    "session_id": "go2-01",
    "instruction": "Exit the room and stop beside the red chair."
  }'
```

Later requests use the same session:

```bash
curl -X POST http://127.0.0.1:5802/eval_vln \
  -F image=@next-frame.jpg \
  -F 'json={"reset": false, "session_id": "go2-01"}'
```

Example response:

```json
{
  "action": [1, 1],
  "mode": "act",
  "terminal": false,
  "reasoning": [
    "I have entered the hallway and should continue toward the doorway."
  ],
  "raw_output": "<BEGIN_OF_ACTION> Move forward 50 cm.",
  "session_id": "go2-01"
}
```

Changing an instruction requires `reset=true`. Unknown sessions return HTTP
`409`; invalid model action text returns `422` instead of silently moving the
robot.

## Action conversion

AwareVLN produces one textual action with an optional magnitude. The parser
converts it to the existing fixed primitives:

| Model output | Robot actions | Concrete motion |
| --- | --- | --- |
| `stop` | `[0]` | stop navigation |
| `move forward 25 cm` | `[1]` | forward 0.25 m |
| `move forward 50 cm` | `[1, 1]` | forward 0.50 m |
| `move forward 75 cm` | `[1, 1, 1]` | forward 0.75 m |
| `turn left 30 degrees` | `[2, 2]` | left 30 degrees |
| `turn right 45 degrees` | `[3, 3, 3]` | right 45 degrees |

Missing magnitudes use one primitive. Other positive values are rounded to the
nearest 25 cm or 15 degrees and limited to three primitives per model call.
Outputs containing multiple conflicting command types are rejected.

`<BEGIN_OF_REASONING>` or `[REASON]` output does not move the robot. The server
stores the reasoning and calls the model again with that context. Four
consecutive reasoning turns are allowed by default; reaching the configured
limit returns `[0]`.

## Go2 client

The recommended client can select either server:

```bash
export VLN_SERVER_URL=http://127.0.0.1:5802/eval_vln
export VLN_SESSION_ID=go2-01
export VLN_INSTRUCTION='Exit the room and stop beside the red chair.'

cd robot
python3 go2_3.py --iface eth0
```

`VLN_SERVER_URL` takes precedence over the legacy
`LATENTPILOT_SERVER_URL`. The client sends the instruction on its first
request, converts SDK2 BGR frames to RGB, and stops requesting plans after
action `0`.

## Local tests

The parser, reasoning loop, and HTTP protocol tests do not load the checkpoint:

```bash
PYTHONPATH=. uv run --isolated --no-project \
  --with pytest --with Flask --with Pillow \
  python -m pytest -q RobotWorkspace_nav/tests
```

## Limits and safety

- GPU inference is serialized even when multiple session IDs are active.
- Session history is in memory and is lost when the server restarts.
- The Flask server has no authentication or TLS. Keep it on localhost or a
  trusted network and prefer SSH port forwarding.
- Real checkpoint loading and physical robot motion must be validated on the
  target CUDA and robot hosts.
- Use a hardware e-stop, a spotter, conservative speed limits, and a clear
  test area before enabling motion.

The inference sequence and output vocabulary follow the official AwareVLN
evaluation implementation, distributed under Apache-2.0.
