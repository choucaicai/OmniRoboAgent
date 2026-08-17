# Unitree Go2 setup and safety checklist

## Software and hardware

The recommended client, `robot/go2_3.py`, uses two execution domains:

- ROS2 Foxy subscribes to `/sportmodestate` for odometry and performs local goal/PID control.
- Unitree SDK2 `VideoClient` captures camera frames and `SportClient` sends velocity commands in a separate process.

Install/sourcing requirements before launch:

```bash
source /opt/ros/foxy/setup.bash
# Source the Go2 ROS2 workspace that provides unitree_go messages.
# Ensure unitree_sdk2py is importable in this Python environment.
pip install -r requirements/robot-go2.txt
```

Use the correct DDS NIC, typically the wired robot interface:

```bash
cd robot
export LATENTPILOT_SERVER_URL=http://127.0.0.1:5801/eval_vln
python3 go2_3.py --iface eth0 --domain_id 0
```

## Preflight checklist

1. Put the robot in a clear, flat space; assign a safety operator and verify e-stop access.
2. With the control client stopped, verify the required NIC and SDK2 connection.
3. Confirm `ros2 topic echo /sportmodestate --once` returns a valid pose/velocity state.
4. Confirm the server is reachable, including any SSH tunnel.
5. Start the client and verify logs show both **first frame** and **first odom** before allowing movement.
6. Begin with a short forward instruction; observe the 0.25 m / 15 degree action calibration.
7. Use Ctrl-C/e-stop immediately for unexpected motion. The normal client shutdown sends `StopMove` to the SDK worker.

## Calibration points

`pid_controller.py` uses `Kp_trans=3.0`, `Kd_trans=0.5`, `Kp_yaw=3.0`, `Kd_yaw=0.5`, with maximum `1.0 m/s` and `1.2 rad/s`. These are source experiment values, not universal safe defaults. Reduce limits and tune gains for a new robot, floor, payload, or localization stream.

The client assumes `/sportmodestate` has Unitree Go2 position, yaw, linear velocity, and yaw speed fields. Adapt the odometry callback if the deployed firmware/message package differs.
