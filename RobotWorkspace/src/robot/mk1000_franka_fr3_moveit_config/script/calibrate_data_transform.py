#!/usr/bin/env python
# -*- coding:utf-8 -*-
"""
本程序为读取easy_handeye的标定结果，转换为可用的标定结果。
使用方法参考手眼标定文档
#标定结果为robot_effector_frame -> tracking_base_frame
############################################################################################
1.眼在手上TF流程:

              |<----------------------------   已知(标定结果[xyz,xyzw])(T4)   ------------------------>|
              |<------  求取(实际使用的TF)(T1)  ------>|<--------  已知(固定TF)(T2)  ------------------>|
            cam_p3    -------->   camera_bottom_screw_frame    -------->    camera_color_optical_frame
        (末端相机安装位置)            （相机底座螺丝孔）                            (相机rgb摄像头)

            计算公式：
            T1*T2=T4
            ==>  T1 = T4*(T2逆)

            T4=T2*T1
            T₁ = T₂⁻¹ · T₄，
并且
2.眼在手外TF流程:

              |<----------------------------  已知(标定结果[xyz,xyzw])(T4)   ----------------------------------------------->|
              |<------ 已知(固定TF)(T1) ------>|<----- 求取(实际使用的TF)(T2) ---->|<--------  已知(固定TF)(T3)  ------------->|
            arm_base    -------->   cam_fixed_p0    -------->   camera_bottom_screw_frame    -------->   camera_color_optical_frame
          (机械臂底座)             (车上相机安装位置)                  （相机底座螺丝孔）                         (相机rgb摄像头)

            计算公式：
            T1*T2*T3=T4
            ==>  T2 = (T1逆)*T4*(T3逆)
############################################################################################
以上内容【求取】才是实际使用的标定值 (TF值,四元数需要转换成rpy,方可写入urdf文件) ,需要使用本程序计算出来.

"""


import os
import yaml
import numpy as np

np.set_printoptions(suppress=True)

import rclpy
from rclpy.node import Node
from rclpy.time import Time
from rclpy.duration import Duration
from tf2_ros import Buffer, TransformListener
from geometry_msgs.msg import TransformStamped
from tf_transformations import (
    quaternion_matrix,
    quaternion_from_matrix,
    euler_from_quaternion,
)
from geometry_msgs.msg import TransformStamped, Transform, Vector3, Quaternion
import yaml, os, numpy as np
import transforms3d as tfs
from tf2_ros import TransformException, StaticTransformBroadcaster
from tf_transformations import (
    euler_from_quaternion,
    quaternion_from_euler,
    quaternion_matrix,
    quaternion_from_matrix,
    inverse_matrix,
    concatenate_matrices,
)


def rt2matrix(r_matrix, t_vector):
    """构造4x4变换矩阵"""
    t_vector = np.array(t_vector).flatten()
    return np.vstack(
        [np.hstack([r_matrix, t_vector[:, np.newaxis]]), np.array([0, 0, 0, 1])]
    )


def pose2matrix(pose):
    """[x, y, z, roll, pitch, yaw] -> 4x4矩阵"""
    tx, ty, tz, rx, ry, rz = pose
    r_matrix = tfs.euler.euler2mat(rx, ry, rz, axes="sxyz")
    t_vector = [tx, ty, tz]
    return rt2matrix(r_matrix, t_vector)


# ---------- 读取 easy_handeye2 标定 ----------


