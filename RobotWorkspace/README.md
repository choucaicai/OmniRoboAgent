# RobotWorkspace 真机工作区

`RobotWorkspace` 是本仓库内独立维护的 ROS2 Humble 真机工作区，用于 Franka FR3 机械臂、夹爪、RealSense 相机和 MR1000 移动底盘的启动、标定、双臂遥操与 ROS bag 数据采集。它已用于真机实验；该状态来自项目记录，本次迁移只完成代码与资料归档，**未重新连接、解锁或运行真实硬件**。

本目录提供可独立运行的真机部署能力：将任务文本和相机观测发送到 VLA server，并完成从 VLA action 到 ROS 真机控制的执行。该链路与当前主干的任务/子任务驱动执行流程保持一致，可在 VLA 调用与真机执行边界直接衔接。不要把本目录的 ROS2 topic、脚本参数或标定数据视为通用真机 API。

## VLA Server 真机部署

我们已基本完成 VLA server 真机部署链路，入口是 [`infer.py`](src/application/robot_bringup/scripts/infer.py)：

```text
两路 RealSense 图像 + task_description
        -> HTTP VLA server
        -> action chunk
        -> 手眼变换 + MoveIt IK
        -> ROS JointTrajectory / gripper topic
        -> Franka FR3
```

`infer.py` 从 `/pc_arm/body_camera/color/image_raw/compressed` 与 `/pc_arm/wrist_camera/color/image_raw/compressed` 读取最新 JPEG，通过 multipart HTTP 请求发送 `main_images`、`wrist_images` 和含 `task_description` / `exp_id` 的 JSON；server 返回动作序列。当前执行器把每个动作的前 6 维视为相机坐标系下的位姿增量、第 7 维视为夹爪状态，使用手眼标定和 MoveIt IK 转为关节轨迹，再发布到 `/mk1000/fr3_arm_controller/joint_trajectory` 与 `/gripper_control_signal`。

该部署链已经将相机采集、VLA server 调用、手眼变换、IK 求解和 ROS 真机控制串联起来，形成完整的真机部署闭环。它可以与主干中产生的任务或子任务信息直接衔接，并将其作为 VLA 的任务输入。后续接入不同 VLA 时，只需替换具体的 VLA 部署模型，并将该模型的输入输出对齐到当前链路；ROS 驱动、标定与真机执行流程无需重写：

1. **动作定义**：确认 action chunk 的长度与 shape、位姿增量或关节动作、夹爪编码、参考坐标系、单位、归一化统计和控制频率。
2. **动作转换**：若新 VLA 不输出当前的 7D 相机系 delta action，就在 server 响应与 IK/轨迹控制之间加入对应的 action converter。
3. **输入兼容**：若新 VLA 使用不同的图像数量、顺序、分辨率/编码、状态或历史帧，只在 server request 侧适配，不改变下游执行部分。
4. **安全验证**：空载检查 action 范围、关节跳变、夹爪切换、超时和 server 异常；现有人工确认只覆盖部分位移和关节跳变，不能替代新模型验收。

## 真机 Demo

[观看真机部署演示视频](../real_world_robot_deployment.mp4)

该视频记录当前工作站的真机部署示例。复现实验时仍应单独记录任务、日期、控制模式、相机与实际使用的标定版本。

## 安全边界

真实机器人控制只能由完成现场培训的人员在工作站旁执行。每次操作至少两人：一人控制，一人持续观察机械臂、夹爪、线缆和人员安全；发现异常立即按急停。

- 移动平台充电时不得运行；固定平台和移动平台分别使用其规定电源。
- 在启动任何控制节点前，清空机械臂活动范围，确认夹爪无夹持风险、线缆无拉扯、急停可达。
- Franka 上位机必须先完成关节/夹爪解锁与 FCI 激活。手动示教用 `Programming`；接收程序控制用 `Execution`。模式不正确时不得启动遥操或轨迹脚本。
- `master_arm`、`slave_arm`、`apply.py` 和 `traj_control.py` 会产生或转发实际控制指令；先用空载、低速和现场监护验证。不要通过远程会话首次启动运动。
- 故障恢复应在 Franka 上位机完成；不要以强制杀进程代替安全停机。所有控制程序退出后，依照现场规程关闭设备电源。

访问权限应向工作站管理员单独获取，不得写入仓库、脚本或命令历史。

