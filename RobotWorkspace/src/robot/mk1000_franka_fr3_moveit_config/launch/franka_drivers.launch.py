import os
from launch.actions import LogInfo, TimerAction
import xacro
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    ExecuteProcess,
    IncludeLaunchDescription,
    Shutdown,
)
from launch.conditions import UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import (
    Command,
    FindExecutable,
    LaunchConfiguration,
    PathJoinSubstitution,
)
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare

import yaml
import tempfile
from launch.conditions import IfCondition

from launch.actions import OpaqueFunction, TimerAction, ExecuteProcess
from launch.substitutions import LaunchConfiguration

robot_description_ = ""

def _resolve(val, context):
    """把 LaunchConfiguration 或字符串解析成最终字符串"""
    if isinstance(val, LaunchConfiguration):
        return val.perform(context)
    return str(val)


def franka_init_sequence(ns):
    from launch.actions import OpaqueFunction, TimerAction, ExecuteProcess
    from launch.substitutions import LaunchConfiguration

    def _resolve(val, context):
        if isinstance(val, LaunchConfiguration):
            return val.perform(context)
        return str(val)

    def _build(context, *args, **kwargs):
        ns_v = _resolve(ns, context).strip("/")

        bash_script = f"""
        set -e

        wait_srv() {{
          local srv="$1"
          local timeout="${{2:-120}}"
          local elapsed=0
          echo "[INIT] waiting for $srv ..."
          while ! ros2 service type "$srv" >/dev/null 2>&1; do
            sleep 0.5
            elapsed=$((elapsed+1))
            if [ $elapsed -ge $((timeout*2)) ]; then
              echo "[INIT][ERROR] timeout waiting for $srv"
              exit 1
            fi
          done
          echo "[INIT] $srv is ready."
        }}

        echo '[INIT] wait services on /{ns_v} ...'
        wait_srv /{ns_v}/service_server/set_full_collision_behavior

        echo '[INIT] set_full_collision_behavior'
        ros2 service call /{ns_v}/service_server/set_full_collision_behavior franka_msgs/srv/SetFullCollisionBehavior "{{
          lower_torque_thresholds_acceleration: [32, 32, 28, 24, 20, 16, 12],
          upper_torque_thresholds_acceleration: [52, 52, 45, 38, 30, 24, 18],
          lower_torque_thresholds_nominal:      [28, 28, 24, 20, 16, 12, 10],
          upper_torque_thresholds_nominal:      [45, 45, 38, 32, 26, 20, 16],
          lower_force_thresholds_acceleration:  [40, 40, 40, 18, 18, 18],
          upper_force_thresholds_acceleration:  [70, 70, 70, 30, 30, 30],
          lower_force_thresholds_nominal:       [34, 34, 34, 14, 14, 14],
          upper_force_thresholds_nominal:       [55, 55, 55, 24, 24, 24]
        }}"

        echo '[INIT] done.'
        """

        return [TimerAction(
            period=2.0,
            actions=[ExecuteProcess(cmd=['bash', '-lc', bash_script], output='screen')]
        )]

    return [OpaqueFunction(function=_build)]

def create_parameter_name():
    """
    声明所有参数并返回参数声明的列表。
    """
    enable_arm = DeclareLaunchArgument(
        "enable_arm",
        default_value="true",
        choices=["true", "false"],
        description="是否启用franka控制，注意使能则franka必须处于程序执行模式，此时机械臂无法示教",
    )
    return [enable_arm]


def render_rviz_config(template_path: str, replacements: dict) -> str:
    """
    从 RViz 模板生成一份实际可用的 .rviz 文件。
    模板里用占位符(例如 __MOVE_GROUP_NS__)，用 replacements 里的键值替换。

    :param template_path: 模板 .rviz 的绝对路径
    :param replacements:  例如 {"__MOVE_GROUP_NS__": "/car_arm"}
    :return: 生成的临时 .rviz 文件绝对路径
    """
    with open(template_path, "r", encoding="utf-8") as f:
        txt = f.read()
    for k, v in replacements.items():
        txt = txt.replace(k, v)

    fd, out_path = tempfile.mkstemp(prefix="rviz_", suffix=".rviz")
    with os.fdopen(fd, "w", encoding="utf-8") as g:
        g.write(txt)
    return out_path


