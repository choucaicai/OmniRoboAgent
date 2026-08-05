#!/usr/bin/env python3
import os
import datetime
from pathlib import Path

import numpy as np
import cv2
from PIL import Image

import rclpy
from rclpy.node import Node

from sensor_msgs.msg import Image as ImageMsg
from sensor_msgs.msg import JointState

from cv_bridge import CvBridge

from urchin import URDF
import urchin

import pyrender
from pyrender import MetallicRoughnessMaterial
import tempfile


class CalibRender:
    def __init__(
        self,
        urdf_path=f"{os.environ['WORKDIR']}/src/robot/mr1000_description/urdf/robot.urdf",
        intrinsic_path=f"{os.environ['WORKDIR']}/data/calib/intrinsic/results_344422300343",
        cam2base_path=f"{os.environ['WORKDIR']}/data/calib/eyehand/results_11_28/cam2base_4x4.npy",
    ):
        # ---- 关键修改：处理 package:// 路径 ----
        urdf_path = Path(urdf_path).expanduser().resolve()

        # /home/rpp/rpp_ws/src/robot/mr1000_description/urdf/robot.urdf
        # parents[0] = .../urdf
        # parents[1] = .../mr1000_description  -> 这个就是 package 根路径
        mr1000_pkg_root = urdf_path.parents[1]   # -> /home/.../mr1000_description
        franka_pkg_root = Path("/home/rpp/rpp_ws/install/franka_description/share/franka_description")
        realsense_pkg_root = Path("/home/rpp/rpp_ws/install/realsense2_description/share/realsense2_description")


        # 用一个临时文件把 package:// 前缀替换成绝对路径
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_urdf = Path(tmpdir) / urdf_path.name
            with open(urdf_path, "r") as fin, open(tmp_urdf, "w") as fout:
                for line in fin:
                    # 1) 自己的机器人包
                    line = line.replace("package://mr1000_description/", str(mr1000_pkg_root) + "/",)

                    # 2) Franka 机械臂包
                    line = line.replace("package://franka_description/", str(franka_pkg_root) + "/",)

                    # 3) Realsense 相机包
                    line = line.replace("package://realsense2_description/", str(realsense_pkg_root) + "/",)

                    # 4) 把 file:// 绝对路径改成普通绝对路径
                    #    filename="file:///home/..." -> filename="/home/..."
                    line = line.replace('filename="file://', 'filename="')

                    fout.write(line)

            # 这里再用 urchin 加载已经“替换好路径”的 urdf
            self.robot_model: URDF = URDF.load(str(tmp_urdf))

        # 场景
        self.scene = pyrender.Scene()

        # 相机内参
        self.K = np.load(Path(intrinsic_path) / "mtx.npy")  # 3x3
        self.dist = np.load(Path(intrinsic_path) / "dist.npy")  # 畸变系数

        fx, fy = self.K[0, 0], self.K[1, 1]
        cx, cy = self.K[0, 2], self.K[1, 2]
        self.camera = pyrender.IntrinsicsCamera(fx, fy, cx, cy)

        # 相机到 base 的变换
        self.cam2base = np.load(cam2base_path)  # 4x4
        # OpenCV -> OpenGL 坐标系
        self.cv2gl = np.diag([1, -1, -1, 1])
        self.camera_pose = self.cam2base @ self.cv2gl  # 4×4 numpy

        self.light = pyrender.DirectionalLight(color=[1, 1, 1], intensity=5.0)

    def render_robot(self, joints_rad, width=1280, height=720):
        """在 pyrender 里渲染机械臂轮廓，返回 color, depth"""
        self.scene.clear()

        # FK：得到所有 link 位姿
        joint_angles = {
            "mk1000_fr3_joint1": joints_rad[0],
            "mk1000_fr3_joint2": joints_rad[1],
            "mk1000_fr3_joint3": joints_rad[2],
            "mk1000_fr3_joint4": joints_rad[3],
            "mk1000_fr3_joint5": joints_rad[4],
            "mk1000_fr3_joint6": joints_rad[5],
            "mk1000_fr3_joint7": joints_rad[6],
        }
        link_poses = self.robot_model.link_fk(cfg=joint_angles)

        # 把每个 link 的 mesh 加到场景里
        for link, pose in link_poses.items():
            if link.visuals:
                for visual in link.visuals:
                    visual_mesh = visual.geometry.mesh
                    if isinstance(visual_mesh, urchin.Mesh):
                        try:
                            trimesh_list = visual_mesh.meshes
                            if not isinstance(trimesh_list, list):
                                trimesh_list = [trimesh_list]

                            for mesh in trimesh_list:
                                mesh = mesh.copy()
                                # 视觉原点变换
                                mesh.apply_transform(visual.origin)
                                # link 位姿
                                mesh.apply_transform(pose)

                                red_mat = MetallicRoughnessMaterial(
                                    baseColorFactor=[1.0, 0.0, 0.0, 1.0]
                                )
                                render_mesh = pyrender.Mesh.from_trimesh(
                                    mesh, material=red_mat, wireframe=True
                                )
                                self.scene.add(render_mesh)
                        except Exception as e:
                            print(
                                f"[ERROR] Failed to load/render mesh for {link.name}: {e}"
                            )

        # 加相机和光源
        self.scene.add(self.camera, pose=self.camera_pose)
        self.scene.add(self.light, pose=self.camera_pose)

        r = pyrender.OffscreenRenderer(width, height)
        color, depth = r.render(self.scene)
        r.delete()
        return color, depth

    def overlay_and_save(self, raw_img_bgr, color, depth, save_path):
        """去畸变真实图像 + 叠加渲染边缘，保存"""
        # 使用 depth 做 mask，然后 Canny 提边缘
        mask = (depth > 0).astype(np.uint8) * 255
        edges = cv2.Canny(mask, threshold1=50, threshold2=150)

        # 去畸变
        raw_img_undistorted = cv2.undistort(raw_img_bgr, self.K, self.dist)

        # 对齐大小并转为 RGB 存盘
        raw_img_undistorted = cv2.resize(
            raw_img_undistorted, (color.shape[1], color.shape[0])
        )
        raw_img_undistorted[edges != 0] = [0, 0, 255]  # 在 BGR 下是红色

        img_rgb = cv2.cvtColor(raw_img_undistorted, cv2.COLOR_BGR2RGB)
        Image.fromarray(img_rgb).save(save_path)
        print(f"[INFO] Saved overlay image to: {save_path}")


