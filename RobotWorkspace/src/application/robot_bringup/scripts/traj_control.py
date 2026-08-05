#!/usr/bin/env python3
import pandas as pd
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from builtin_interfaces.msg import Duration
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from geometry_msgs.msg import PoseStamped
from moveit_msgs.srv import GetPositionIK

import os
from convert import FkArm, rotmat2poseeuler
from scipy.spatial.transform import Rotation as R

class FrankaTrajectoryPlayer(Node):
    def __init__(self):
        super().__init__("franka_trajectory_player")

        self.traj_topic = "/mk1000/fr3_arm_controller/joint_trajectory"
        self.csv_path = "/home/rpp/rpp_ws/data/bags/2025-12-02 15:12:41/joint.csv"
        self.declare_parameter("urdf_path", f"{os.environ['WORKDIR']}/src/robot/mr1000_description/urdf/robot.urdf")
        self.urdf_path = (self.get_parameter("urdf_path").get_parameter_value().string_value)

        self.fk_arm = FkArm(self.urdf_path)

        self.get_logger().info(f"Loading trajectory CSV: {self.csv_path}")

        self.get_logger().info("Waiting for initial /joint_states to move to start pose...")

        self.joint_names = [
            "mk1000_fr3_joint1",
            "mk1000_fr3_joint2",
            "mk1000_fr3_joint3",
            "mk1000_fr3_joint4",
            "mk1000_fr3_joint5",
            "mk1000_fr3_joint6",
            "mk1000_fr3_joint7",
        ]

        self.group_name = "mk1000_fr3_arm"
        self.base_frame = "base_link"
        self.ik_link_name = "mk1000_fr3_link8"

        self.transition_duration = 1.0
        self.pub = self.create_publisher(JointTrajectory, self.traj_topic, 10)

        # 只需要获取一次当前关节角
        self.got_start_state = False
        self.joint_state_sub = self.create_subscription(
            JointState,
            "/mk1000/joint_states",       # 如有不同请改成你的 joint_states 话题
            self.joint_state_callback,
            10,
        )

        self.get_logger().info("Waiting for initial /joint_states to move to start pose...")

    def joint_state_callback(self, msg: JointState):
        if self.got_start_state:
            return

        self.got_start_state = True
        self.get_logger().info("Received initial joint state, preparing trajectory...")

        # 把 JointState 里的 name->position 做一个字典，方便按 joint_names 顺序取
        name_to_pos = dict(zip(msg.name, msg.position))

        # 按 joint_names 的顺序提取当前关节角
        try:
            current_q = [float(name_to_pos[name]) for name in self.joint_names]
        except KeyError as e:
            self.get_logger().error(
                f"joint_states 中缺少关节 {e}，请检查 joint_names 与 /joint_states 的 name 是否一致"
            )
            rclpy.shutdown()
            return

        self.current_joint_states = current_q
        if not self.got_start_state:
            self.got_start_state = True
            self.get_logger().info("Received initial joint state.")


    def prepare_and_publish_trajectory(self, current_q):
        self.get_logger().info(f"Loading CSV trajectory from: {self.csv_path}")

        # 1) 用 pandas 读取 CSV
        # 假设 CSV 格式为：
        # timestamp_ms,joint1,joint2,joint3,joint4,joint5,joint6,joint7
        try:
            df_raw = pd.read_csv(self.csv_path)
            df = df_raw.iloc[::40].reset_index(drop=True)
        except Exception as e:
            self.get_logger().error(f"Failed to read CSV: {e}")
            rclpy.shutdown()
            return

        if not {"timestamp_ms", "joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "joint7"} <= set(df.columns):
            self.get_logger().error("CSV 列名必须至少包含: timestamp_ms, joint1~joint7")
            rclpy.shutdown()
            return

        timestamps = df["timestamp_ms"].to_numpy()
        q_mat = df[["joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "joint7"]].to_numpy()
        q_mat = np.deg2rad(q_mat)

        if len(timestamps) == 0:
            self.get_logger().error("CSV 轨迹为空！")
            rclpy.shutdown()
            return
        
        pose_list = []
        for t, joints in zip(timestamps, q_mat):
            jointsAng_rad = joints
            end_mat = self.fk_arm(jointsAng_rad)     # 4x4 齐次变换矩阵
            xyzrpy = rotmat2poseeuler(end_mat)      # [x, y, z, r, p, y]
            pose_list.append(np.concatenate(([t], xyzrpy)))

        pose_mat = np.vstack(pose_list)  # shape: (N, 7+1)

        # 存成 DataFrame，列：timestamp_ms, x, y, z, roll, pitch, yaw
        self.df_pose = pd.DataFrame(
            pose_mat,
            columns=["timestamp_ms", "x", "y", "z", "roll", "pitch", "yaw"]
        )

        self.df_pose.to_csv("/home/rpp/rpp_ws/data/bags/2025-12-02 15:12:41/joint_xyzrpy.csv")

        self.client = self.create_client(GetPositionIK, "/pc_arm/compute_ik")
        self.get_logger().info(f"Waiting for IK service: /pc_arm/compute_ik ...")
        if not self.client.wait_for_service(timeout_sec=10.0):
            self.get_logger().error("IK service not available. Is moveit.launch.py running?")
            rclpy.shutdown()
            return     
        
        rpy = self.df_pose[["roll","pitch","yaw"]].values
        rot = R.from_euler('xyz', rpy, degrees=False)
        quats_xyzw = rot.as_quat()
        self.df_pose["qx"] = quats_xyzw[:, 0]
        self.df_pose["qy"] = quats_xyzw[:, 1]
        self.df_pose["qz"] = quats_xyzw[:, 2]
        self.df_pose["qw"] = quats_xyzw[:, 3]

        df_pose = self.df_pose

        required_cols = {"timestamp_ms", "x", "y", "z", "qx", "qy", "qz", "qw"}
        if not required_cols.issubset(df_pose.columns):
            self.get_logger().error(
                f"Pose CSV must contain columns: {required_cols}, got: {df_pose.columns}"
            )
            rclpy.shutdown()
            return

        # 如果频率很高，也可以在这里直接降采样（例如每 40 个点取一个）
        # df_pose = df_pose.iloc[::40].reset_index(drop=True)

        timestamps = df_pose["timestamp_ms"].to_numpy()

        # 保存结果的列表
        joint_traj = []

        # 上一个解，用作 IK 种子，保持轨迹连续
        q_seed = self.current_joint_states

        self.get_logger().info(f"Start IK for {len(df_pose)} poses...")

        for idx, row in df_pose.iterrows():
            self.get_logger().info(f"Solving {idx} ...")
            # 构造 PoseStamped
            pose = PoseStamped()
            pose.header.frame_id = self.base_frame
            pose.header.stamp = self.get_clock().now().to_msg()

            pose.pose.position.x = float(row["x"])
            pose.pose.position.y = float(row["y"])
            pose.pose.position.z = float(row["z"])

            pose.pose.orientation.x = float(row["qx"])
            pose.pose.orientation.y = float(row["qy"])
            pose.pose.orientation.z = float(row["qz"])
            pose.pose.orientation.w = float(row["qw"])

            # 构造 IK 请求
            req = GetPositionIK.Request()
            req.ik_request.avoid_collisions = False
            req.ik_request.group_name = self.group_name
            req.ik_request.pose_stamped = pose
            req.ik_request.ik_link_name = self.ik_link_name
            # req.ik_request.attempts = 5
            req.ik_request.timeout.sec = 0
            req.ik_request.timeout.nanosec = int(0.05 * 1e9)  # 50ms

            self.get_logger().info(
                f"[IK] idx={idx}, pose: pos=({pose.pose.position.x:.3f}, "
                f"{pose.pose.position.y:.3f}, {pose.pose.position.z:.3f}), "
                f"quat=({pose.pose.orientation.x:.3f}, "
                f"{pose.pose.orientation.y:.3f}, "
                f"{pose.pose.orientation.z:.3f}, "
                f"{pose.pose.orientation.w:.3f})"
            )

            # 如果有上一帧解，用作 seed
            if q_seed is not None:
                req.ik_request.robot_state.joint_state.name = self.joint_names
                req.ik_request.robot_state.joint_state.position = q_seed

            # 同步调用服务
            future = self.client.call_async(req)
            rclpy.spin_until_future_complete(self, future, timeout_sec=2.0)

            if future.result() is None:
                self.get_logger().error(f"IK service call failed at index {idx}")
                rclpy.shutdown()
                return

            res = future.result()
            if res is None:
                self.get_logger().error(f"IK service call returned None at index {idx}")
                rclpy.shutdown()
                return

            # 检查返回的 error_code
            if res.error_code.val != res.error_code.SUCCESS:
                self.get_logger().warn(
                    f"IK failed at index {idx}, error_code={res.error_code.val}. "
                    f"Using previous solution if available."
                )
                if q_seed is None:
                    self.get_logger().error("No previous IK solution to fall back on. Aborting.")
                    rclpy.shutdown()
                    return
                q_sol = list(q_seed)
            else:
                # 从 solution.robot_state.joint_state 中取出我们的 7 个关节
                joint_state = res.solution.joint_state
                name_to_pos = dict(zip(joint_state.name, joint_state.position))

                try:
                    q_sol = [float(name_to_pos[name]) for name in self.joint_names]
                except KeyError as e:
                    self.get_logger().error(
                        f"IK solution missing joint {e}. "
                        f"Check joint_names list and MoveIt config."
                    )
                    rclpy.shutdown()
                    return

                q_seed = q_sol  # 作为下一帧的 seed

            joint_traj.append(q_sol)

        
        self.get_logger().info(f"IK finished.")

        joint_traj = np.array(joint_traj)  # shape: [N, 7]
        df_joint = pd.DataFrame(
            {
                "timestamp_ms": timestamps,
                "joint1": joint_traj[:, 0],
                "joint2": joint_traj[:, 1],
                "joint3": joint_traj[:, 2],
                "joint4": joint_traj[:, 3],
                "joint5": joint_traj[:, 4],
                "joint6": joint_traj[:, 5],
                "joint7": joint_traj[:, 6],
            }
        )

        q_mat = df_joint[["joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "joint7"]].to_numpy()

        # 2) 构造 JointTrajectory
        traj = JointTrajectory()
        traj.joint_names = self.joint_names

        # 2.1 加入第一个点：当前关节角，t = 0
        p0 = JointTrajectoryPoint()
        p0.positions = current_q
        p0.time_from_start = Duration(sec=0, nanosec=0)
        traj.points.append(p0)

        # 2.2 加入第二个点：轨迹起始姿态，t = transition_duration
        q_start = q_mat[0, :].tolist()
        p1 = JointTrajectoryPoint()
        p1.positions = q_start
        sec = int(self.transition_duration)
        nsec = int((self.transition_duration - sec) * 1e9)
        p1.time_from_start = Duration(sec=sec, nanosec=nsec)
        traj.points.append(p1)

        # 2.3 接上原来的轨迹点，但整体时间轴平移 transition_duration
        t0 = timestamps[0]
        for t, q in zip(timestamps[1:], q_mat[1:]):
            dt = float((t - t0) / 1e3) + self.transition_duration
            sec = int(dt)
            nsec = int((dt - sec) * 1e9)

            pt = JointTrajectoryPoint()
            pt.positions = q.tolist()
            pt.time_from_start = Duration(sec=sec, nanosec=nsec)
            traj.points.append(pt)

        self.get_logger().info(
            f"Final trajectory has {len(traj.points)} points "
            f"(including move-to-start). Now publishing..."
        )

        self.pub.publish(traj)
        self.get_logger().info("Trajectory published. Shutting down.")


def main():
    rclpy.init()
    node = FrankaTrajectoryPlayer()
    
    node.get_logger().info("Waiting for initial joint state...")
    while rclpy.ok() and not node.got_start_state:
        rclpy.spin_once(node, timeout_sec=0.1)

    if not node.got_start_state:
        node.get_logger().error("Failed to receive initial joint state.")
        rclpy.shutdown()
        return

    node.get_logger().info("Initial joint state received. Start IK & trajectory generation...")
    node.prepare_and_publish_trajectory(node.current_joint_states)

    if rclpy.ok():
        rclpy.shutdown()


if __name__ == "__main__":
    main()