def load_eh2_calib_as_ts(path: str) -> TransformStamped:
    """把 easy_handeye2 的 *.calib 读成 TransformStamped（和官方 publisher 一致）"""
    with open(os.path.expanduser(path), "r", encoding="utf-8") as f:
        d = yaml.safe_load(f)

    params = d["parameters"]
    # 眼在手上：parent=robot_effector_frame；眼在手外：parent=robot_base_frame
    if str(params["calibration_type"]) == "eye_in_hand":
        orig = str(params["robot_effector_frame"])
    else:
        orig = str(params["robot_base_frame"])
    dest = str(params["tracking_base_frame"])
    robot_base_frame = str(params["robot_base_frame"])
    # easy_handeye2 的 transform 在顶层：transform:{translation:{x,y,z}, rotation:{x,y,z,w}}
    t = d["transform"]
    ts = TransformStamped()
    ts.header.frame_id = orig  # parent
    ts.child_frame_id = dest  # child
    ts.transform = Transform(
        translation=Vector3(
            x=float(t["translation"]["x"]),
            y=float(t["translation"]["y"]),
            z=float(t["translation"]["z"]),
        ),
        rotation=Quaternion(
            x=float(t["rotation"]["x"]),
            y=float(t["rotation"]["y"]),
            z=float(t["rotation"]["z"]),
            w=float(t["rotation"]["w"]),
        ),
    )
    return dest, orig, robot_base_frame, ts


# ---------- 节点 ----------