## 已包含的能力

| 能力 | 实现位置 | 当前作用 |
| --- | --- | --- |
| Franka 主/从臂遥操 | [`src/robot/arm_servo_adapters`](src/robot/arm_servo_adapters) | C++ 可执行程序 `master_arm` / `slave_arm` 通过 Zenoh 传递关节数据，ROS2 发布关节和夹爪状态。 |
| 机械臂模型与 MoveIt | [`src/robot/mk1000_franka_fr3_moveit_config`](src/robot/mk1000_franka_fr3_moveit_config) | FR3 控制器、SRDF、MoveIt、RViz 与手眼标定 launch 配置。 |
| 移动平台模型 | [`src/robot/mr1000_description`](src/robot/mr1000_description) | MR1000 URDF/Xacro、网格、RViz 与 robot-state publisher 启动文件。 |
| 相机、雷达与底盘 bring-up | [`src/application/robot_bringup/launch`](src/application/robot_bringup/launch) | 双 RealSense 相机、2D/3D 雷达、底盘驱动、机器人描述与 RViz 组合启动。 |
| 内参与手眼标定 | [`src/application/robot_bringup/scripts`](src/application/robot_bringup/scripts) | 收集棋盘格图像/关节状态、求解内参和相机到机械臂基座变换、渲染核验。 |
| 遥操数据采集 | [`teleop_log.py`](src/application/robot_bringup/scripts/teleop_log.py) 与 [`topic_recorder`](src/application/robot_bringup/scripts/topic_recorder) | 以 ROS 时间戳分别录制关节、夹爪、主视角和腕部图像到 SQLite3 `rosbag2`。 |
| VLA server 部署 | [`infer.py`](src/application/robot_bringup/scripts/infer.py) | 向 HTTP VLA server 发送双相机图像和任务文本，将返回的 7D delta action 转换为 Franka 关节轨迹与夹爪命令。 |
| 轨迹/策略回放工具 | [`apply.py`](src/application/robot_bringup/scripts/apply.py)、[`traj_control.py`](src/application/robot_bringup/scripts/traj_control.py) | 将 CSV 中的位姿增量或关节轨迹转换为 MoveIt IK/控制器消息；仅限经现场确认后使用。 |
| 标定样例 | [`data/calib`](data/calib) | 保存一组相机内参、手眼矩阵和误差文本，均绑定原工作站。 |

## 目录与数据边界

```text
RobotWorkspace/
├── src/
│   ├── robot/
│   │   ├── arm_servo_adapters/          # Franka 主从臂与 Zenoh 遥操
│   │   ├── mk1000_franka_fr3_moveit_config/
│   │   └── mr1000_description/
│   └── application/robot_bringup/       # launch、标定、采集和回放脚本
├── data/calib/                           # 工作站绑定的标定样例
└── local/                                # 可选的本地音频/视频辅助脚本
```

真机部署演示视频位于仓库根目录 [`real_world_robot_deployment.mp4`](../real_world_robot_deployment.mp4)。

`build/`、`install/`、`log/`、`interfaces/`、Python 缓存和所有原工作区 Git 元数据均未迁入。运行产生的 ROS bag、标定采集图像和模型权重不应提交到本仓库；将其保存到受控数据存储，并记录数据版本和机器人配置。

## 依赖与部署前检查

本工作区的代码不是可移植的一键安装包。构建与运行前必须由现场负责人确认以下依赖和参数，而不是照搬旧工作站设置：

1. Ubuntu 与 ROS2 Humble，包含 `ament_cmake`、`rclcpp`、`sensor_msgs`、`std_msgs`、`rosbag2_py`、`robot_state_publisher`、`joint_state_publisher` 和 `rviz2`。
2. Franka 的 `libfranka`、`franka_description`、`franka_hardware` 与 `franka_gripper`，版本须与控制柜和本地 SDK 匹配。
3. MoveIt2、`ros2_control`、`controller_manager`、`moveit_ros_move_group` 和 IK 所需组件。
4. `realsense2_camera`；如使用底盘/定位，还需要 `rpp_ros_driver`、`livox_ros_driver2`、`lakibeam1`、导航与定位相关包；手眼标定 launch 还引用 `aruco_ros`。
5. `arm_servo_adapters` 的 `zenohc`、`zenohcxx`、`yaml-cpp`、`nlohmann_json`、`fastcdr`、Eigen3 与 pinocchio。
6. Python 标定/采集脚本使用 ROS2 Python、OpenCV、NumPy、SciPy、Pandas、PyKDL、`cv_bridge` 与 `rosbag2_py`；现有脚本按原工作站的 `calib` Conda 环境编写，但该环境定义未随仓库迁入。
7. 相机序列号、机器人/控制柜 IP、网络接口、Zenoh discovery、topic 名称和控制器名称均须在现场逐项核对。它们写在 launch 文件、C++ 参数或脚本默认值中，不能当作新工作站的默认配置。

