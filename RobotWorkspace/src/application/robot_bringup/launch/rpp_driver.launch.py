from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, PythonExpression
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():
    config = PathJoinSubstitution(
        [
            FindPackageShare("robot_bringup"),
            "params",
            "rpp_ros_driver.yaml",
        ]
    )
    rpp_ros_driver_node = Node(
        package="rpp_ros_driver",
        executable="rpp_ros_driver_node",
        name="rpp_ros_driver",
        output="screen",
        parameters=[config],
    )
    return LaunchDescription(
        [
            rpp_ros_driver_node,
        ]
    )
