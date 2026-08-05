#include "timer/hp_timer.h"
#include "untils/joint_interpolator.h"
#include "zenoh.hxx"
#ifdef FRANKA_ARM
#include "arm/arm_franka.h" // 添加机械臂接口头文件
#endif
#include "protocol/cdr.h"

#include <mutex>
#include <getopt.h>
#include <fstream>
#include <yaml-cpp/yaml.h>
#include <nlohmann/json.hpp>

// ==== ROS2 相关头文件 ====
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <std_msgs/msg/float32.hpp>

using json = nlohmann::json;
using namespace rpp;
struct SharedData
{
    std::mutex mtx;
    int joints = 6; // 机械臂关节数，默认为6
    long long curr_time = 0;
    std::vector<float> curr_joint;
    ArmInterface *arm = nullptr;
    JointInterpolator *interpolator = nullptr;
    zenoh::Publisher *slave_msg_pub = nullptr;
    zenoh::Publisher *slave_gripper_msg_pub = nullptr;
    zenoh::Publisher *master_gripper_msg_pub = nullptr;
    zenoh::Publisher *master_msg_pub = nullptr;
    long long start_time = 0;
    bool first_frame = true;

    // ==== ROS2 相关 ====
    rclcpp::Node::SharedPtr node;
    rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr joint_pub;
    rclcpp::Publisher<std_msgs::msg::Float32>::SharedPtr gripper_pub;
    rclcpp::Subscription<std_msgs::msg::Float32>::SharedPtr gripper_control_sub;
};

void controlCallback(void *arg)
{
    auto *data = static_cast<SharedData *>(arg);
    std::lock_guard<std::mutex> lock(data->mtx);
    data->start_time = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
    auto interp_joint = data->interpolator->interpolate(data->start_time);
    if (interp_joint.empty())
    {
        // std::cout << "interp_joint empty" << std::endl;
        return;
    }
    // 获取当前实际关节位置和夹爪状态
    std::vector<float> curr_joint;
    if (data->arm)
    {
        data->arm->getJointsPosition(curr_joint);
        if (curr_joint.size() != data->joints)
        {
            std::cerr << "获取关节位置失败，可能是机械臂未连接或数据错误。" << std::endl;
            return; // 跳过本次循环
        }
    }

    // 将插值结果转换为Joint_angle结构体
    Joint_angle joint_angle;
    memset(joint_angle.angle, 0, sizeof(joint_angle.angle));
    joint_angle.stamp.sec = data->start_time / 1000;
    joint_angle.stamp.nanosec = (data->start_time % 1000) * 1000000; // 纳秒转换
    std::copy(curr_joint.begin(), curr_joint.end(), joint_angle.angle);
    // 编码为CDR格式
    auto encoded_data = encodeJoint(joint_angle);
    // 发布
    data->slave_msg_pub->put(zenoh::Bytes(encoded_data));
    float gripper_pos;
    if (data->arm)
    {
        data->arm->getGripperPosition(gripper_pos);
        data->slave_gripper_msg_pub->put(
            zenoh::Bytes(encodeGripper({joint_angle.stamp, gripper_pos})));
    }

    // 通过 ROS2 发布从臂的 Joint_angle / Gripper_status ======
    if (data->joint_pub && data->node)
    {
        sensor_msgs::msg::JointState js_msg;
        js_msg.header.stamp = data->node->now();
        // 你也可以在这里设置 name，例如：
        // js_msg.name = {"joint1", "joint2", ..., "jointN"};
        js_msg.position.assign(curr_joint.begin(), curr_joint.end()); // float -> double
        data->joint_pub->publish(js_msg);
    }

    if (data->gripper_pub && data->node)
    {
        std_msgs::msg::Float32 grip_msg;
        grip_msg.data = gripper_pos; // 这里用的是夹爪位置
        data->gripper_pub->publish(grip_msg);
    }

    if (data->arm)
    {
        data->arm->setMotorsPosition(interp_joint);
    }
}

void print_usage(const char *prog_name)
{
    std::cerr << "Usage: " << prog_name << " [options]\n"
              << "Options:\n"
              << "  -a, --arm-ip <address>    机械臂IP地址 (默认: 192.168.1.10)\n"
              << "  -t, --arm-port <number>   机械臂控制端口 (默认: 10000)\n"
              << "  -r, --arm-rt-port <number> 机械臂实时端口 (默认: 10001)\n"
              << "  -T, --period <ms>         控制周期（毫秒） (默认: 1)\n"
              << "  -j, --joints <number>     机械臂关节数 (默认: 6)\n"
              << "  -g, --enable-gripper       启用夹爪控制 (默认: 禁用)\n"
              << "  -u, --urdf-path <path>     URDF文件路径 (默认: 空)\n"
              << "  -p, --priority <number>   定时器优先级 (默认: 99)\n"
              << "  -S, --side <left|right> 机械臂方向 (默认: right)\n"
              << "  -h, --help                显示帮助信息\n";
}