def load_yaml(package_name, file_path):
    package_path = get_package_share_directory(package_name)
    absolute_file_path = os.path.join(package_path, file_path)

    try:
        with open(absolute_file_path, "r") as file:
            return yaml.safe_load(file)
    except (
        EnvironmentError
    ):  # parent of IOError, OSError *and* WindowsError where available
        return None


def create_arm_nodes(
    arm_ip: str,
    arm_id: str,
    ros2_control: str = "true",
    use_fake_hardware: str = "false",
    hand: str = "true",
    fake_sensor_commands: str = "true",
    arm_prefix: str = "mk1000",
    init_on_launch: bool = True,
    tool_mass: float = 0.8,
    tool_com_x: float = 0.0,
    tool_com_y: float = 0.0,
    tool_com_z: float = 0.07,
):
    arm_namespace = "/" + arm_prefix
    # Define path to the URDF file
    arm_xacro_file = os.path.join(
        get_package_share_directory("franka_description"),
        "robots",
        arm_id,
        arm_id + ".urdf.xacro",
    )

    # Generate robot description from URDF file
    robot_description = xacro.process_file(
        arm_xacro_file,
        mappings={
            "ros2_control": ros2_control,
            "arm_id": arm_id,
            "arm_prefix": arm_prefix,
            "robot_ip": arm_ip,
            "hand": hand,
            "use_fake_hardware": use_fake_hardware,
            "fake_sensor_commands": fake_sensor_commands,
        },
    ).toprettyxml(indent="  ")

    # Robot State Publisher node
    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        name="robot_state_publisher",
        namespace=arm_namespace,
        output="screen",
        remappings=[
            ("/tf", arm_namespace + "/tf"),
            ("/tf_static", arm_namespace + "/tf_static"),
        ],
        parameters=[{"robot_description": robot_description}],
    )

    # Path to the controllers configuration file
    arm_controllers = PathJoinSubstitution(
        [
            FindPackageShare("mk1000_franka_fr3_moveit_config"),
            "config",
            arm_id + "_ros_controllers.yaml",
        ]
    )
    robot_description_param = {"robot_description": robot_description}
    # ros2_control node
    ros2_control_node = Node(
        package="controller_manager",
        executable="ros2_control_node",
        namespace=arm_namespace,
        parameters=[arm_controllers],
        remappings=[
            ("~/robot_description", arm_namespace + "/robot_description"),
            ("joint_states", arm_namespace + "/franka/joint_states"),
        ],
        output={"stdout": "screen", "stderr": "screen"},
        on_exit=[LogInfo(msg=f"ERROR: {arm_id} controller_manager exit")],
    )

    # Joint state broadcaster
    joint_state_broadcaster = Node(
        package="controller_manager",
        executable="spawner",
        namespace=arm_namespace,
        arguments=["joint_state_broadcaster"],
        output="screen",
    )

    # Arm controller
    ros_controller = Node(
        package="controller_manager",
        executable="spawner",
        namespace=arm_namespace,
        arguments=[arm_id + "_arm_controller"],
        output="screen",
        condition=IfCondition(LaunchConfiguration("enable_arm")),
    )

    # Franka robot state broadcaster
    franka_robot_state_broadcaster = Node(
        package="controller_manager",
        executable="spawner",
        namespace=arm_namespace,
        arguments=["franka_robot_state_broadcaster"],
        parameters=[{"arm_id": arm_id}],
        output="screen",
        condition=UnlessCondition(use_fake_hardware),
    )
    # load fripper
    default_joint_name_postfix = "_finger_joint"
    joint_names_1 = arm_prefix + "_" + arm_id + default_joint_name_postfix + "1"
    joint_names_2 = arm_prefix + "_" + arm_id + default_joint_name_postfix + "2"
    joint_names = [joint_names_1, joint_names_2]

    gripper_launch_file = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            [
                PathJoinSubstitution(
                    [FindPackageShare("franka_gripper"), "launch", "gripper.launch.py"]
                )
            ]
        ),
        launch_arguments={
            "robot_ip": arm_ip,
            "use_fake_hardware": use_fake_hardware,
            "arm_id": f"{arm_prefix}_{arm_id}",
            "namespace": arm_namespace,
        }.items(),
    )

    joint_state_publisher = Node(
        package="joint_state_publisher",
        executable="joint_state_publisher",
        name="joint_state_publisher",
        namespace=arm_namespace,
        parameters=[
            {
                "source_list": [
                    arm_namespace + "/franka/joint_states",
                    arm_namespace + "_"+arm_id+"_gripper/joint_states",
                ],
                "rate": 30,
            }
        ],
    )

    node_list = [
        robot_state_publisher,
        ros2_control_node,
        # joint_state_broadcaster,
        TimerAction(period=2.0, actions=[joint_state_broadcaster]),
        # ros_controller,  #
        TimerAction(period=4.0, actions=[ros_controller]),
        # franka_robot_state_broadcaster,
        TimerAction(period=6.0, actions=[franka_robot_state_broadcaster]),
        joint_state_publisher,
        gripper_launch_file,
    ]
    # if enable_arm:
    #     node_list.append(ros_controller)

    if init_on_launch:
        node_list += franka_init_sequence(
            ns=arm_prefix,                 # 命名空间就是前缀（mk1000）
        )
    return node_list


