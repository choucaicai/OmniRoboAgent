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
from launch.conditions import IfCondition


def create_lakibeam1_nodes():
    front_lidar_2d_launch_file = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([PathJoinSubstitution([FindPackageShare("robot_bringup"), "launch", "lidar_2d.launch.py"])]),
        launch_arguments={
            "namespace": "/",
            "lidar_name": "lakibeam1_front_node",
            "frame_id": "laser_F_link",
            "output_topic": "front_laser",
            "inverted": "false",
            "hostip": "192.168.11.11",
            "sensorip": "192.168.11.20",
            "port": '"2368"',
            "angle_offset": "0",
        }.items(),
    )
    left_back_lidar_2d_launch_file = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([PathJoinSubstitution([FindPackageShare("robot_bringup"), "launch", "lidar_2d.launch.py"])]),
        launch_arguments={
            "namespace": "/",
            "lidar_name": "lakibeam1_left_back_node",
            "frame_id": "laser_LB_link",
            "output_topic": "left_back_laser",
            "inverted": "false",
            "hostip": "192.168.11.11",
            "sensorip": "192.168.11.21",
            "port": '"2369"',
            "angle_offset": "0",
        }.items(),
    )
    right_back_lidar_2d_launch_file = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([PathJoinSubstitution([FindPackageShare("robot_bringup"), "launch", "lidar_2d.launch.py"])]),
        launch_arguments={
            "namespace": "/",
            "lidar_name": "lakibeam1_right_back_node",
            "frame_id": "laser_RB_link",
            "output_topic": "right_back_laser",
            "inverted": "false",
            "hostip": "192.168.11.11",
            "sensorip": "192.168.11.22",
            "port": '"2370"',
            "angle_offset": "0",
        }.items(),
    )
    ira_laser = Node(
        package="ira_laser_tools",
        executable="laserscan_multi_merger",
        name="laserscan_multi_merger",
        output="screen",
        condition=IfCondition(LaunchConfiguration("use_2d_lidar")),
        parameters=[
            {"destination_frame": "base_link"},
            {"cloud_destination_topic": "/merged_cloud"},
            {"scan_destination_topic": "/scan_multi"},
            {"laserscan_topics": "/front_laser /left_back_laser /right_back_laser"},
            {"angle_min": -3.14},
            {"angle_max": 3.14},
            {"angle_increment": 0.001745329},
            {"scan_time": 0.0},
            {"range_min": 0.1},
            {"range_max": 30.0},
        ],
    )
    return [
        front_lidar_2d_launch_file,
        left_back_lidar_2d_launch_file,
        right_back_lidar_2d_launch_file,
        ira_laser,
    ]


def create_mid360():
    package_name = "robot_bringup"
    package_path = get_package_share_directory(package_name)
    user_config_path = os.path.join(package_path, "params", "MID360_config.json")
    livox_msg_type = LaunchConfiguration("livox_msg_type")
    lidar_3d_launch_file = IncludeLaunchDescription(
        PythonLaunchDescriptionSource([PathJoinSubstitution([FindPackageShare("robot_bringup"), "launch", "lidar_3d.launch.py"])]),
        launch_arguments={
            "namespace": "/",
            "lidar_name": "livox_node",
            "frame_id": "lidar_link",
            "xfer_format": livox_msg_type,
            "multi_topic": "0",
            "data_src": "0",
            "publish_freq": "10.0",
            "output_type": "0",
            "lvx_file_path": "/home/livox/livox_test.lvx",
            "cmdline_bd_code": "livox0000000001",
            "user_config_path": user_config_path,
        }.items(),
    )

    lidar_clipping = Node(
        package="lidar_clipping",
        executable="lidar_clipping",
        condition=IfCondition(LaunchConfiguration("use_3d_lidar")),
        parameters=[
            {"point_cloud_topic": PathJoinSubstitution([LaunchConfiguration("namespace"), "livox", "lidar"])},
            {"filtered_point_cloud_topic": PathJoinSubstitution([LaunchConfiguration("namespace"), "livox", "lidar_filtered"])},
            {"lidar_type": "livox"},  #
            {"max_x": 0.2},
            {"max_y": 0.4},
            {"max_z": 0.4},
            {"min_x": -0.65},
            {"min_y": -0.4},
            {"min_z": -0.1},
            {
                "qos_overrides": {
                    "/parameter_events": {"publisher": {"depth": 1000, "durability": "volatile", "history": "keep_last", "reliability": "reliable"}}
                }
            },
        ],
        output="screen",
    )
    return [lidar_3d_launch_file]


def generate_launch_description():
    use_2d_lidar = DeclareLaunchArgument("use_2d_lidar", default_value="True", description="是否使用2D雷达")

    use_3d_lidar = DeclareLaunchArgument("use_3d_lidar", default_value="False", description="是否使用3D雷达")

    livox_msg_type = DeclareLaunchArgument("livox_msg_type", default_value="0", description="livox_msg格式")

    lidar_2d = create_lakibeam1_nodes()
    lidar_3d = create_mid360()
    ld = LaunchDescription()
    ld.add_action(use_2d_lidar)
    ld.add_action(use_3d_lidar)
    ld.add_action(livox_msg_type)
    for node in lidar_2d + lidar_3d:
        ld.add_action(node)
    return ld
    # return LaunchDescription()