class CalibRenderNode(Node):
    def __init__(self):
        super().__init__("calib_render_node")

        self.bridge = CvBridge()
        self.renderer = CalibRender()

        self.image_msg = None
        self.joint_state_msg = None
        self.done = False

        # 订阅相机和 joint_states
        self.image_sub = self.create_subscription(
            ImageMsg,
            "/pc_arm/body_camera/color/image_raw",
            self.image_callback,
            10,
        )

        self.joint_sub = self.create_subscription(
            JointState,
            "/arm/right/joint_states",
            self.joint_callback,
            10,
        )

        self.get_logger().info("CalibRenderNode started, waiting for image & joint_states...")

    def image_callback(self, msg: ImageMsg):
        if self.done:
            return
        self.image_msg = msg
        self.try_process()

    def joint_callback(self, msg: JointState):
        if self.done:
            return
        self.joint_state_msg = msg
        self.try_process()

    def try_process(self):
        # 两个都有了就处理一次
        if self.image_msg is None or self.joint_state_msg is None:
            return

        self.get_logger().info("Received both image and joint_states, start rendering...")

        jointsAng = self.joint_state_msg.position
        joints_rad = np.deg2rad(np.array(jointsAng))

        color_render, depth_render = self.renderer.render_robot(
            joints_rad, width=1280, height=720
        )

        raw_img_bgr = self.bridge.imgmsg_to_cv2(self.image_msg, desired_encoding="bgr8")

        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_dir = f"{os.environ.get('WORKDIR', '.')}/data/calib/render_results"
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, f"render_{ts}.png")

        self.renderer.overlay_and_save(raw_img_bgr, color_render, depth_render, save_path)

        self.done = True
        self.get_logger().info("Done. Node will shut down.")


def main(args=None):
    rclpy.init(args=args)
    node = CalibRenderNode()

    # 简单 spin，直到 done
    try:
        while rclpy.ok() and not node.done:
            rclpy.spin_once(node, timeout_sec=0.1)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
