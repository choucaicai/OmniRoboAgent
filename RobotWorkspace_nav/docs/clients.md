# Robot clients

| File | Intended use | Notes |
| --- | --- | --- |
| `go2_3.py` | Recommended Go2 closed-loop client | ROS2 odometry plus SDK2 camera and motion in isolated processes. |
| `go2_vln_client_v2.py` | Alternative Go2 closed-loop client | Earlier variant of the same ROS2/SDK2 architecture. |
| `go2_vln_client.py` | ROS2 camera + Unitree API client | Requires `realsense-ros`, `cv_bridge`, and Unitree ROS2 APIs. |
| `go2_vln_client_v1-5.py` | Earlier ROS2 client | Retained for compatibility with older deployed stacks. |
| `go2_vln_client_openloop.py` | SDK2-only Go2 client | No odometry feedback; executes timed actions, so use very cautiously. |
| `limo_client.py` | LIMO mobile base client | OpenCV camera and `pylimo`; action execution is open loop. |

All clients read `LATENTPILOT_SERVER_URL`; it defaults to `http://localhost:5801/eval_vln` for local or SSH-forwarded operation.

For the ROS2-camera client, mount an Intel RealSense D400 camera and launch the matching `realsense-ros` node, then check the image topic in the client before use. The original topic is `/camera/camera/color/image_raw`; change the subscription if your launch file publishes a different topic.