特别注意：[`arm_servo_adapters/CMakeLists.txt`](src/robot/arm_servo_adapters/CMakeLists.txt) 仍引用未随仓库提供的 `interfaces/zenoh-c`、`interfaces/zenohcpp`、`interfaces/Franka` 以及旧机器的 `libfranka` 绝对路径。新机器必须先补齐这些依赖并将路径改为本机真实位置，才可以构建该 package；不要为了通过编译而关闭 Franka 支持后再误认为可控制真机。

## 构建工作区

以下命令只构建软件，不会启动机器人。执行前先确认全部外部依赖已安装，且未连接的真机不会因自动启动脚本被触发。

```bash
cd <OMNIROBOAGENT_ROOT>/RobotWorkspace

source /opt/ros/humble/setup.bash
export WORKDIR="$PWD"

# 先处理 arm_servo_adapters 的 Franka/Zenoh 本地依赖与路径，再构建全部 package。
colcon build --symlink-install
source install/setup.bash
```

每个新终端都需要重新执行：

```bash
source /opt/ros/humble/setup.bash
export WORKDIR=<OMNIROBOAGENT_ROOT>/RobotWorkspace
source "$WORKDIR/install/setup.bash"
```

旧工作站使用 `sr2` / `srws` 作为上述两个 `source` 命令的 shell alias；迁入后不要依赖旧的 `/home/rpp/rpp_ws` 路径。脚本位于源树，`robot_bringup` 的 CMake 只安装 launch 和资源目录，因此目前应按下文用 `python "$WORKDIR/src/.../scripts/<script>.py"` 直接运行它们。

构建后的最小软件检查：

```bash
ros2 pkg prefix mr1000_description
ros2 pkg prefix mk1000_franka_fr3_moveit_config
ros2 pkg prefix robot_bringup
ros2 pkg prefix arm_servo_adapters
```

任何一项失败，都先解决依赖、路径或 CMake 配置；不要继续启动控制节点。

## 推荐执行顺序

以下是由现场电源状态到数据产出的完整流程。每一步都有明确停止条件；不满足时停在当前步骤排查。

| 阶段 | 操作 | 成功信号 | 停止条件 |
| --- | --- | --- | --- |
| 1. 现场检查 | 两人到场，确认急停、供电、线缆、工作空间和网络。 | 急停可达，活动范围清空。 | 人员、线缆或设备状态异常。 |
| 2. 上电与上位机 | 按现场安全规程为固定/移动平台上电；在 Franka 上位机解锁关节与夹爪、激活 FCI，并选择正确模式。 | 机械臂显示可用且无 fault。 | 任何 fault、碰撞告警或模式不一致。 |
| 3. ROS 环境 | `source` ROS2 与工作区，设置 `WORKDIR`。 | `ros2 pkg prefix` 能定位 package。 | package 找不到或依赖缺失。 |
| 4. 感知/状态 | 先启动所需相机或机械臂驱动，使用 `ros2 topic list` / `ros2 topic echo --once` 核对数据。 | 预期 topic 有 publisher 且消息有效。 | 相机序列号、网络或 topic 不匹配。 |
| 5. 标定或遥操 | 仅在步骤 1--4 全部通过后启动标定、主从臂或数据记录。 | 人工确认运动与记录正确。 | 运动异常、延迟、丢帧或不安全状态。 |
| 6. 数据检查与收尾 | 停止记录，核验各 bag，退出控制程序，按现场规程关机。 | 每个 bag 含 `.db3` 与 `metadata.yaml`。 | 任一数据流缺失或机器人未安全停稳。 |

## 相机与手眼标定

标定针对当前安装位置和相机，换相机、调整支架、重装末端执行器或变更坐标系后必须重做。`data/calib/` 中的结果仅是原工作站样例，禁止直接用于另一台机器人。