class HandeyeIHToURDF(Node):
    def __init__(self):
        super().__init__("handeye_converter")

        # 标定文件与安装基座帧（螺丝孔）
        self.declare_parameter(
            "calib_path",
            os.path.expanduser(
                "~/.ros2/easy_handeye2/calibrations/mk1000_fr3_arm.calib"
            ),
        )
        self.declare_parameter("camera_mount_frame", "camera_bottom_screw_frame")  # M

        calib_path = self.get_parameter("calib_path").get_parameter_value().string_value
        self.camera_base_frame = (
            self.get_parameter("camera_mount_frame").get_parameter_value().string_value
        )

        (
            self.camera_optical_frame,
            self.robot_effector_frame,
            self.robot_base_frame,
            self.T4_ts,
        ) = load_eh2_calib_as_ts(calib_path)
        self.T4 = self.transform_to_matrix(self.T4_ts)

        # 初始化TF工具
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.tf_broadcaster = StaticTransformBroadcaster(self)  # 静态TF发布器
        # 运行主逻辑
        self.process_calibration()

    def get_transform(self, target_frame, source_frame):
        """坐标变换获取"""
        retry_count = 5
        timeout_sec = 3.0

        for i in range(retry_count):
            try:
                self.get_logger().debug(
                    f"尝试获取变换 {source_frame}->{target_frame} ({i + 1}/{retry_count})"
                )

                transform = self.tf_buffer.lookup_transform(
                    target_frame,
                    source_frame,
                    rclpy.time.Time(),
                    timeout=rclpy.duration.Duration(seconds=timeout_sec),
                )
                return self.transform_to_matrix(transform)

            except TransformException as ex:
                if i == retry_count - 1:
                    self.get_logger().error(f"TF获取失败: {ex}")
                    raise
                else:
                    self.get_logger().warn(f"TF获取失败，正在重试... ({ex})")
                    rclpy.spin_once(self, timeout_sec=1.0)

    @staticmethod
    def transform_to_matrix(transform):
        """将TransformStamped转换为4x4齐次矩阵"""
        t = transform.transform.translation
        r = transform.transform.rotation

        translation = np.array([t.x, t.y, t.z])
        rotation = quaternion_matrix([r.x, r.y, r.z, r.w])
        rotation[:3, 3] = translation
        return rotation

    def publish_static_tf(self, frame_from, frame_to, position, quaternion):
        """发布静态TF"""
        try:
            transform_msg = TransformStamped()

            # 设置消息头
            transform_msg.header.stamp = self.get_clock().now().to_msg()
            transform_msg.header.frame_id = frame_from
            transform_msg.child_frame_id = frame_to

            # 设置平移
            transform_msg.transform.translation.x = position[0]
            transform_msg.transform.translation.y = position[1]
            transform_msg.transform.translation.z = position[2]

            # 设置旋转
            transform_msg.transform.rotation.x = quaternion[0]
            transform_msg.transform.rotation.y = quaternion[1]
            transform_msg.transform.rotation.z = quaternion[2]
            transform_msg.transform.rotation.w = quaternion[3]

            # 发布静态TF
            self.tf_broadcaster.sendTransform(transform_msg)
            self.get_logger().info(
                f"已发布静态TF: {transform_msg.header.frame_id} -> {transform_msg.child_frame_id}"
            )

        except Exception as e:
            self.get_logger().error(f"TF发布失败: {str(e)}")

    def process_calibration(self):
        """主处理逻辑"""
        mode = "hand"
        T4 = self.T4

        if mode == "hand":
            self.process_eye_in_hand(T4)
        elif mode == "base":
            self.process_eye_to_hand(T4)
        else:
            self.get_logger().error(f"Invalid mode: {mode}")

    def process_eye_in_hand(self, T4):
        """眼在手上模式计算"""
        # 获取相机安装架到光学相机的变换
        T2 = self.get_transform(  # 这里直接取逆
            self.camera_base_frame, self.camera_optical_frame
        )

        if T2 is not None:
            # 计算最终变换: T1 = T4 * inv(T2)
            T1 = np.dot(T4, inverse_matrix(T2))

            # 提取结果
            position = T1[:3, 3]
            quat = quaternion_from_matrix(T1)
            rpy = euler_from_quaternion(quat, axes="rxyz")
            roll, pitch, yaw = euler_from_quaternion(quat, axes="sxyz")

            self.print_result(
                frame_from=self.robot_effector_frame,
                frame_to=self.camera_base_frame,
                position=position,
                quaternion=quat,
                rpy_rad=(roll, pitch, yaw)
            )

    def process_eye_to_hand(self, T4):
        """眼在手外模式计算"""
        # 获取机械臂基座到相机安装架的变换
        T1 = self.get_transform(
            self.get_parameter("camera_mount_frame").value,
            self.get_parameter("robot_base_frame").value,
        )

        # 获取相机基座到光学相机的变换
        T3 = self.get_transform(
            self.get_parameter("camera_optical_frame").value,
            self.get_parameter("camera_base_frame").value,
        )

        if T1 is not None and T3 is not None:
            # 计算最终变换: T2 = inv(T1) * T4 * inv(T3)
            T2 = np.dot(np.dot(inverse_matrix(T1), T4), inverse_matrix(T3))

            # 提取结果
            position = T2[:3, 3]
            quat = quaternion_from_matrix(T2)
            rpy = euler_from_quaternion(quat, axes="rxyz")

            self.print_result(
                frame_from=self.get_parameter("camera_mount_frame").value,
                frame_to=self.get_parameter("camera_base_frame").value,
                position=position,
                quaternion=quat,
                rpy=np.degrees(rpy),
            )

    def print_result(self, frame_from, frame_to, position, quaternion, rpy_rad):
        rx, ry, rz = rpy_rad
        rpy_deg = np.degrees([rx, ry, rz])
        origin_line = (
            f'<origin xyz="{position[0]:.8f} {position[1]:.8f} {position[2]:.8f}" '
            f'rpy="{rx:.15f} {ry:.15f} {rz:.15f}"/>'
        )

        self.get_logger().warn(
            "\n======== 标定结果（眼在手上） ========\n"
            f"写入 URDF 的安装位姿:  {frame_from} -> {frame_to}\n"
            f"xyz(m) = [{position[0]:.6f}, {position[1]:.6f}, {position[2]:.6f}]\n"
            f"quat(xyzw) = [{quaternion[0]:.6f}, {quaternion[1]:.6f}, {quaternion[2]:.6f}, {quaternion[3]:.6f}]\n"
            f"rpy_rad(sxyz) = [{rx:.9f}, {ry:.9f}, {rz:.9f}]\n"
            f"rpy_deg(sxyz) = [{rpy_deg[0]:.3f}, {rpy_deg[1]:.3f}, {rpy_deg[2]:.3f}]\n"
            "—— 直接粘贴到 URDF/xacro:\n"
            f"  {origin_line}\n"
            "=====================================\n"
        )
        #self.publish_static_tf(frame_from, frame_to, position, quaternion)


def main(args=None):
    rclpy.init(args=args)
    node = HandeyeIHToURDF()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
