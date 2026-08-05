#!/usr/bin/env python3
"""
ROS2 intrinsic calibration data collector

Usage example:
    # 1. 启动相机（以 RealSense 为例）
    ros2 launch robot_bringup arm_gripper_camera.py

    # 2. 运行本节点（可以用参数覆盖默认值）
    ros2 run robot_bringup prepare_cam_calibration_data \
        --ros-args \
        -p image_topic:=/pc_arm/body_camera/color/image_raw \
        -p output_dir:=/home/mozheng/RobotWorkspace/cam_calib_data \

    # 3. 在弹出的窗口中对准棋盘格，按键盘 'a' 保存图像
"""

import os
import cv2
import numpy as np
from typing import Tuple
import datetime

import rclpy
from rclpy.node import Node

from cv_bridge import CvBridge, CvBridgeError
from sensor_msgs.msg import Image, JointState


from urchin import URDF
from urchin.utils import matrix_to_xyz_rpy


# 棋盘格参数（和原脚本保持一致）
XX = 11  # 标定板长度方向角点数
YY = 8   # 标定板宽度方向角点数
L = 0.02 # 棋盘格一格边长（m），这里暂时只用于理解，不直接用在代码里


def _find_chessboard_corners(
    gray: np.ndarray,
    XX: int,
    YY: int,
    flags: int = cv2.CALIB_CB_ADAPTIVE_THRESH
           + cv2.CALIB_CB_FAST_CHECK
           + cv2.CALIB_CB_NORMALIZE_IMAGE,
    criteria: Tuple[int, int, float] = (
        cv2.TERM_CRITERIA_MAX_ITER | cv2.TERM_CRITERIA_EPS,
        30,
        0.001,
    ),
    winsize: Tuple[int, int] = (11, 11),
):
    """在灰度图中寻找并细化棋盘格角点"""
    ret, corners = cv2.findChessboardCorners(gray, (XX, YY), flags)
    if ret:
        corners2 = cv2.cornerSubPix(gray, corners, winsize, (-1, -1), criteria)
        return True, corners2
    else:
        return False, []