def create_arm_robot_nodes(
    arm_id: str,
    arm_prefix: str = "mk1000",
    robot_namespace: str = "robot_mk1000_arm",
):
    # name spce全部为/
    # 加载模型文件
    global robot_description_
    arm_namespace = "/" + arm_prefix
    robot_namespace = "/" + robot_namespace
    arm_prefix = arm_prefix + "_"
    dula_arm_robot_xacro_file = os.path.join(
        get_package_share_directory("mr1000_description"), "urdf", "robot.urdf.xacro"
    )
    robot_description = xacro.process_file(
        dula_arm_robot_xacro_file,
        mappings={
            "arm_id": arm_id,
            "arm_prefix": arm_prefix,
            "use_fake_hardware": "false",
            "fake_sensor_commands": "false",
        },
    ).toprettyxml(indent="  ")

    robot_description_ = {
        "robot_description": ParameterValue(robot_description, value_type=str)
    }
    robot_state_publisher = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        name="robot_state_publisher",
        namespace=robot_namespace,
        output="screen",
        parameters=[{"robot_description": robot_description}],
    )
    joint_state_publisher = Node(
        package="joint_state_publisher",
        executable="joint_state_publisher",
        name="joint_state_publisher",
        namespace=robot_namespace,
        parameters=[
            {
                "source_list": [
                    arm_namespace + "/franka/joint_states",
                    arm_namespace + "_"+arm_id+"_gripper/joint_states",
                ],
                "rate": 30,
            }
        ],  # todo:改为分别接收作用的
    )
    return [robot_state_publisher, joint_state_publisher]


