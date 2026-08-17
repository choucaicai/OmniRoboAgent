# Deployment guide

## Server prerequisites

- Linux GPU host with CUDA-compatible NVIDIA driver.
- Python 3.9 and a CUDA-enabled PyTorch build. The source environment used PyTorch 2.1.2 + CUDA 12.1.
- A local LatentPilot checkpoint containing at least `config.json`, tokenizer files, and model shard/index files.
- Network reachability from the robot to TCP port 5801, or SSH access for port forwarding.

The service uses `bfloat16` and `flash_attention_2`; choose a GPU and FlashAttention wheel/build that support them.

## Start the service

```bash
conda env create -f environment-server.yml
conda activate latentpilot-realworld
pip install -r requirements/server.txt
pip install flash-attn --no-build-isolation
pip install 'depth-camera-filtering @ git+https://github.com/naokiyokoyama/depth_camera_filtering.git'

cd server
python -m streamvln.http_realworld_server \
  --model_path /models/latentpilot \
  --device cuda:0 \
  --num_future_steps 4 \
  --num_frames 32 \
  --num_history 8 \
  --host 0.0.0.0 \
  --port 5801
```

Equivalent helper:

```bash
bash scripts/start_server.sh /models/latentpilot cuda:0
```

Set `LATENTPILOT_OUTPUT_DIR` or pass `--output_dir` to choose where incoming and annotated frames are saved. The server validates the checkpoint path before loading it.

## HTTP protocol

`POST /eval_vln` expects multipart form data:

- `image`: a JPEG RGB frame;
- `json`: `{"reset": true}` at the beginning of an episode, otherwise `{"reset": false}`.

The response is JSON: `{"action": [1, 2, 1]}`. The robot client converts the fixed action vocabulary into local goals or timed velocity commands. The service retains policy memory until the next `reset` request.

## Networking patterns

Direct network:

```bash
# Robot shell
export LATENTPILOT_SERVER_URL=http://GPU_HOST:5801/eval_vln
```

SSH tunnel, recommended when the GPU server is not exposed on the robot LAN:

```bash
# Robot shell; keep this process running
ssh -N -L 5801:127.0.0.1:5801 USER@GPU_HOST
export LATENTPILOT_SERVER_URL=http://127.0.0.1:5801/eval_vln
```

Before enabling motion, send a test image from the robot and confirm a response is returned within the client timeout (150 seconds).

## Operational controls

The active server instruction is set in `server/streamvln/http_realworld_server.py`. When a STOP action is observed, the server prints a prompt for the next instruction. Start each new navigation episode with `reset=true`; otherwise memory from the prior episode is retained.

The model's motion vocabulary assumes 25 cm forward increments and 15 degree rotations. If a robot needs different increments, retrain or calibrate the robot controller carefully rather than changing only one side of the interface.
