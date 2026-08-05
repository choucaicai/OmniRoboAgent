import os
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import LogInfo
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from ament_index_python.packages import get_package_share_directory
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch.conditions import IfCondition

# 声明全局变量
global_user_config_path = None


def get_default_value_user_config_path():
    global global_user_config_path
    package_name = "robot_bringup"
    package_path = get_package_share_directory(package_name)
    global_user_config_path = os.path.join(package_path, "params", "MID360_config.json")
    print(f"User config path is: {global_user_config_path}")


def create_livox_nodes(
    namespace: str = "/",
    lidar_name: str = "livox_node",
    frame_id: str = "lidar_link",
    # output_topic: str = 'front_laser', inverted: str = 'false', hostip: str = '192.168.11.11',
    # sensorip: str = '192.168.11.20', port: str = 2368, angle_offset: str = '0'
    xfer_format: str = "1",  # 0-Pointcloud2(PointXYZRTL), 1-customized pointcloud format
    multi_topic: str = "0",  # 0-All LiDARs share the same topic, 1-One LiDAR one topic
    data_src: str = "0",  # 0-lidar, others-Invalid data src
    publish_freq: str = "10.0",  # freqency of publish, 5.0, 10.0, 20.0, 50.0, etc.
    output_type: str = "0",
    lvx_file_path: str = "/home/livox/livox_test.lvx",
    cmdline_bd_code: str = "livox0000000001",
    user_config_path: str = global_user_config_path,  #
):
    """
    创建一个 livox_driver 雷达节点。
    """
    livox_driver = Node(
        package="livox_ros_driver2",
        executable="livox_ros_driver2_node",
        name=lidar_name,
        namespace=namespace,
        condition=IfCondition(LaunchConfiguration("use_3d_lidar")),
        parameters=[
            {"xfer_format": xfer_format},
            {"multi_topic": multi_topic},
            {"data_src": data_src},
            {"publish_freq": publish_freq},
            {"output_data_type": output_type},
            {"frame_id": frame_id},
            {"lvx_file_path": lvx_file_path},
            {"user_config_path": user_config_path},
            {"cmdline_input_bd_code": cmdline_bd_code},
        ],
        output="screen",
    )

    return [livox_driver]


def create_livox_parameter_name():
    """
    声明所有参数并返回参数声明的列表。
    """
    namespace = DeclareLaunchArgument("namespace", default_value="", description="每个雷达的命名空间，默认为根命名空间")

    lidar_name = DeclareLaunchArgument("lidar_name", default_value="livox_node", description="每个雷达的节点名")

    frame_id = DeclareLaunchArgument("frame_id", default_value="lidar_link", description="每个雷达所对应的坐标系")

    # output_topic = DeclareLaunchArgument(
    #     'output_topic',
    #     default_value='front_laser',
    #     description='每个雷达输出的话题名'
    # )

    # inverted = DeclareLaunchArgument(
    #     'inverted',
    #     default_value='false',
    #     description='配置是否倒装，true表示倒装'
    # )

    # hostip = DeclareLaunchArgument(
    #     'hostip',
    #     default_value='192.168.11.11',
    #     description='雷达对应的主机 IP 地址'
    # )

    # sensorip = DeclareLaunchArgument(
    #     'sensorip',
    #     default_value='192.168.11.20',
    #     description='雷达自身的 IP 地址'
    # )

    # port = DeclareLaunchArgument(
    #     'port',
    #     default_value='"2368"',
    #     description='雷达对应的端口，端口号不能重复'
    # )

    # angle_offset = DeclareLaunchArgument(
    #     'angle_offset',
    #     default_value='0',
    #     description='配置每个雷达点云的旋转角度，可以是负数'
    # )
    xfer_format = DeclareLaunchArgument("xfer_format", default_value="1", description="0-Pointcloud2(PointXYZRTL),1-自定义点云格式")
    multi_topic = DeclareLaunchArgument("multi_topic", default_value="0", description="0-所有 LiDAR 共享同一主题，1-一个 LiDAR 一个主题")
    data_src = DeclareLaunchArgument("data_src", default_value="0", description="0-激光雷达，其他-无效数据源")
    publish_freq = DeclareLaunchArgument("publish_freq", default_value="10.0", description="发布频率，5.0、10.0、20.0、50.0  hz等")
    output_type = DeclareLaunchArgument("output_type", default_value="0", description="输出数据类型，0 或其他")
    lvx_file_path = DeclareLaunchArgument("lvx_file_path", default_value="/home/livox/livox_test.lvx", description="LVX 文件路径，用于加载点云数据")
    cmdline_bd_code = DeclareLaunchArgument("cmdline_bd_code", default_value="livox0000000001", description="激光雷达板卡的代码")
    user_config_path = DeclareLaunchArgument("user_config_path", default_value=global_user_config_path, description="livox雷达的配置文件地址")
    use_3d_lidar = DeclareLaunchArgument("use_3d_lidar", default_value="true", description="是否启用 3D 雷达")
    return [
        namespace,
        lidar_name,
        frame_id,
        # output_topic, inverted, hostip, sensorip, port, angle_offset
        xfer_format,
        multi_topic,
        data_src,
        publish_freq,
        output_type,
        lvx_file_path,
        cmdline_bd_code,
        user_config_path,
        use_3d_lidar,
    ]


def generate_launch_description():
    """
    生成 Launch 描述，包含参数声明和节点启动。
    """
    lidar_model = DeclareLaunchArgument("lidar_model", default_value="lakibeam1", description="雷达类型选择，暂不启用")
    get_default_value_user_config_path()
    # 获取参数声明
    parameter_declarations = create_livox_parameter_name()
    # 从 LaunchConfiguration 获取参数值
    namespace = LaunchConfiguration("namespace")
    lidar_name = LaunchConfiguration("lidar_name")
    frame_id = LaunchConfiguration("frame_id")
    xfer_format = LaunchConfiguration("xfer_format")
    multi_topic = LaunchConfiguration("multi_topic")
    data_src = LaunchConfiguration("data_src")
    publish_freq = LaunchConfiguration("publish_freq")
    output_type = LaunchConfiguration("output_type")
    lvx_file_path = LaunchConfiguration("lvx_file_path")
    cmdline_bd_code = LaunchConfiguration("cmdline_bd_code")
    user_config_path = LaunchConfiguration("user_config_path")

    # 创建雷达节点
    nodes = create_livox_nodes(
        namespace=namespace,
        lidar_name=lidar_name,
        frame_id=frame_id,
        xfer_format=xfer_format,
        multi_topic=multi_topic,
        data_src=data_src,
        publish_freq=publish_freq,
        output_type=output_type,
        lvx_file_path=lvx_file_path,
        cmdline_bd_code=cmdline_bd_code,
        user_config_path=user_config_path,
    )

    ld = LaunchDescription()
    for node in parameter_declarations + nodes:
        ld.add_action(node)
    return ld
