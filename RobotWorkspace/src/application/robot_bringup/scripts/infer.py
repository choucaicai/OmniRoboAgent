#!/usr/bin/env python3
# Model Inference Test
import pandas as pd
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from std_msgs.msg import Float32
from sensor_msgs.msg import JointState, CompressedImage, Image
from builtin_interfaces.msg import Duration
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint
from geometry_msgs.msg import PoseStamped
from moveit_msgs.srv import GetPositionIK
import cv2

from rclpy.qos import qos_profile_sensor_data
import threading

import os, time
from typing import Tuple, List
import convert
from convert import FkArm
import threading
from threading import Event
from PIL import Image as PILImage
import json
import requests
import io

def send_dangerous():
    """播报Dangerous"""
    url = 'http://192.168.3.14:5000/receive_message'
    data = {'message': "Dangerous! Be careful!"}
    requests.post(url, json=data)

def send_message_to_api_server(main_bytes, wrist_bytes, json_payload):
    """发送消息到API服务器"""
    # url = 'http://210.45.70.21:23035/api/inference'
    # url = 'http://210.45.70.21:45340/api/inference'
    url = 'http://210.45.70.21:36515/api/inference'

    files = {
        "main_images": ("main.jpg", io.BytesIO(main_bytes), "image/jpeg"),
        "wrist_images": ("wrist.jpg", io.BytesIO(wrist_bytes), "image/jpeg"),
        "json": ("data.json", io.BytesIO(json.dumps(json_payload).encode("utf-8")), "application/json"),
    }
    return requests.post(url, files=files, timeout=(3, 120))