### 1. 启动相机并核对 topic

在机械臂处于手动示教模式时启动相机：

```bash
ros2 launch robot_bringup camera.launch.py
```

[`camera.launch.py`](src/application/robot_bringup/launch/camera.launch.py) 会启动两台 RealSense：机身相机和腕部相机。运行前在该文件中核对相机序列号、命名空间、分辨率、深度对齐和实际设备。预期可观察到类似 `/pc_arm/body_camera/color/image_raw` 的图像 topic；准确名称以 `ros2 topic list` 为准。

### 2. 内参标定

1. 启动目标相机；在带显示器的现场终端运行收集程序，远程无显示会使 OpenCV 按键采集不可用。
2. 运行：

   ```bash
   python "$WORKDIR/src/application/robot_bringup/scripts/prepare_intrinsic_calib_data.py"
   ```

3. 确保每张图完整包含标定板，稳定后按 `a` 保存。建议至少采集 25 张，并覆盖不同位置和姿态。
4. 在 [`run_intrinsic_opt_calibration.py`](src/application/robot_bringup/scripts/run_intrinsic_opt_calibration.py) 中确认输入目录、棋盘格参数与输出目录后运行：

   ```bash
   python "$WORKDIR/src/application/robot_bringup/scripts/run_intrinsic_opt_calibration.py"
   ```

5. 保存的 `mtx.npy`、`dist.npy` 与采集数据一起归档，记录相机序列号、分辨率和日期。

### 3. 手眼标定

1. 启动相机，并在主臂处于 `Programming` 模式时启动主臂状态发布：

   ```bash
   "$WORKDIR/install/arm_servo_adapters/lib/arm_servo_adapters/master_arm"
   ```

2. 核对图像 topic 和关节状态 topic（原流程使用 `/arm/right/joint_states`）。
3. 在现场显示器上运行：

   ```bash
   python "$WORKDIR/src/application/robot_bringup/scripts/prepare_eyehand_calib_data.py"
   ```

4. 在无碰撞的可达区域内采集覆盖充足的姿态；建议至少采集 50 张，按 `a` 保存。
5. 核对 [`run_eyehand_opt_calibration.py`](src/application/robot_bringup/scripts/run_eyehand_opt_calibration.py) 的路径和标定板配置后运行：

   ```bash
   python "$WORKDIR/src/application/robot_bringup/scripts/run_eyehand_opt_calibration.py"
   ```

6. 评估输出的重投影误差并使用 [`render.py`](src/application/robot_bringup/scripts/render.py) 做视觉叠加检查。历史手册以约 `0.2` 或更小的重投影误差为经验参考；还必须人工确认渲染框与真实机械臂对齐，不能只看单个误差数值。

## 主从臂遥操

遥操前，用网线连接工控机与移动平台顶部网口，并确认 Zenoh 发现/路由与两台上位机网络配置一致。源代码中主臂发布 `arm/<side>/servo_data`，从臂订阅该键值并发布 `slave_arm/<side>/joint_states`；这是当前工作站实现细节，不是跨机器的稳定协议。

1. **主臂**：在主臂上位机依次解锁、激活 FCI、选择 `Programming`，然后运行：

   ```bash
   "$WORKDIR/install/arm_servo_adapters/lib/arm_servo_adapters/master_arm"
   ```

2. **从臂**：在从臂上位机依次解锁、激活 FCI、选择 `Execution`，确认现场人员已就位后运行。`-T 5` 表示 5 ms 控制周期（约 200 Hz）。

   ```bash
   "$WORKDIR/install/arm_servo_adapters/lib/arm_servo_adapters/slave_arm" -T 5
   ```

3. **夹爪**：`slave_arm` 订阅 `/gripper_control_signal`。另开终端启动键盘控制：

   ```bash
   python "$WORKDIR/src/application/robot_bringup/scripts/keyboard_control.py"
   ```

   `a` 打开夹爪，`q` 闭合夹爪。夹爪控制不能与机械臂拖动同时进行；先松开机械臂控制按钮、等待机械臂停稳，再执行夹爪操作。

4. **运行观察**：确认 `/slave_arm/right/joint_states`、夹爪 topic 和现场运动的频率/方向一致。若出现延迟、抖动、方向相反、碰撞风险或 topic 丢失，立即急停并停止所有控制节点。