void servoDataCallback(const zenoh::Sample &sample, SharedData *data, const bool &open_gripper)
{
    try
    {
        auto j = json::parse(sample.get_payload().as_string());
        long long timestamp = j["timestamp"];
        std::vector<float> positions = j["positions"].get<std::vector<float>>();

        std::lock_guard<std::mutex> lock(data->mtx);

        if (data->first_frame && positions.size() == data->joints)
        {
            if (data->arm)
            {
                data->arm->setJointsPosition(positions);
                data->first_frame = false;
                return;
            }
        }

        data->curr_time = timestamp;
        data->curr_joint = positions;

        Joint_angle joint_angle;
        memset(joint_angle.angle, 0, sizeof(joint_angle.angle));
        joint_angle.stamp.sec = timestamp / 1000;
        joint_angle.stamp.nanosec = (timestamp % 1000) * 1000000; // 纳秒转换
        std::copy(positions.begin(), positions.end(), joint_angle.angle);
        // 编码为CDR格式
        auto encoded_data = encodeJoint(joint_angle);
        data->master_msg_pub->put(zenoh::Bytes(encoded_data));

        if (data->interpolator)
        {
            data->interpolator->addData(
                timestamp,
                positions,
                std::chrono::duration_cast<std::chrono::milliseconds>(
                    std::chrono::system_clock::now().time_since_epoch())
                    .count());
        }
    }
    catch (const std::exception &e)
    {
        std::cerr << "Zenoh数据解析错误: " << e.what() << std::endl;
    }
}
// void gripperDataCallback(const zenoh::Sample &sample, SharedData *data)
// {

//     auto j = json::parse(sample.get_payload().as_string());
//     long long timestamp = j["timestamp"];
//     Time stamp;
//     stamp.sec = timestamp / 1000;
//     stamp.nanosec = (timestamp % 1000) * 1000000; // 纳秒转换
//     float positions = j["positions"].get<float>();
//     data->master_gripper_msg_pub->put(
//         zenoh::Bytes(encodeGripper({stamp, positions})));
//     std::thread([positions, data]()
//                 {
//                     bool gripper_status;
//                     data->arm->getGripperStatus(gripper_status);


//                     auto start = std::chrono::high_resolution_clock::now();
//                     if(positions > 0.04 && gripper_status == false)
//                     {
//                         data->arm->openGripper();

//                     }
//                     else if (positions < 0.04 && gripper_status==true)
//                     {
//                         data->arm->closeGripper();
//                     }
                    
//                     // data->arm->setGripperPose(positions);
//                     auto end = std::chrono::high_resolution_clock::now();
//                     std::cout << "setGripperPose耗时: "
//                             << std::chrono::duration_cast<std::chrono::milliseconds>(end - start).count()
//                             << " ms" << std::endl; })
//         .detach();
// }

// ROS2 夹爪控制信号回调：/gripper_control_signal，1=open，0=close
void gripperControlCallback(const std_msgs::msg::Float32::SharedPtr msg, SharedData* data)
{
    float cmd = msg->data;

    std::lock_guard<std::mutex> lock(data->mtx);

    if (!data->arm)
    {
        RCLCPP_WARN(rclcpp::get_logger("gripper_control"), "Arm not initialized");
        return;
    }

    bool gripper_status;
    data->arm->getGripperStatus(gripper_status);

    auto start = std::chrono::high_resolution_clock::now();
    if (cmd >= 0.04)   // open
    {
        if (!gripper_status)   // 当前是 closed → open
        {
            data->arm->openGripper();
            std::cout << "[ROS2] Gripper opened." << std::endl;
        }
    }
    else if (cmd <= 0.04)   // close
    {
        if (gripper_status)  // 当前是 open → close
        {
            data->arm->closeGripper();
            std::cout << "[ROS2] Gripper closed." << std::endl;
        }
    }
    auto end = std::chrono::high_resolution_clock::now();

    // ====== 通过 ZENOH 发布 Gripper_status ======
    Time stamp;
    auto now_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
                      std::chrono::system_clock::now().time_since_epoch())
                      .count();
    stamp.sec = now_ms / 1000;
    stamp.nanosec = (now_ms % 1000) * 1000000;

    float pos_send = cmd;

    auto encoded = encodeGripper({stamp, pos_send});
    data->slave_gripper_msg_pub->put(zenoh::Bytes(encoded));
}


