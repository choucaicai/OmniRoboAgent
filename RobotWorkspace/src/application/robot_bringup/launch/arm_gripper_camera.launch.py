import os
import xacro
from launch import LaunchDescription
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    Shutdown,
)
from launch.substitutions import (
    Command,
    FindExecutable,
    LaunchConfiguration,
    PathJoinSubstitution,
)
from launch.launch_description_sources import PythonLaunchDescriptionSource

from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    return LaunchDescription(
        [
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [
                        PathJoinSubstitution(
                            [
                                FindPackageShare("mk1000_franka_fr3_moveit_config"),
                                "launch",
                                "franka_drivers.launch.py",
                            ]
                        )
                    ]
                )
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    PathJoinSubstitution(
                        [
                            FindPackageShare("realsense2_camera"),
                            "launch",
                            "rs_launch.py",
                        ]
                    )
                ),
                launch_arguments={
                    "serial_no": '"339222070579"',
                    "camera_name": "camera",
                    "camera_namespace": "pc_arm",
                    "publish_tf": "false",
                    "enable_color": "true",
                    "enable_depth": "true",
                    "pointcloud.enable": "true",
                    "align_depth.enable": "true",
                    "rgb_camera.color_profile": "640,480,30",
                }.items(),
                # launch_arguments={
                #     "serial_no": '"344422300343"',
                #     "camera_name": "body_camera",
                #     "camera_namespace": "pc_arm",
                #     "publish_tf": "false",
                #     "enable_color": "true",
                #     "enable_depth": "true",
                #     "pointcloud.enable": "true",
                #     "align_depth.enable": "true",
                #     "rgb_camera.color_profile": "1280,720,30",
                # }.items(),
            ),
        ]
    )
