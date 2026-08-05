
#include "arm/arm_franka.h" // 添加机械臂接口头文件
#include <nlohmann/json.hpp>
#include <getopt.h>
#include <thread>
#include <atomic>
#include <filesystem>
#include "zenoh.hxx"
#include <rclcpp/rclcpp.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <std_msgs/msg/float32.hpp>


using json = nlohmann::json;
using namespace zenoh;
using namespace rpp;

void print_usage(const char *prog_name)
{
    std::cerr << "Usage: " << prog_name << " [options]\n"
              << "Options:\n"
              << "  -c, --config <path>       配置文件路径\n"
              << "  -u, --urdf <path>         URDF文件路径\n"
              << "  -S, --side <left|right>   机械臂方向 (默认: right)\n"
              << "  -h, --help                显示帮助信息\n";
}

int main(int argc, char *argv[])
{
    rclcpp::init(argc, argv);
    std::cout << "史河机器人 主从同构遥操作系统 启动\n";

    std::string home = getenv("HOME") ? getenv("HOME") : "";
    std::string urdf_path = "/home/robuster/test_ws/src/kortex_description/robots/test.urdf";
    std::string ip = "192.168.60.60";
    int port = 10000;

    std::string side = "right";

    static struct option long_opts[] = {
        {"arm-ip", required_argument, nullptr, 'c'},
        {"arm-port", required_argument, nullptr, 'p'},
        {"urdf", required_argument, nullptr, 'u'},
        {"side", required_argument, nullptr, 'S'},
        {"help", no_argument, nullptr, 'h'},
        {nullptr, 0, nullptr, 0}};

    int opt;
    while ((opt = getopt_long(argc, argv, "a:p:u:S:h", long_opts, nullptr)) != -1)
    {
        switch (opt)
        {
            break;
        case 'u':
            urdf_path = optarg;
            break;
        case 'a':
            ip = optarg;
            break;
        case 'p':
            port = std::stoi(optarg);
            break;
        case 'S':
            side = optarg;
            if (side != "left" && side != "right")
            {
                std::cerr << "Invalid side: " << side << std::endl;
                return -1;
            }
            break;
        case 'h':
            print_usage(argv[0]);
            return 0;
        default:
            print_usage(argv[0]);
            return -1;
        }
    }
    ArmFranka arm(ip, port);
    if (!arm.initialize())
    {
        std::cerr << "Franka机械臂初始化失败\n";
        return -1;
    }
    arm.clearError();

    // === 新增：ROS2 Node & Publishers ===
    auto node = rclcpp::Node::make_shared("master_arm_" + side);
    auto joint_pub = node->create_publisher<sensor_msgs::msg::JointState>("arm/" + side + "/joint_states", 10);
    auto grip_pub = node->create_publisher<std_msgs::msg::Float32>("arm/" + side + "/gripper_position", 10);

    auto session = Session::open(Config::create_default());
    auto pub = session.declare_publisher(KeyExpr("arm/" + side + "/servo_data"));
    auto g_pub = session.declare_publisher(KeyExpr("arm/" + side + "/gripper_data"));


    std::vector<float> position;
    float gripper_pos;
    json j;
    json g;
    auto last_gripper_pub_time = std::chrono::steady_clock::now();

    rclcpp::WallRate loop_rate(200);  // 200Hz -> 每 5ms 一次，和你原来的 sleep 对齐
    while (rclcpp::ok())
    {
        auto now = std::chrono::steady_clock::now();
        auto timestamp = std::chrono::duration_cast<std::chrono::milliseconds>(
                            std::chrono::system_clock::now().time_since_epoch())
                            .count();

        if (!arm.getJointsPosition(position))
        {
            std::cerr << "获取关节位置失败\n";
            rclcpp::spin_some(node);  // 让 ROS2 处理一下事件
            loop_rate.sleep();
            continue;
        }

        j["timestamp"] = timestamp;

        j["positions"] = position;
        pub.put(Bytes(j.dump()));  // 始终高频发布关节位置

        sensor_msgs::msg::JointState js_msg;
        js_msg.header.stamp = node->now();

        // 如果你有固定的关节名字，可以在这里设置一次，不变的可以放到循环外
        js_msg.name = {"joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "joint7"};
        js_msg.position.assign(position.begin(), position.end());
        // js_msg.position = position;
        joint_pub->publish(js_msg);

        // 限制 gripper_data 的发布频率为 30ms
        if (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_gripper_pub_time).count() >= 5000)
        {
            if (!arm.getGripperPosition(gripper_pos))
            {
                std::cerr << "获取夹爪位置失败\n";
            }
            else
            {
                g["timestamp"] = timestamp;
                g["positions"] = gripper_pos;
                g_pub.put(Bytes(g.dump()));
                // ROS2
                std_msgs::msg::Float32 grip_msg;
                grip_msg.data = gripper_pos;
                grip_pub->publish(grip_msg);
            }
            last_gripper_pub_time = now;
        }
        rclcpp::spin_some(node);  // 处理 ROS2 回调
        loop_rate.sleep();        // 保持 5ms 周期

        // std::this_thread::sleep_for(std::chrono::milliseconds(5));
    }
    rclcpp::shutdown();
    return 0;
}