## 遥操数据采集（TeleOp-Log）

采集前先决定任务、相机、频率、数据目录和验收样本。高频 topic 会受磁盘吞吐限制，无法保证无丢帧；先在短时空载试录中核验。

### 启动顺序

分别使用独立终端启动：

```bash
# 终端 1：从臂状态与遥操控制
"$WORKDIR/install/arm_servo_adapters/lib/arm_servo_adapters/slave_arm" -T 5

# 终端 2：相机（先检查 camera.launch.py 中的现场参数）
ros2 launch robot_bringup camera.launch.py

# 终端 3：夹爪键盘控制
python "$WORKDIR/src/application/robot_bringup/scripts/keyboard_control.py"

# 终端 4：记录节点
python "$WORKDIR/src/application/robot_bringup/scripts/teleop_log.py"
```

[`teleop_log.py`](src/application/robot_bringup/scripts/teleop_log.py) 组合 `TopicRecorder`，分别监听关节、夹爪、主视角和腕部图像。它以 ROS 消息时间戳写入 SQLite3 `rosbag2`；输出目录默认为 `$WORKDIR/data/bags/<datetime>/`，每一路应各自具有 `.db3` 和 `metadata.yaml`。

键盘事件为：

| 按键 | 动作 |
| --- | --- |
| `a` | 打开夹爪 |
| `q` | 闭合夹爪 |
| `s` | 开始记录 |
| `e` | 停止记录 |

结束后先检查四路输出是否齐全、时间范围是否重叠、图像是否可解码、关节/夹爪消息数量是否合理，再将原始数据移至受控存储。`local/local_server.py` 和 `local/voice.py` 仅用于可选语音提示；未配置时不影响 ROS bag 记录。

## 其他启动与回放入口

| 目标 | 命令 | 说明 |
| --- | --- | --- |
| Franka + MoveIt | `ros2 launch robot_bringup arm_driver.launch.py` | 间接包含 FR3 driver/MoveIt 配置；会触及控制相关组件，仅在现场就绪后执行。 |
| 相机 + 机械臂 | `ros2 launch robot_bringup arm_gripper_camera.launch.py` | 组合 Franka driver 和一台 RealSense 的历史配置。 |
| 移动底盘 bring-up | `ros2 launch robot_bringup robot_driver.launch.py` | 组合雷达、描述与 `rpp_ros_driver`，依赖现场底盘网络。 |
| 机器人模型可视化 | `ros2 launch mr1000_description mr1000model.launch.py` | 用于模型/RViz 验证，不等同于真机控制。 |
| MoveIt demo | `ros2 launch mk1000_franka_fr3_moveit_config demo_moveit.launch.py` | 先核对 launch 参数和 controller，避免与真机控制会话冲突。 |
| VLA server 真机部署 | `python "$WORKDIR/src/application/robot_bringup/scripts/infer.py"` | 读取双相机图像、请求现有 HTTP VLA server 并执行其 action chunk；运行前必须核对 server endpoint、模型 I/O、手眼标定和安全阈值。 |
| 策略/轨迹执行 | `python "$WORKDIR/src/application/robot_bringup/scripts/apply.py"` 或 `traj_control.py` | 会发布实际轨迹或夹爪命令；CSV 路径、坐标系、IK 服务、速度和工作空间均需逐项复核。 |

## 已知限制与迁移结论

1. 现有源码中存在工作站专用绝对路径、相机序列号、默认 topic 与第三方依赖位置。它们是部署时必须参数化或核对的内容，不应在未验证前改写或假定通用。
2. 标定、遥操、记录和回放路径已经具备源代码；本次没有 ROS build、相机 smoke、机械臂 movement 或真机成功率复验。因此“已进行真机实验”是历史项目状态，不是本次迁移的复现结论。
3. 当前 VLA client 的 server 地址、任务列表、动作维度、执行步数和安全阈值仍在 `infer.py` 的工作站专用实现中。接入新 VLA 时，应先完成 action 对齐和现场安全验证。
4. 实际操作始终以现场安全规程、控制柜状态和厂商文档为最高优先级。

## 迁入完整性

该目录从原 `RobotWorkspace` 工作区复制而来，未保留原项目的 `.git/`、远端地址、提交历史或 submodule 元数据。保留的 `.gitignore` 只用于忽略 ROS2 构建与运行产物。
