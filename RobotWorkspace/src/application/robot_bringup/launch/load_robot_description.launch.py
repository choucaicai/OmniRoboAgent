import os
import xacro
from launch_ros.actions import Node
from launch import LaunchDescription
from launch_ros.parameter_descriptions import ParameterValue
from ament_index_python.packages import get_package_share_directory

def create_robot_nodes():
    dula_arm_robot_xacro_file = os.path.join(get_package_share_directory("mr1000_description"), "urdf", "robot.urdf.xacro")
    robot_description = xacro.process_file(dula_arm_robot_xacro_file, ).toprettyxml(indent='  ')
    robot_description_= {'robot_description': ParameterValue(robot_description, value_type=str)}
    robot_state_publisher= Node(
        package='robot_state_publisher',
        executable='robot_state_publisher',
        name='robot_state_publisher',
        output='screen',
        parameters=[{'robot_description': robot_description}],
        remappings=[('/tf', 'tf'),
            ('/tf_static', 'tf_static')]
    )
    joint_state_publisher = Node(
        package='joint_state_publisher',
        executable='joint_state_publisher',
        name='joint_state_publisher',
        parameters=[
            {'source_list': [ '/joint_states', "/left/joint_states", "/right/joint_states"], 'rate': 30}], #todo:改为分别接收作用的
    )
    return [
    robot_state_publisher,
    joint_state_publisher
    ]
def generate_launch_description():

    robot_nodes=create_robot_nodes()

    return LaunchDescription(robot_nodes)
