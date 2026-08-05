#!/usr/bin/env python3
# 应用一个action轨迹
import pandas as pd
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from std_msgs.msg import Float32
from sensor_msgs.msg import JointState
from builtin_interfaces.msg import Duration
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from geometry_msgs.msg import PoseStamped
from moveit_msgs.srv import GetPositionIK

import os, time
from typing import Tuple, List
import convert
from convert import FkArm
import threading
from threading import Event

class Actor(Node):
    def __init__(self):
        super().__init__("franka_trajectory_player")

        self.traj_topic = "/mk1000/fr3_arm_controller/joint_trajectory"
        self.eyehand_path = "/home/rpp/rpp_ws/data/calib/eyehand/results_12_5_344422300343/cam2base_4x4.npy"
        self.csv_path = "/data/parse/2025-12-05/15:40:01/episodes_5hz/episode_0_o0.csv"
        self.declare_parameter("urdf_path", f"{os.environ['WORKDIR']}/src/robot/mr1000_description/urdf/robot_arm_only.urdf")
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
        self.gripper_pub = self.create_publisher(Float32, "/gripper_control_signal", 10)

        self.app_idx = 0
        self.gripper_state = -123
        self.last_gripper_change_idx = 0

        # Prepare IK Service
        self.client = self.create_client(GetPositionIK, "/pc_arm/compute_ik")
        self.get_logger().info(f"Waiting for IK service: /pc_arm/compute_ik ...")
        if not self.client.wait_for_service(timeout_sec=10.0):
            self.get_logger().error("IK service not available. Is moveit.launch.py running?")
            rclpy.shutdown()
            return
        
    def reset(self, target_q: List[float] = None, duration: float = None):
        reset_joint_state = np.array([-17.21529197692871,-17.8583984375,12.776642799377441,-166.14749145507812,2.387296199798584,167.3789520263672,41.040199279785156])
        if target_q is None:
            target_q = np.deg2rad(reset_joint_state)
        if duration is None:
            duration = 5.0  # 你前面定义的 1.0s

        if len(target_q) != len(self.joint_names):
            self.get_logger().error(
                f"reset() target_q 长度({len(target_q)})和关节数({len(self.joint_names)})不一致!"
            )
            return

        self.get_logger().info(
            f"Resetting arm to joint state (rad): {['%.3f' % q for q in target_q]}, "
            f"duration={duration:.2f}s"
        )

        traj_msg = JointTrajectory()
        traj_msg.joint_names = self.joint_names

        pt = JointTrajectoryPoint()
        pt.positions = list(target_q)

        dur_msg = Duration()
        dur_msg.sec = int(duration)
        dur_msg.nanosec = int((duration - int(duration)) * 1e9)
        pt.time_from_start = dur_msg

        traj_msg.points.append(pt)

        # 发布轨迹
        self.pub.publish(traj_msg)

        # 粗略等待执行完成（简单暴力但好用）
        wait_time = duration + 0.5
        self.get_logger().info(f"Waiting ~{wait_time:.2f}s for reset motion to finish.")
        time.sleep(wait_time)

        self.get_logger().info("Reset motion finished.")


    def get_current_state(self, timeout=None) -> JointState:
        event = Event()
        result = {}

        def cb(msg):
            result['msg'] = msg
            event.set()

        sub = self.create_subscription(JointState, "/mk1000/joint_states", cb, 10)

        start = self.get_clock().now()
        # 循环 spin_once，直到收到消息或超时
        while rclpy.ok():
            # 处理一次回调，最多阻塞 0.1 秒
            rclpy.spin_once(self, timeout_sec=0.1)
            if event.is_set():
                break

            now = self.get_clock().now()
            if (now - start).nanoseconds > timeout * 1e9:
                break

        self.destroy_subscription(sub)

        if not event.is_set():
            self.get_logger().error(
                f"Timeout waiting for /mk1000/joint_states (timeout={timeout}s)"
            )
            return None

        return result["msg"]
    
    def ik_fun(self, target_endmat_arm, q_seed) -> List:
        ee_pose_arm = convert.rotmat2posequat(target_endmat_arm)
        # 构造 PoseStamped
        pose = PoseStamped()
        pose.header.frame_id = self.base_frame
        pose.header.stamp = self.get_clock().now().to_msg()

        pose.pose.position.x = ee_pose_arm[0]
        pose.pose.position.y = ee_pose_arm[1]
        pose.pose.position.z = ee_pose_arm[2]

        pose.pose.orientation.x = ee_pose_arm[3]
        pose.pose.orientation.y = ee_pose_arm[4]
        pose.pose.orientation.z = ee_pose_arm[5]
        pose.pose.orientation.w = ee_pose_arm[6]

        # 构造 IK 请求
        req = GetPositionIK.Request()
        req.ik_request.avoid_collisions = False
        req.ik_request.group_name = self.group_name
        req.ik_request.pose_stamped = pose
        req.ik_request.ik_link_name = self.ik_link_name
        # req.ik_request.attempts = 5
        req.ik_request.timeout.sec = 0
        req.ik_request.timeout.nanosec = int(0.05 * 1e9)  # 50ms

        if q_seed is not None:
            req.ik_request.robot_state.joint_state.name = self.joint_names
            req.ik_request.robot_state.joint_state.position = q_seed

        # 同步调用服务
        future = self.client.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=2.0)

        if future.result() is None:
            self.get_logger().error(f"IK service call failed with {target_endmat_arm=}")
            rclpy.shutdown()
            return

        res = future.result()
        if res is None:
            self.get_logger().error(f"IK service call returned None with {target_endmat_arm=}")
            rclpy.shutdown()
            return

        # 检查返回的 error_code
        if res.error_code.val != res.error_code.SUCCESS:
            self.get_logger().warn(
                f"IK failed with {target_endmat_arm=}, error_code={res.error_code.val}. "
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

        return q_sol

    def apply(self, action: np.ndarray, gripper: float, current_endmat_camera=None) -> Tuple[np.ndarray, List]:
        """根据相机坐标系下的位姿进行控制"""
        # 获取当前机械臂状态
        self.app_idx += 1
        msg = self.get_current_state(timeout=5)
        if msg is None:
            self.get_logger().error("Failed to get current joint state, abort this step.")
            raise RuntimeError("No joint_states received")
        joints = list(msg.position)
        joints_rad = np.array(joints)
        if current_endmat_camera is None:
            self.ik_seed = joints_rad.tolist()
            current_endmat_arm = self.fk_arm(joints_rad)
            # print(f"Current: {current_endmat_arm}")
            current_endmat_camera = convert.arm2camera(current_endmat_arm, self.eyehand_path)
        #print(f"Current Camera: {current_endmat_camera}")
        # 获取delta
        delta_mat = convert.poseeuler2rotmat(action)
        # 计算目标位置
        delta_rot = delta_mat[:3, :3]
        delta_trans = delta_mat[:3, 3]
        target_endmat_camera = np.eye(4)
        target_endmat_camera[:3, :3] = delta_rot @ current_endmat_camera[:3, :3]  # Target rotation
        target_endmat_camera[:3, 3] = current_endmat_camera[:3, 3] + delta_trans # Target translation
        #print(f"Target Camera: {target_endmat_camera}")
        target_endmat_arm = convert.camera2arm(target_endmat_camera, self.eyehand_path)
        # 计算逆运动学
        sol_q = self.ik_fun(target_endmat_arm, self.ik_seed)
        self.ik_seed = sol_q
        gripper = 1 if gripper > 0.5 else 0
        # now = time.time()
        # if now - self.last_gripper_change_time > 3:
        #     if gripper != self.gripper_state:
        #         self.gripper_state = gripper
        #         self.last_gripper_change_time = now
        if ((self.app_idx - self.last_gripper_change_idx) > 3) and (gripper != self.gripper_state):
            self.gripper_state = gripper
            self.last_gripper_change_idx = self.app_idx
            # if gripper == 1:
            #     send_message_to_local_host(close_text)
            # else:
            #     send_message_to_local_host(open_text)
        if self.gripper_state == -123:
            self.gripper_state = gripper
            self.last_gripper_change_idx = self.app_idx
        instruct = sol_q + [self.gripper_state]
        return np.array(instruct), joints, target_endmat_camera
    
    def send_gripper_command(self, gripper_state):
        msg = Float32()
        if gripper_state >= 0.5:
            msg.data = 1.0
            self.gripper_pub.publish(msg)
        else:
            msg.data = 0.0
            self.gripper_pub.publish(msg)
    
    def run(self, ):
        self.send_gripper_command(1.0)
        time.sleep(5.0)
        self.reset()
        self.get_logger().info(f"Loading CSV: {self.csv_path}")
        df = pd.read_csv(self.csv_path)
        dt_default = 0.2

        # 先根据 apply() 的输出把整条轨迹算出来，并按“夹爪状态变化”分段
        segments = []   # 每个元素: (q_list, seg_gripper)
        current_segment_qs = []
        current_segment_gripper = None

        current_endmat_camera = None

        for i, row in df.iterrows():
            action = np.array([row["action_x"],row["action_y"],row["action_z"],row["action_roll"],row["action_pitch"],row["action_yaw"]])
            gripper = row["Gripper"]

            instruct, previous_state, current_endmat_camera = self.apply(action, gripper, current_endmat_camera)
            # instruct: [q1..q7, gripper_state]
            q = instruct[:-1]
            g_state = instruct[-1]

            # 初始化第一段
            if current_segment_gripper is None:
                current_segment_gripper = g_state

            # 如果夹爪状态发生改变，则关闭上一段、开启新的一段
            if g_state != current_segment_gripper and len(current_segment_qs) > 0:
                segments.append((current_segment_qs, current_segment_gripper))
                current_segment_qs = [q]
                current_segment_gripper = g_state
            else:
                current_segment_qs.append(q)

        # 收尾，把最后一段加进去
        if len(current_segment_qs) > 0:
            segments.append((current_segment_qs, current_segment_gripper))

        self.get_logger().info(f"Total {len(segments)} trajectory segments split by gripper state changes.")

        if len(segments) == 0:
            self.get_logger().warn("No valid trajectory segments, aborting.")
            return

        first_gripper_state = segments[0][1]
        self.get_logger().info(f"Initializing gripper to state {first_gripper_state}.")
        self.send_gripper_command(first_gripper_state)
        time.sleep(1.5)  # 等夹爪动作一下

        for idx, (q_list, seg_gripper) in enumerate(segments):
            self.get_logger().info(
                f"Playing segment {idx+1}/{len(segments)}, "
                f"{len(q_list)} points, seg_gripper={seg_gripper}"
            )

            traj_msg = JointTrajectory()
            traj_msg.joint_names = self.joint_names

            # 构造这一段的 JointTrajectoryPoint
            t_accum = 0.0
            for step_i, q in enumerate(q_list):
                dt = dt_default

                t_accum += dt

                pt = JointTrajectoryPoint()
                pt.positions = list(q)

                dur_msg = Duration()
                dur_msg.sec = int(t_accum)
                dur_msg.nanosec = int((t_accum - int(t_accum)) * 1e9)
                pt.time_from_start = dur_msg

                traj_msg.points.append(pt)

            # 发布这一段轨迹
            self.pub.publish(traj_msg)

            # 粗略等待这段轨迹执行完
            wait_time = t_accum + 0.5  # 多给一点冗余
            self.get_logger().info(
                f"Waiting ~{wait_time:.2f}s for segment {idx+1} to finish."
            )
            time.sleep(wait_time)

            # 如果还有下一段，则在两段之间切换夹爪状态，并等待夹爪动作完成
            if idx < len(segments) - 1:
                next_gripper_state = segments[idx + 1][1]
                if next_gripper_state != seg_gripper:
                    self.get_logger().info(
                        f"Segment {idx+1} finished, switching gripper to {next_gripper_state}."
                    )
                    self.send_gripper_command(next_gripper_state)
                    # 根据实际夹爪动作时间调这个值
                    time.sleep(2.0)
                else:
                    self.get_logger().info(
                        f"Segment {idx+1} finished, gripper state unchanged ({seg_gripper}), no command sent."
                    )

        self.get_logger().info("All trajectory segments and gripper actions finished.")
        self.send_gripper_command(1.0)


if __name__ == "__main__":
    rclpy.init()
    node = Actor()

    try:
        node.run()
    except KeyboardInterrupt:
        node.get_logger().info("Trajectory playback interrupted by user (Ctrl+C).")
    finally:
        # 清理节点、关闭 rclpy
        node.destroy_node()
        rclpy.shutdown()