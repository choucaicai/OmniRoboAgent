from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch_ros.actions import Node
from launch.substitutions import LaunchConfiguration
import os
import xacro
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    # Declare use_sim_time parameter
    use_sim_time = LaunchConfiguration("use_sim_time")
    declare_use_sim_time_cmd = DeclareLaunchArgument("use_sim_time", default_value="false", description="Use simulation (Gazebo) clock if true")

    # Define the URDF file location and process it using xacro
    robot_description_urdf = os.path.join(get_package_share_directory("mr1000_description"), "urdf", "robot.urdf.xacro")
    robot_description = xacro.process_file(robot_description_urdf).toxml()

    # Start the robot_state_publisher node
    start_robot_state_publisher_cmd = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        name="robot_state_publisher",
        output="screen",
        parameters=[{"use_sim_time": use_sim_time, "robot_description": robot_description}],
    )

    # Start the joint_state_publisher node
    join_state_publisher_cmd = Node(
        package="joint_state_publisher",
        executable="joint_state_publisher",
        name="joint_state_publisher",
        output="screen",
        parameters=[{"use_sim_time": use_sim_time}],
    )

    # Define the RViz config file and start RViz
    rviz_config_file = os.path.join(get_package_share_directory("mr1000_description"), "rviz", "rviz.rviz")
    start_rviz_cmd = Node(
        package="rviz2",
        executable="rviz2",
        name="rviz2_ursf_show",
        output="screen",
        parameters=[{"use_sim_time": use_sim_time}],
        arguments=["-d", rviz_config_file],
    )
    joint_state_publisher_gui_cmd = Node(
        package="joint_state_publisher_gui",
        executable="joint_state_publisher_gui",
        name="joint_state_publisher_gui",
        output="screen",
        parameters=[{"robot_description": robot_description}],
    )

    return LaunchDescription(
        [declare_use_sim_time_cmd, start_robot_state_publisher_cmd ]
    )


    return LaunchDescription(
        [declare_use_sim_time_cmd, start_robot_state_publisher_cmd, join_state_publisher_cmd, joint_state_publisher_gui_cmd, start_rviz_cmd]
    )
