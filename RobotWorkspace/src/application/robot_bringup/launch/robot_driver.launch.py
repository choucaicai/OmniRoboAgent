import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import LogInfo
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch.actions import DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription, Shutdown
from launch.substitutions import Command, FindExecutable, LaunchConfiguration, PathJoinSubstitution
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.substitutions import FindPackageShare


def create_lidar_nodes():
    lidar_launch_file = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([PathJoinSubstitution([FindPackageShare("robot_bringup"), "launch", "lidar_bringup.launch.py"])])
    )
    return [
        lidar_launch_file,
    ]


def create_robot_nodes():
    robot_launch_file = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([PathJoinSubstitution([FindPackageShare("robot_bringup"), "launch", "load_robot_description.launch.py"])])
    )
    rpp_drive_launch_file = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([PathJoinSubstitution([FindPackageShare("robot_bringup"), "launch", "rpp_driver.launch.py"])])
    )
    return [rpp_drive_launch_file]


def create_parameters():
    use_2d_lidar = DeclareLaunchArgument("use_2d_lidar", default_value="True", description="是否使用2D雷达")
    use_3d_lidar = DeclareLaunchArgument("use_3d_lidar", default_value="True", description="是否使用3D雷达")
    livox_msg_type = DeclareLaunchArgument("livox_msg_type", default_value="0", description="livox_msg格式")

    return [use_2d_lidar, use_3d_lidar,livox_msg_type]


def generate_launch_description():
    parameters = create_parameters()

    lidar = create_lidar_nodes()
    robot = create_robot_nodes()
    ld = LaunchDescription()
    for node in parameters + lidar+robot :
        ld.add_action(node)
    return ld
