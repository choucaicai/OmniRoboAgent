#!/usr/bin/env python3
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import PathJoinSubstitution
from launch.actions import IncludeLaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    move_group_name = "mk1000_fr3_arm"
    calibration_type = "eye_in_hand"  # or "eye_to_hand"
    tracking_base_frame = "camera_color_optical_frame"  # 相机坐标系
    tracking_marker_frame = "aruco_marker_frame"  # 注意：aruco 默认是 marker_<id>
    robot_base_frame = "mk1000_fr3_link0"
    robot_effector_frame = "camera_bracket"  # 最好是挂载相机的地方
    marker_size_meters = 0.15  # April/Aruco 码实际边长（米）
    marker_id = 150
    # === easy_handeye2 主服务 ===
    handeye_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [
                    get_package_share_directory("easy_handeye2"),
                    "launch",
                    "calibrate.launch.py",
                ]
            )
        ),
        launch_arguments={
            "name": move_group_name,
            "calibration_type": calibration_type,
            "tracking_base_frame": tracking_base_frame,
            "tracking_marker_frame": tracking_marker_frame,
            "robot_base_frame": robot_base_frame,
            "robot_effector_frame": robot_effector_frame,
        }.items(),
    )

    # === aruco 标记检测节点 ===
    image_topic = "/pc_arm/camera/color/image_raw"
    camera_info_topic = "/pc_arm/camera/color/camera_info"

    aruco_marker_publisher = Node(
        package="aruco_ros",
        executable="single",
        name="aruco_marker_publisher",
        parameters=[
            {
                # "image_is_rectified": True,
                "marker_size": marker_size_meters,  # 强制为 double
                "reference_frame": tracking_base_frame,  # TF 父帧
                "marker_id": marker_id,
                "camera_frame": tracking_base_frame,  # 与图像消息 frame_id 一致
                "reference_frame": tracking_base_frame,
                "marker_frame": tracking_marker_frame,
                "corner_refinement": "LINES",  #'NONE', 'HARRIS', 'LINES', 'SUBPIX'
                # "publish_tf": True,
            }
        ],
        remappings=[
            ("/image", image_topic),
            ("/camera_info", camera_info_topic),
        ],
        output="screen",
    )

    return LaunchDescription(
        [
            handeye_launch,
            aruco_marker_publisher,
        ]
    )