class CamIntrinsicDataCollector(Node):
    def __init__(self):
        super().__init__("prepare_cam_calibration_data")

        self.get_logger().info("Hello from ROS2 intrinsic calibration data collector!")

        # ---- 参数 ----
        self.declare_parameter("image_topic", "/pc_arm/body_camera/color/image_raw")
        # self.declare_parameter("joint_state_topic", "/joint_states")
        self.declare_parameter("output_dir", f"{os.environ['WORKDIR']}/data/calib/intrinsic/prepare_data_{datetime.date.today().month}_{datetime.date.today().day}_344422300343")
        # self.declare_parameter("urdf_path", "")
        # self.declare_parameter("use_fk", True)

        self.image_topic = (
            self.get_parameter("image_topic").get_parameter_value().string_value
        )
        # self.joint_state_topic = (
        #     self.get_parameter("joint_state_topic").get_parameter_value().string_value
        # )
        self.output_dir = (
            self.get_parameter("output_dir").get_parameter_value().string_value
        )
        # self.urdf_path = (
        #     self.get_parameter("urdf_path").get_parameter_value().string_value
        # )
        # self.use_fk = (
        #     self.get_parameter("use_fk").get_parameter_value().bool_value
        # )

        os.makedirs(self.output_dir, exist_ok=True)

        # ---- 状态变量 ----
        self.bridge = CvBridge()
        self.save_idx = 0
        # self.current_joint_angles = None
        # self.current_ee_xyzrpy = None
        # self.robot_model = None

        # ---- 加载 URDF（用于正解） ----
        # if self.use_fk and self.urdf_path:
        #     try:
        #         self.robot_model = URDF.load(self.urdf_path)
        #         self.get_logger().info(f"Loaded URDF model from: {self.urdf_path}")
        #     except Exception as e:
        #         self.get_logger().error(f"Failed to load URDF: {e}")
        #         self.robot_model = None
        # else:
        #     self.get_logger().info(
        #         "URDF path not set or use_fk:=false, will NOT compute ee xyzrpy."
        #     )

        # ---- 订阅话题 ----
        self.image_sub = self.create_subscription(
            Image,
            self.image_topic,
            self.image_callback,
            10,
        )
        # self.joint_sub = self.create_subscription(
        #     JointState,
        #     self.joint_state_topic,
        #     self.joint_states_callback,
        #     10,
        # )

        self.get_logger().info(
            f"Subscribed to image_topic: {self.image_topic}, "
            # f"joint_state_topic: {self.joint_state_topic}"
        )
        self.get_logger().info(
            f"Output dir: {self.output_dir}, press 'a' in the image window to save data."
        )

    # ---- 显示并在按下 'a' 时保存图像 + 关节 + ee pose ----
    def show_and_save_image(self, img: np.ndarray, img_draw: np.ndarray):
        cv2.imshow("Frame", img_draw)
        key = cv2.waitKey(3) & 0xFF
        if key == ord("a"):
            image_save_path = os.path.join(
                self.output_dir, f"{self.save_idx:04d}.png"
            )
            cv2.imwrite(image_save_path, img)
            self.get_logger().info(f"Saved image: {image_save_path}")

            # 保存关节角
            # if self.current_joint_angles is not None:
            #     joint_save_path = os.path.join(
            #         self.output_dir, f"{self.save_idx:04d}_angles.npy"
            #     )
            #     np.save(joint_save_path, np.array(self.current_joint_angles))
            #     self.get_logger().info(f"Saved joint angles: {joint_save_path}")

            # 保存 ee xyzrpy
            # if self.current_ee_xyzrpy is not None:
            #     ee_save_path = os.path.join(
            #         self.output_dir, f"{self.save_idx:04d}_xyzrpy.npy"
            #     )
            #     np.save(ee_save_path, np.array(self.current_ee_xyzrpy))
            #     self.get_logger().info(f"Saved ee xyzrpy: {ee_save_path}")

            self.save_idx += 1

    # ---- 图像回调 ----
    def image_callback(self, img_msg: Image):
        try:
            cv_image = self.bridge.imgmsg_to_cv2(img_msg, desired_encoding="bgr8")
        except CvBridgeError as e:
            self.get_logger().error(f"CvBridge Error: {e}")
            return

        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        ret, corners = _find_chessboard_corners(gray, XX, YY)

        img_draw = cv_image.copy()
        if ret:
            img_draw = cv2.drawChessboardCorners(
                cv_image.copy(), (XX, YY), corners, ret
            )

        # 显示并处理保存按键
        self.show_and_save_image(cv_image, img_draw)

    # ---- 关节状态回调 ----
    # def joint_states_callback(self, msg: JointState):
    #     jointsAng = msg.position
    #     self.current_joint_angles = jointsAng

    #     # 正解求末端位姿（xyzrpy）
    #     if self.robot_model is not None and self.use_fk:
    #         try:
    #             # 这里按照你原来的 joint 名称来写，如果不一致需要自己改
    #             fk = self.robot_model.link_fk(
    #                 cfg={
    #                     "joint1": jointsAng[0],
    #                     "joint2": jointsAng[1],
    #                     "joint3": jointsAng[2],
    #                     "joint4": jointsAng[3],
    #                     "joint5": jointsAng[4],
    #                     "joint6": jointsAng[5],
    #                     "joint7": jointsAng[6],
    #                 }
    #             )
    #             tf_link7 = fk[self.robot_model.links[-1]]
    #             self.current_ee_xyzrpy = matrix_to_xyz_rpy(tf_link7)
    #         except Exception as e:
    #             self.get_logger().warn(f"FK computation failed: {e}")
    #             self.current_ee_xyzrpy = None


def main(args=None):
    rclpy.init(args=args)
    node = CamIntrinsicDataCollector()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