def create_arm_robot_moveit_nodes(
    arm_id: str,
    arm_prefix: str = "mk1000_",
    robot_namespace: str = "robot_mk1000_arm",
):
    robot_namespace = "/" + robot_namespace

    # 获取
    # 加载srdf
    dula_arm_robot_moveit_semantic_xacro_file = os.path.join(
        get_package_share_directory("mk1000_franka_fr3_moveit_config"),
        "srdf",
        "fr3_arm.srdf.xacro",
    )
    # 解析srdf
    dula_arm_robot_moveit_semantic_config = Command(
        [
            FindExecutable(name="xacro"),
            " ",
            dula_arm_robot_moveit_semantic_xacro_file,
            " hand:=true",
        ]
    )
    dula_arm_robot_moveit_semantic_config = {
        "robot_description_semantic": ParameterValue(
            dula_arm_robot_moveit_semantic_config, value_type=str
        )
    }
    #
    kinematics_yaml = load_yaml(
        "mk1000_franka_fr3_moveit_config", "config/kinematics.yaml"
    )
    # 加载规划器
    ompl_planning_pipeline_config = {
        "move_group": {
            "planning_plugin": "ompl_interface/OMPLPlanner",
            "request_adapters": "default_planner_request_adapters/AddTimeOptimalParameterization "
            "default_planner_request_adapters/ResolveConstraintFrames "
            "default_planner_request_adapters/FixWorkspaceBounds "
            "default_planner_request_adapters/FixStartStateBounds "
            "default_planner_request_adapters/FixStartStateCollision "
            "default_planner_request_adapters/FixStartStatePathConstraints",
            "start_state_max_bounds_error": 0.1,
        }
    }
    ompl_planning_yaml = load_yaml(
        "mk1000_franka_fr3_moveit_config", "config/ompl_planning.yaml"
    )
    ompl_planning_pipeline_config["move_group"].update(ompl_planning_yaml)
    # 加载客户端
    moveit_franka_controllers = load_yaml(
        "mk1000_franka_fr3_moveit_config", "config/fr3_controllers.yaml"
    )
    moveit_controllers = {
        "moveit_simple_controller_manager": moveit_franka_controllers,
        "moveit_controller_manager": "moveit_simple_controller_manager"
        "/MoveItSimpleControllerManager",
    }
    # 执行参数设置
    trajectory_execution = {
        "moveit_manage_controllers": True,
        "trajectory_execution.allowed_execution_duration_scaling": 1.2,
        "trajectory_execution.allowed_goal_duration_margin": 0.5,
        "trajectory_execution.allowed_start_tolerance": 0.01,
    }
    # 规划参数设置
    planning_scene_monitor_parameters = {
        "publish_planning_scene": True,
        "publish_geometry_updates": True,
        "publish_state_updates": True,
        "publish_transforms_updates": True,
    }
    # 启动实际的 move_group 节点/动作服务器
    run_move_group_node = Node(
        package="moveit_ros_move_group",
        executable="move_group",
        output="screen",
        namespace=robot_namespace,
        parameters=[
            robot_description_,
            dula_arm_robot_moveit_semantic_config,
            kinematics_yaml,
            ompl_planning_pipeline_config,
            trajectory_execution,
            moveit_controllers,
            planning_scene_monitor_parameters,
        ],
        remappings=[
            ("/tf", "/tf"),
            ("/tf_static", "/tf_static"),
        ],
    )
    # rvi
    rviz_base = os.path.join(
        get_package_share_directory("mk1000_franka_fr3_moveit_config"), "rviz"
    )
    rviz_tpl = os.path.join(rviz_base, "moveit.rviz")
    rviz_cfg = render_rviz_config(rviz_tpl, {"__MOVE_GROUP_NS__": f"{robot_namespace}"})
    rviz_node = Node(
        package="rviz2",
        executable="rviz2",
        name="dual_rviz2",
        output="log",
        arguments=["-d", rviz_cfg],
        namespace=robot_namespace,
        parameters=[
            robot_description_,
            dula_arm_robot_moveit_semantic_config,
            ompl_planning_pipeline_config,
            kinematics_yaml,
        ],
    )
    rviz_delayed = TimerAction(period=8.0, actions=[rviz_node])
    return [run_move_group_node]

    pass


def generate_launch_description():
    parameter_declarations = create_parameter_name()
    enable_arm = LaunchConfiguration("enable_arm")
    arm_drivers_nodes = create_arm_nodes(
        arm_ip="192.168.60.60",
        arm_id="fr3",
        ros2_control="true",
        use_fake_hardware="false",
        hand="true",
        fake_sensor_commands="true",
        arm_prefix="mk1000",
        # enable_arm=True,
    )

    robot_moveit_nodes = create_arm_robot_moveit_nodes(
        arm_id="fr3", arm_prefix="mk1000", robot_namespace="pc_arm"
    )

    return LaunchDescription(parameter_declarations + arm_drivers_nodes)