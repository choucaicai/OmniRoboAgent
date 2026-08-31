# LatentPilot Real-World Navigation

A standalone real-robot navigation package with StreamVLN and AwareVLN GPU inference servers. It separates policy inference from robot-side sensing and control through a small HTTP API.

> **Safety notice.** This software commands physical robots. Test first in an unobstructed area with a hardware e-stop, a spotter, and conservative velocity limits. Inspect camera, odometry, network, and stop behavior before allowing autonomous motion.

## What is included

- GPU HTTP inference services: bundled LatentPilot/StreamVLN code and an adapter for the external official AwareVLN repository.
- Robot clients: Unitree Go2 ROS2 + SDK2 clients, an SDK2 open-loop Go2 client, and a LIMO client.
- PID controller and thread-safe state utility used by the Go2 clients.
- Reproducible environment specifications and launch scripts.
- Six real-world demonstration assets in [`assets/`](assets/).

Model weights are deliberately not bundled. Point each server at its corresponding local checkpoint.

## Architecture

```text
camera + robot odometry ──> robot client ──HTTP POST /eval_vln──> GPU server
       ^                                                              |
       └──── velocity commands <── action codes [forward,left,right,stop] ──┘
```

Action semantics are fixed: `0=STOP`, `1=forward 0.25 m`, `2=left 15°`, `3=right 15°`.

## StreamVLN quick start

### 1. Create the GPU-server environment

On a CUDA Linux machine, create the Conda environment and install the hardware-matched PyTorch / FlashAttention builds first:

```bash
conda env create -f environment-server.yml
conda activate latentpilot-realworld
pip install -r requirements/server.txt
```

`flash-attn` must be built or installed for the installed CUDA and PyTorch ABI. The original working environment used Python 3.9, PyTorch 2.1.2, CUDA 12.1, Transformers 4.45.1, and FlashAttention 2.

### 2. Start the policy service

Copy or download the checkpoint to the server, then run:

```bash
cd server
bash ../scripts/start_server.sh /path/to/latentpilot-checkpoint cuda:0
```

The service listens on `0.0.0.0:5801`, writes annotated received frames to `server/streamvln/runs/`, and asks for the next natural-language instruction after the policy emits STOP. See [`docs/deployment.md`](docs/deployment.md) for all options.

## AwareVLN quick start

AwareVLN requires its separate official Python 3.10 environment and source repository:

```bash
cd /path/to/OmniRoboAgent/RobotWorkspace_nav
bash scripts/start_awarevln_server.sh \
  /opt/AwareVLN \
  /models/AwareVLN-ck/awarevln \
  cuda:0 \
  --host 127.0.0.1 \
  --port 5802
```

See [`docs/awarevln.md`](docs/awarevln.md) for installation, checkpoint layout, HTTP fields, reasoning behavior, and action conversion.

## Connect and run the robot client

For a robot not directly routable to the GPU host, make a tunnel on the robot:

```bash
ssh -N -L 5801:localhost:5801 user@gpu-server
export VLN_SERVER_URL=http://127.0.0.1:5801/eval_vln
export VLN_INSTRUCTION='Exit the room and stop beside the red chair.'
```

The recommended Go2 client combines ROS2 odometry with Unitree SDK2 video and motion:

```bash
cd robot
python3 go2_3.py --iface eth0
```

Before running, complete the robot-specific checks in [`docs/go2.md`](docs/go2.md). The client files are described in [`docs/clients.md`](docs/clients.md).

## Layout

```text
assets/       Real-world videos and project icon
server/       StreamVLN code plus the AwareVLN HTTP/model adapter
robot/        Go2/LIMO clients plus PID control
docs/         Deployment, hardware, client, and asset notes
requirements/ Server and robot dependency lists
scripts/      Launch helpers
environment-server.yml  Conda environment definition
```

## Demo videos

| File | View / role |
| --- | --- |
| `4975_498.mp4` | Main real-world teaser |
| `first-person.mp4` | Robot first-person view |
| `third-person.mp4` | External third-person view |
| `3870_385.mp4`, `3976_402.mp4` | Additional demonstrations |

## Attribution

The StreamVLN deployment is derived from the local LatentPilot research project. The AwareVLN adapter follows the official [GWxuan/AwareVLN](https://github.com/GWxuan/AwareVLN) Apache-2.0 implementation without bundling its source or weights.