class Infer(Node):
    def __init__(self):
        super().__init__("franka_trajectory_player")

        self.traj_topic = "/mk1000/fr3_arm_controller/joint_trajectory"
        self.eyehand_path = f"{os.environ['WORKDIR']}/data/calib/eyehand/results_12_23_344422300343/cam2base_4x4.npy"
        self.image_path = "/home/rpp/images"
        self.declare_parameter("urdf_path", f"{os.environ['WORKDIR']}/src/robot/mr1000_description/urdf/robot_arm_only.urdf")
        self.urdf_path = (self.get_parameter("urdf_path").get_parameter_value().string_value)

        # self.main_image_path = self.image_path + "/main"
        # self.wrist_image_path = self.image_path + "/wrist"
        # os.makedirs(self.main_image_path, exist_ok=True)
        # os.makedirs(self.wrist_image_path, exist_ok=True)

        # FK & IK prepare
        self.fk_arm = FkArm(self.urdf_path)
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

        # Prepare IK Service
        self.client = self.create_client(GetPositionIK, "/pc_arm/compute_ik")
        self.get_logger().info(f"Waiting for IK service: /pc_arm/compute_ik ...")
        if not self.client.wait_for_service(timeout_sec=10.0):
            self.get_logger().error("IK service not available. Is moveit.launch.py running?")
            rclpy.shutdown()
            return
        
        # Moving Control
        self.transition_duration = 1.0
        self.pub = self.create_publisher(JointTrajectory, self.traj_topic, 10)
        self.gripper_pub = self.create_publisher(Float32, "/gripper_control_signal", 10)

        self.app_idx = 0
        self.gripper_state = -123 # Gripper State Log for Lock
        self.last_gripper_change_idx = 0
        self.current_gripper = 1.0 # Current Gripper State

        # Inference Control
        self._lock = threading.Lock()
        self._main_msg = None
        self._wrist_msg = None

        self.cam_sub = self.create_subscription(
            CompressedImage,
            "/pc_arm/body_camera/color/image_raw/compressed",
            self._main_cb,
            qos_profile_sensor_data,   # 关键：适合相机
        )
        self.wrist_sub = self.create_subscription(
            CompressedImage,
            "/pc_arm/wrist_camera/color/image_raw/compressed",
            self._wrist_cb,
            qos_profile_sensor_data,
        )
        self.wrist_evt = threading.Event()

    def _main_cb(self, msg):
        with self._lock:
            self._main_msg = msg

    def _wrist_cb(self, msg):
        with self._lock:
            self._wrist_msg = msg

    def _get_latest_pair(self, timeout=1.0):
        """拿到两路最新帧；必要时等一小会儿直到都不为 None"""
        start = time.time()
        while time.time() - start < timeout:
            with self._lock:
                m = self._main_msg
                w = self._wrist_msg
            if m is not None and w is not None:
                return m, w
            time.sleep(0.005)
        raise RuntimeError("Timeout waiting for latest frames")


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
    
    # def get_main_image_callback(self, msg: CompressedImage):
    #     if self.get_main_image:
    #         if not getattr(self, "get_main_image", False):
    #             return

    #         timestamp_ms = msg.header.stamp.sec * 1000.0 + msg.header.stamp.nanosec / 1e6

    #         np_arr = np.frombuffer(msg.data, dtype=np.uint8)
    #         # 用 OpenCV 解码（得到 BGR）
    #         img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    #         if img_bgr is None:
    #             self.get_logger().error(f"Failed to decode CompressedImage (format={msg.format})")
    #             return
    #         # 转 RGB，交给 PIL 保存（也可以直接用 cv2.imwrite 存 BGR）
    #         img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    #         pil_image = PILImage.fromarray(img_rgb)

    #         out_path = os.path.join(self.main_image_path, f"frame_{timestamp_ms:.3f}.jpeg")
    #         pil_image.save(out_path, format="JPEG")

    #         self.get_logger().info(f"Image saved: {out_path} (format={msg.format})")

    #         self.main_evt.set()
    #         self.get_main_image = False


    # def get_wrist_image_callback(self, msg: CompressedImage):
    #     if self.get_wrist_image:
    #         if not getattr(self, "get_wrist_image", False):
    #             return

    #         timestamp_ms = msg.header.stamp.sec * 1000.0 + msg.header.stamp.nanosec / 1e6

    #         np_arr = np.frombuffer(msg.data, dtype=np.uint8)
    #         # 用 OpenCV 解码（得到 BGR）
    #         img_bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    #         if img_bgr is None:
    #             self.get_logger().error(f"Failed to decode CompressedImage (format={msg.format})")
    #             return
    #         # 转 RGB，交给 PIL 保存（也可以直接用 cv2.imwrite 存 BGR）
    #         img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    #         pil_image = PILImage.fromarray(img_rgb)

    #         out_path = os.path.join(self.wrist_image_path, f"frame_{timestamp_ms:.3f}.jpeg")
    #         pil_image.save(out_path, format="JPEG")

    #         self.get_logger().info(f"Image saved: {out_path} (format={msg.format})")

    #         self.wrist_evt.set()
    #         self.get_wrist_image = False
    
    def reset(self, target_q: List[float] = None, duration: float = None):
        reset_joint_state = np.array([-0.641, 0.128, 0.218, -2.265, 0.038, 2.485, 0.305]) # Cup & Bowl
        if target_q is None:
            target_q = reset_joint_state
        if duration is None:
            duration = 2.0  # 复位时间

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

        # 夹爪复位
        self.send_gripper_command(1.0)

        self.get_logger().info("Reset motion finished.")
    
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

    def apply(self, action: np.ndarray, gripper: float, current_endmat_camera=None) -> Tuple[np.ndarray, List, np.ndarray]:
        """根据相机坐标系下的位姿进行控制"""
        # 获取当前机械臂状态
        self.app_idx += 1
        msg = self.get_current_state(timeout=5)
        if msg is None:
            self.get_logger().error("Failed to get current joint state, abort this step.")
            raise RuntimeError("No joint_states received")
        joints = list(msg.position)
        joints_rad = np.array(joints[:7])
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
        return np.array(instruct), joints[:7], target_endmat_camera
    
    def send_gripper_command(self, gripper_state, sleep_time: float = 2.5):
        msg = Float32()
        if gripper_state >= 0.5:
            msg.data = 1.0
            self.gripper_pub.publish(msg)
        else:
            msg.data = 0.0
            self.gripper_pub.publish(msg)
        time.sleep(sleep_time)
    
    def infer(self, task_description: str):
        data = {
            # 'unnorm_key': "teledata",
            'task_description': task_description,
            #'task_description': 'Pick up the carambola.',
            #'task_description': "Put the carambola in the white plate.",
            # 'use_ddim': True,
            # 'write_log': False,
            # 'set_unnorm_stats': False,
            # 'unnorm_stats_file': None,
            # 'shift_to_left': 200,
            'exp_id': "1",
            # 'action_shift': 0
        }

        main_msg, wrist_msg = self._get_latest_pair(timeout=2.0)

        response = send_message_to_api_server(main_msg.data, wrist_msg.data, data)

        print("--------------------------------------------------")
        if response.status_code == 200:
            return response.json()

        print("Failed to get a response from the API")
        print(response.status_code, response.text)
        raise RuntimeError(f"API failed: {response.status_code}")
    
    def execute_chunk(self, chunk: pd.DataFrame):
        # 如果第一个动作的夹爪状态和当前不一致, 先单独执行第一个动作
        if chunk["Gripper"].iloc[0] != self.current_gripper:
            action = chunk.iloc[0]
            target_q = action.iloc[:7].to_numpy()
            traj_msg = JointTrajectory()
            traj_msg.joint_names = self.joint_names

            pt = JointTrajectoryPoint()
            pt.positions = target_q.tolist()

            dur_msg = Duration()
            dur_msg.sec = 0
            dur_msg.nanosec = int(0.2 * 1e9)
            pt.time_from_start = dur_msg
            traj_msg.points.append(pt)
            self.pub.publish(traj_msg)

            # 等待执行完成
            wait_time = 0.4
            self.get_logger().info(f"Waiting ~{wait_time:.2f}s for firsr action to finish.")
            time.sleep(wait_time)
            self.send_gripper_command(action["Gripper"])
            df = chunk.iloc[1:]
        else:
            df = chunk

        # 按夹爪状态变化分段
        segments = []   # 每个元素: (q_list, seg_gripper)
        current_segment_qs = []
        current_segment_gripper = None
        for i, row in df.iterrows():
            q = np.array([row["Joint1"],row["Joint2"],row["Joint3"],row["Joint4"],row["Joint5"],row["Joint6"],row["Joint7"]])
            g_state = row["Gripper"]

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

        # self.get_logger().info(f"Total {len(segments)} trajectory segments split by gripper state changes.")

        if len(segments) == 0:
            self.get_logger().warn("No valid trajectory segments, aborting.")
            return

        # first_gripper_state = segments[0][1]
        # self.get_logger().info(f"Initializing gripper to state {first_gripper_state}.")
        # self.send_gripper_command(first_gripper_state)

        for idx, (q_list, seg_gripper) in enumerate(segments):
            # self.get_logger().info(
            #     f"Playing segment {idx+1}/{len(segments)}, "
            #     f"{len(q_list)} points, seg_gripper={seg_gripper}"
            # )

            traj_msg = JointTrajectory()
            traj_msg.joint_names = self.joint_names

            # 构造这一段的 JointTrajectoryPoint
            t_accum = 0.0
            for step_i, q in enumerate(q_list):
                dt = 1.0
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
                else:
                    self.get_logger().info(
                        f"Segment {idx+1} finished, gripper state unchanged ({seg_gripper}), no command sent."
                    )
        
        self.current_gripper = chunk["Gripper"].iloc[-1]

        self.get_logger().info("Chunk Finished.")
    
    def run(self, ):
        re = input("Reset? 1 for yes, 0 for no\n")
        if re == '1':
            self.reset()
        else:
            pass

        dt_default = 0.2 # 执行频率, 默认5Hz

        s = int(input("How many times?\n")) # 一轮执行的推理次数
        # last_joints = np.array(self.get_current_state().position)
        # last_joints_with_gripper = np.append(last_joints, 0).reshape(1, -1)
        # instructs = pd.DataFrame(last_joints_with_gripper, columns=["joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "joint7", "gripper"])

        # task_list = ["Put the red block on the paper with '1'.", "Put the blue block on the paper with '2'.",
        #               "Put the green block on the paper with '7'."]
        # task_list = ["Pick up the yellow block.", "Put the yellow block on the green block.",
        #             "Pick up the blue block.", "Put the blue block on the orange block.",
        #             "Pick up the orange block.", "Put the orange block on the red block.",
        #             "Pick up the red block.", "Put the red block on the yellow block.",]
        #
        task_list  = ["Pick up the yellow cup.", "Place the yellow cup in the green cup.",
                      "Pick up the green cup.", "Place the green cup in the grey cup.",
                      "Pick up the grey cup.", "Place the blue cup into the yellow cup.",
                      "Pick up the yellow bowl.", "Place the yellow bowl into the white bowl.",
                      "Pick up the blue bowl.", "Place the blue bowl into the yellow bowl."]
        # task_list  = ["move to the pink cup.", "move to the yellow cup.",
        #               "move to the blue cup.", "move to the yellow bowl.",
        #               "move to the pink bowl.", "move to the blue bowl."]

        # task_list = ["Pick up the lemon.", "Put the lemon in the blue plate.",
        #              "Pick up the banana.", "Put the banana in the yellow plate.",
        #              "Pick up the green fruit.", "Put the green fruit in the blue plate.",]
        # task_list = ["Pick up the blue measuring tape.", "Put the blue measuring tape into the basket.",
        #              "Pick up the green mug.", "Put the green mug into the basket.",]
        # task_list = ["Pick up the building block.", "Put the building block on the other building block.",
        #             "Pick up the cylindrical wooden block.", "Put the cylindrical wooden block on the other cylindrical wooden block.",
        #             "Pick up the triangular wooden block.", "Put the triangular wooden block on the other triangular wooden block.",]
        # task_list = ["Pick up the eggplant.", "Put the eggplant in the yellow plate.",
        #             "Pick up the black trash bag.", "Put the black trash bag in the green plate.",
        #             "Pick up the white can.", "Put the white can into the basket.",]
        # task_list = ["Pick up the screwdriver.", "Put the screwdriver into the basket.",
        #         "Pick up the harmmer.", "Put the blue clip into the basket.",
        #         "Pick up the green fruit.", "Put the green fruit in the pink plate.",]
        # task_list = ["Pick up the yellow can.", "Put the yellow can into the basket.",
        #              "Pick up the red can.", "Put the red can into the basket.",
        #              "Pick up the orange can.", "Put the orange can into the basket.",
        #              "Pick up the white can.", "Put the white can into the basket.",
        #              "Pick up the green can.", "Put the green can into the basket.",]

        # Index begin with 1
        task = int(input("Task?\n"))
        while True:
            for i in range(s):
                print(f"-------Start to infer,Index {i+1} of {s}---------")
                task_description = task_list[task-1]
                print(f"Task: {task_description}")
                action_traj = self.infer(task_description)
                # print(action_traj)
                # action_traj = action_traj[0]
                # action = action_ensemble.ensemble_action(np.array(action_traj))
                actions = np.array(action_traj)
                # actions = actions[np.newaxis, :]
                target_endmat_camera = None
                instructs = []
                for t in range(2): # 2 means only the first 2 action in action chunk will be used
                    action = actions[t]
                    #action = actions
                    print(f"Action: {action}")
                    # break
                    instruct, previous_state, target_endmat_camera = self.apply(action[:6], action[6], target_endmat_camera)
                    #instruct, previous_state = actor.apply([0,0,0], [0,0.5,0], 0)
                    print("--------------------------------------------------")
                    print(f"Target joint{instruct}")
                    print(f"Previous joint angle{previous_state}")
                    flag = True
                    # Check Translational and Rotational changes
                    for i in range(3):
                        if np.abs(action[i]) > 0.03:
                            flag = False
                            print("Trans Dangerous!", i)
                            send_dangerous()
                            conti = int(input("Continue? 1 for yes, 0 for no\n"))
                            if conti == 0:
                                break
                            elif conti == 1:
                                flag = True
                                continue
                            else:
                                print("Invalid input")
                                break
                    for i in range(6):
                        if np.abs(instruct[i] - previous_state[i]) > 1.0:
                            flag = False
                            print("Joint Dangerous!", i)
                            send_dangerous()
                            conti = int(input("Continue? 1 for yes, 0 for no\n"))
                            if conti == 0:
                                break
                            elif conti == 1:
                                flag = True
                                continue
                            else:
                                print("Invalid input")
                                break
                    if flag:
                        instructs.append(instruct)
                    else:
                        break
                        #rospy.loginfo("Published")
                #s = input("Continue?")
                cols = [
                        "Joint1", "Joint2", "Joint3", "Joint4",
                        "Joint5", "Joint6", "Joint7", "Gripper"
                    ]
                df = pd.DataFrame(instructs, columns=cols)
                self.execute_chunk(df)
                #rospy.loginfo("Finished")
                #instructs.loc[len(instructs)] = instruct
            s = int(input("How many times?\n"))
            re = input("Reset? 1 for yes, 0 for no\n")
            if re == '1':
                self.reset()
            else:
                pass
            task = int(input("Task?\n"))


def spin_thread_fn(executor: SingleThreadedExecutor):
    executor.spin()


if __name__ == "__main__":
    rclpy.init()
    node = Infer()

    executor = SingleThreadedExecutor()
    executor.add_node(node)

    t = threading.Thread(target=spin_thread_fn, args=(executor,), daemon=True)
    t.start()

    try:
        node.run()
    except KeyboardInterrupt:
        node.get_logger().info("Trajectory playback interrupted by user (Ctrl+C).")
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()