int main(int argc, char *argv[])
{
    // ==== ROS2 初始化 ====
    rclcpp::init(argc, argv);

    std::cout << "史河机器人（合肥）有限公司 主从同构遥操作系统" << std::endl;
    std::cout << "Slave Arm Controller started." << std::endl;
    // 设置默认参数
    std::string arm_ip = "192.168.60.60";
    int arm_port = 10000;
    int arm_rt_port = 10001;
    int period_ms = 1;
    int joints = 7;
    bool enable_gripper = false;
    std::string urdf_path = ""; // 修复：改为正确的string类型
    int priority = 0;           // 定时器优先级
    std::string side = "right";

    // 更新命令行选项
    static struct option long_options[] = {
        {"arm-ip", required_argument, nullptr, 'a'},
        {"arm-port", required_argument, nullptr, 't'},
        {"arm-rt-port", required_argument, nullptr, 'r'},
        {"period", required_argument, nullptr, 'T'},
        {"joints", required_argument, nullptr, 'j'},
        {"help", no_argument, nullptr, 'h'},
        {"enable-gripper", no_argument, nullptr, 'g'},
        {"urdf-path", required_argument, nullptr, 'u'},
        {"priority", required_argument, nullptr, 'p'},
        {"side", no_argument, nullptr, 'S'},
        {nullptr, 0, nullptr, 0}};

    // 解析参数
    int opt;
    while ((opt = getopt_long(argc, argv, "a:t:r:T:j:S:g:u:p:h", long_options, nullptr)) != -1)
    {
        switch (opt)
        {
        case 'a':
            arm_ip = optarg;
            break;
        case 't':
            arm_port = std::stoi(optarg);
            break;
        case 'r':
            arm_rt_port = std::stoi(optarg);
            break;
        case 'T':
            period_ms = std::stoi(optarg);
            break;
        case 'j':
            joints = std::stoi(optarg);
            break;
        case 'h':
            print_usage(argv[0]);
            return 0;
        case 'g':
            enable_gripper = true;
            break;
        case 'u':
            urdf_path = optarg;
            break;
        case 'p':
            priority = std::stoi(optarg);
            break;
        case 'S':
            side = optarg;
            if (side != "left" && side != "right")
            {
                std::cerr << "Error: Invalid side option. Use 'left' or 'right'." << std::endl;
                return -1;
            }
            break;
        default:
            print_usage(argv[0]);
            return -1;
        }
    }
    bool open_gripper = false;
    zenoh::Config config = zenoh::Config::create_default();
    zenoh::Config config2 = zenoh::Config::create_default();

    auto session = zenoh::Session::open(std::move(config));
    auto test = zenoh::Session::open(std::move(config2));
#ifdef FRANKA_ARM
    ArmFranka arm(arm_ip.c_str(), arm_port); // Franka机械臂初始化
#endif
    if (arm.initialize())
    {
        if (arm.clearError())
        {
            std::cout << "机械臂初始化成功，清除错误状态。" << "关节数：" << joints << std::endl;
        }
    }
    JointInterpolator interp(joints); // 6自由度

    SharedData data;
    data.interpolator = &interp;
    data.joints = joints;           // 设置机械臂关节数
    data.curr_joint.resize(joints); // 初始化关节数组
    data.arm = &arm;
    data.start_time = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count();
    auto slave_msg_pub = session.declare_publisher(zenoh::KeyExpr("slave_arm/" + side + "/Joint_angle"));
    auto master_msg_pub = session.declare_publisher(zenoh::KeyExpr("master_arm/" + side + "/Joint_angle"));
    auto slave_gripper_msg_pub = session.declare_publisher(zenoh::KeyExpr("slave_arm/" + side + "/Gripper_status"));
    auto master_gripper_msg_pub = session.declare_publisher(zenoh::KeyExpr("master_arm/" + side + "/Gripper_status"));

    data.master_msg_pub = &master_msg_pub;
    data.slave_msg_pub = &slave_msg_pub;
    data.slave_gripper_msg_pub = &slave_gripper_msg_pub;
    data.master_gripper_msg_pub = &master_gripper_msg_pub;


    // ==== 新增：创建 ROS2 Node 与 Publishers ====
    data.node = rclcpp::Node::make_shared("slave_arm_" + side);

    // 从臂关节角：/slave_arm/<side>/joint_states
    data.joint_pub = data.node->create_publisher<sensor_msgs::msg::JointState>(
        "slave_arm/" + side + "/joint_states", 10);

    // 从臂夹爪位置：/slave_arm/<side>/gripper_position
    data.gripper_pub = data.node->create_publisher<std_msgs::msg::Float32>(
        "slave_arm/" + side + "/gripper_position", 10);

    // ==== 接收 ROS2 夹爪控制信号 ====
    data.gripper_control_sub = data.node->create_subscription<std_msgs::msg::Float32>(
        "/gripper_control_signal",
        10,
        [&](const std_msgs::msg::Float32::SharedPtr msg)
        {
            gripperControlCallback(msg, &data);
        }
    );

    auto sub = session.declare_subscriber(
        zenoh::KeyExpr("arm/" + side + "/servo_data"),
        [&data, &open_gripper](const zenoh::Sample &sample)
        { servoDataCallback(sample, &data, open_gripper); },
        zenoh::closures::none);
    // auto g_sub = test.declare_subscriber(
    //     zenoh::KeyExpr("arm/" + side + "/gripper_data"),
    //     [&data](const zenoh::Sample &sample)
    //     { gripperDataCallback(sample, &data); },
    //     zenoh::closures::none);

    HPTimer timer(period_ms, priority, controlCallback, &data);
    timer.start();
    // 主循环：保持进程 + 给 ROS2 一点时间处理事件
    while (rclcpp::ok())
    {
        rclcpp::spin_some(data.node);
        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }

    rclcpp::shutdown();
    return 0;
}
