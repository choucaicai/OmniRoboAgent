import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import LogInfo
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch.conditions import IfCondition

def create_lakibeam1_nodes(namespace: str = '/', lidar_name: str = 'lakibeam1_node', frame_id: str = 'laser_link', 
                            output_topic: str = 'front_laser', inverted: str = 'false', hostip: str = '192.168.11.11', 
                            sensorip: str = '192.168.11.20', port: str = 2368, angle_offset: str = '0'):
    """
    创建一个 Lakibeam1 雷达节点。
    """
    lakibeam1_node = Node(
        package='lakibeam1',
        executable='lakibeam1_scan_node',
        namespace=namespace,
        name=lidar_name,
        condition=IfCondition(LaunchConfiguration('use_2d_lidar')),
        parameters=[{
            'frame_id': frame_id,
            'output_topic': output_topic,
            'inverted': inverted,
            'hostip': hostip,
            'sensorip': sensorip,
            'port': port,
            'angle_offset': angle_offset
        }],
        output='screen'
    )
    return lakibeam1_node

def create_lakibeam1_parameter_name():
    """
    声明所有参数并返回参数声明的列表。
    """
    namespace = DeclareLaunchArgument(
        'namespace',
        default_value='',
        description='每个雷达的命名空间，默认为根命名空间'
    )

    lidar_name = DeclareLaunchArgument(
        'lidar_name',
        default_value='lakibeam1_node',
        description='每个雷达的节点名'
    )

    frame_id = DeclareLaunchArgument(
        'frame_id',
        default_value='laser_link',
        description='每个雷达所对应的坐标系'
    )

    output_topic = DeclareLaunchArgument(
        'output_topic',
        default_value='front_laser',
        description='每个雷达输出的话题名'
    )

    inverted = DeclareLaunchArgument(
        'inverted',
        default_value='false',
        description='配置是否倒装，true表示倒装'
    )

    hostip = DeclareLaunchArgument(
        'hostip',
        default_value='192.168.11.11',
        description='雷达对应的主机 IP 地址'
    )

    sensorip = DeclareLaunchArgument(
        'sensorip',
        default_value='192.168.11.20',
        description='雷达自身的 IP 地址'
    )

    port = DeclareLaunchArgument(
        'port',
        default_value='"2368"',
        description='雷达对应的端口，端口号不能重复'
    )

    angle_offset = DeclareLaunchArgument(
        'angle_offset',
        default_value='0',
        description='配置每个雷达点云的旋转角度，可以是负数'
    )
    use_2d_lidar = DeclareLaunchArgument(
        'use_2d_lidar',
        default_value='true',
        description='是否启用 2D 雷达'
    )
    return [namespace, lidar_name, frame_id, output_topic, inverted, hostip, sensorip, port, angle_offset,use_2d_lidar]

def generate_launch_description():
    """
    生成 Launch 描述，包含参数声明和节点启动。
    """
    lidar_model = DeclareLaunchArgument(
        'lidar_model',
        default_value='lakibeam1',
        description='雷达类型选择，暂不启用'
    )

    # 获取参数声明
    parameter_declarations = create_lakibeam1_parameter_name()
    # 从 LaunchConfiguration 获取参数值
    namespace = LaunchConfiguration('namespace')
    lidar_name = LaunchConfiguration('lidar_name')
    frame_id = LaunchConfiguration('frame_id')
    output_topic = LaunchConfiguration('output_topic')
    inverted = LaunchConfiguration('inverted')
    hostip = LaunchConfiguration('hostip')
    sensorip = LaunchConfiguration('sensorip')
    port = LaunchConfiguration('port')
    angle_offset = LaunchConfiguration('angle_offset')
    print(lidar_name)
    # 创建雷达节点
    nodes = [
        create_lakibeam1_nodes(
            namespace=namespace,
            lidar_name=lidar_name,
            frame_id=frame_id,
            output_topic=output_topic,
            inverted=inverted,
            hostip=hostip,
            sensorip=sensorip,
            port=port,
            angle_offset=angle_offset
        )
    ]

    ld = LaunchDescription()
    for node in parameter_declarations + nodes:
        ld.add_action(node)
    return ld
