#include "arm/arm_franka.h"

namespace rpp
{
  ArmFranka::ArmFranka(std::string ipAddress, uint32_t port)
      : ArmInterface(ipAddress, port), robot_(ipAddress), gripper_(ipAddress)
  {
    // 设置默认行为
    setDefaultBehavior(robot_);
    dq_filtered_.setZero();
  }

  ArmFranka::~ArmFranka()
  {
    if (control_running_)
    {
      isServoingMode = true;

      // 如果线程仍在运行，强制退出
      if (control_thread_.joinable())
      {
        control_thread_.join();
      }
    }
  }

  bool ArmFranka::initialize()
  {
    try
    {
      setDefaultBehavior(robot_);
      robot_.setCollisionBehavior(
          {{20.0, 20.0, 18.0, 18.0, 16.0, 14.0, 12.0}}, {{20.0, 20.0, 18.0, 18.0, 16.0, 14.0, 12.0}},
          {{20.0, 20.0, 18.0, 18.0, 16.0, 14.0, 12.0}}, {{20.0, 20.0, 18.0, 18.0, 16.0, 14.0, 12.0}},
          {{20.0, 20.0, 20.0, 25.0, 25.0, 25.0}}, {{20.0, 20.0, 20.0, 25.0, 25.0, 25.0}},
          {{20.0, 20.0, 20.0, 25.0, 25.0, 25.0}}, {{20.0, 20.0, 20.0, 25.0, 25.0, 25.0}});
      gripper_feedback_thread_ = std::thread(&ArmFranka::gripperFeedbackLoop, this);
      return true;
    }
    catch (const franka::Exception &e)
    {
      std::cerr << "Initialize failed: " << e.what() << std::endl;
      return false;
    }
  }

  bool ArmFranka::unitialize()
  {
    std::this_thread::sleep_for(std::chrono::milliseconds(500));
    return true;
  }

  bool ArmFranka::clearError()
  {
    try
    {
      setDefaultBehavior(robot_);
      return true;
    }
    catch (const franka::Exception &e)
    {
      std::cerr << "ClearError failed: " << e.what() << std::endl;
      return false;
    }
  }

  bool ArmFranka::setServoingMode(bool enable)
  {
    isServoingMode = enable;
    return true;
  }

  bool ArmFranka::getJointsPosition(std::vector<float> &values)
  {
    try
    {
      if (!isServoingMode)
      {
        franka::RobotState state = robot_.readOnce();
        for (size_t i = 0; i < 7; ++i)
        {
          state_[i] = state.q[i] * 180.0 / M_PI;
        }
      }
      values.assign(state_.begin(), state_.end());

      return true;
    }
    catch (const franka::Exception &e)
    {
      std::cerr << "getJointsPosition failed: " << e.what() << std::endl;
      return false;
    }
  }

  bool ArmFranka::getCartesianPose(std::vector<float> &values)
  {
    try
    {
      std::lock_guard<std::mutex> lock(robot_mutex_);
      franka::RobotState state = robot_.readOnce();
      values.assign(state.O_T_EE.begin(), state.O_T_EE.end());
      return true;
    }
    catch (const franka::Exception &e)
    {
      std::cerr << "getCartesianPose failed: " << e.what() << std::endl;
      return false;
    }
  }
  bool ArmFranka::getGripperStatus(bool &value)
  {
    try
    {
      if (is_grasped_)
      {
        value = false;
      }
      else
      {
        value = (gripper_width_ > 0.04);
      }

      return true;
    }
    catch (const franka::Exception &e)
    {
      std::cerr << "getGripperStatus failed: " << e.what() << std::endl;
      return false;
    }
  }
  bool ArmFranka::getGripperPosition(float &value)
  {

    value = gripper_width_;
    return true;
  }
  bool ArmFranka::setJointsPosition(const std::vector<float> &values)
  {
    std::lock_guard<std::mutex> lock(robot_mutex_);
    if (isServoingMode)
    {
      setServoingMode(false);
    }
    if (values.size() != 7)
      return false;
    try
    {
      std::array<double, 7> target_q;
      for (size_t i = 0; i < 7; ++i)
      {
        // 检查关节限位
        const float clamped_deg = std::clamp(values[i],
                                             JOINT_LIMITS[i].first,
                                             JOINT_LIMITS[i].second);
        // 转换为弧度
        target_q[i] = clamped_deg * M_PI / 180.0;
      }

      MotionGenerator motion_generator(0.5, target_q);
      robot_.control(motion_generator);
      return true;
    }
    catch (const franka::Exception &e)
    {
      std::cerr << "setJointsPosition failed: " << e.what() << std::endl;
      return false;
    }
  }

  bool ArmFranka::setCartesianPose(const std::vector<float> &values)
  {
    std::lock_guard<std::mutex> lock(robot_mutex_);
    if (values.size() != 16)
    {
      std::cerr << "setCartesianPose: expected 16 values (4x4 transform matrix)." << std::endl;
      return false;
    }

    try
    {
      std::array<double, 16> target_pose;
      std::copy(values.begin(), values.end(), target_pose.begin());

      auto motion = [target_pose](const franka::RobotState &,
                                  franka::Duration) -> franka::CartesianPose
      {
        return franka::MotionFinished(target_pose);
      };

      robot_.control(motion);
      return true;
    }
    catch (const franka::Exception &e)
    {
      std::cerr << "setCartesianPose failed: " << e.what() << std::endl;
      return false;
    }
  }

  bool ArmFranka::setMotorsPosition(const std::vector<float> &values)
  {

    if (!isServoingMode)
    {
      setServoingMode(true);
    }
    if (values.size() != 7)
    {
      std::cerr << "setMotorsPosition: expected 7 values for joint positions." << std::endl;
      return false;
    }
    std::array<double, 7> target_q;

    for (size_t i = 0; i < 7; ++i)
    {
      // 检查关节限位
      const float clamped_deg = std::clamp(values[i],
                                           JOINT_LIMITS[i].first,
                                           JOINT_LIMITS[i].second);
      // 转换为弧度
      target_q[i] = clamped_deg * M_PI / 180.0;
    }

    {
      std::lock_guard<std::mutex> lock(target_mutex_);
      for (size_t i = 0; i < 7; ++i)
      {
        target_position_[i] = target_q[i];
      }
    }

    if (!control_running_)
    {
      control_running_ = true;
      control_thread_ = std::thread(&ArmFranka::controlLoop, this);
      control_thread_.detach(); // 后台运行
    }

    return true;
  }
  bool ArmFranka::setGripperPosition(const float &value)
  {
    try
    {
      // Fully open to max width (assume ~0.08m), speed 0.1 m/s
      return gripper_.move(value, 0.8);
    }
    catch (const franka::Exception &e)
    {
      std::cerr << "openGripper failed: " << e.what() << std::endl;
      return false;
    }
  }
  bool ArmFranka::openGripper()
  {
    try
    {
      // Fully open to max width (assume ~0.08m), speed 0.1 m/s
      return gripper_.move(0.08, 0.1);
    }
    catch (const franka::Exception &e)
    {
      std::cerr << "openGripper failed: " << e.what() << std::endl;
      return false;
    }
  }

  bool ArmFranka::closeGripper()
  {
    try
    {
      // Grasp object with 60N force at 0.0 width (fully closed)
      // bool success = gripper_.grasp(0.05, 0.1, 60.0, 0.03, 0.03);
      // if (!success)
      // {
      //   std::cerr << "Gripper failed to grasp object." << std::endl;
      // }
      // return success;
      return gripper_.move(0.0, 0.1);
    }
    catch (const franka::Exception &e)
    {
      std::cerr << "closeGripper failed: " << e.what() << std::endl;
      return false;
    }
  }
  void ArmFranka::setDefaultBehavior(franka::Robot &robot)
  {
    robot.setCollisionBehavior(
        {{20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0}}, {{20.0, 20.0, 20.0, 20.0, 20.0, 20.0, 20.0}},
        {{10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0}}, {{10.0, 10.0, 10.0, 10.0, 10.0, 10.0, 10.0}},
        {{20.0, 20.0, 20.0, 20.0, 20.0, 20.0}}, {{20.0, 20.0, 20.0, 20.0, 20.0, 20.0}},
        {{10.0, 10.0, 10.0, 10.0, 10.0, 10.0}}, {{10.0, 10.0, 10.0, 10.0, 10.0, 10.0}});
    robot.setJointImpedance({{3000, 3000, 3000, 2500, 2500, 2000, 2000}});
    robot.setCartesianImpedance({{3000, 3000, 3000, 300, 300, 300}});
  }

  void ArmFranka::controlLoop()
  {
    // 固定阻抗控制参数
    const Eigen::Matrix<double, 7, 1> Kp((Eigen::Matrix<double, 7, 1>() << 240.0, 240.0, 240.0, 240.0, 100.0, 80.0, 50.0).finished());
    const Eigen::Matrix<double, 7, 1> Kd((Eigen::Matrix<double, 7, 1>() << 20.0, 20.0, 20.0, 10.0, 10.0, 10.0, 10.0).finished());
    const double k_alpha = 0.99;

    // 目标位置缓存
    std::array<double, 7> local_target;

    robot_.control(
        [&](const franka::RobotState &rs, franka::Duration /*period*/) -> franka::Torques
        {
          {
            std::lock_guard<std::mutex> lock(target_mutex_);
            local_target = target_position_;
          }

          // 当前状态
          Eigen::Matrix<double, 7, 1> q, dq;
          for (int i = 0; i < 7; ++i)
          {
            q(i) = rs.q[i];
            state_[i] = rs.q[i] * 180.0 / M_PI;
            dq(i) = rs.dq[i];
          }

          // 目标状态
          Eigen::Matrix<double, 7, 1> q_goal;
          for (int i = 0; i < 7; ++i)
          {
            q_goal(i) = local_target[i];
          }

          // 一阶低通滤波
          dq_filtered_ = (1.0 - k_alpha) * dq_filtered_ + k_alpha * dq;

          // 力矩计算：τ = Kp*(q_goal - q) - Kd*dq_filtered
          Eigen::Matrix<double, 7, 1> tau_d =
              Kp.cwiseProduct(q_goal - q) +
              Kd.cwiseProduct(-dq_filtered_);

          // 输出
          std::array<double, 7> tau_cmd{};
          Eigen::VectorXd::Map(tau_cmd.data(), 7) = tau_d;

          // 可选终止：误差收敛或退出控制模式
          double max_err = (q_goal - q).cwiseAbs().maxCoeff();
          if (!isServoingMode)
          {
            control_running_ = false;
            std::cout << "控制结束: err=" << max_err << std::endl;
            return franka::MotionFinished(franka::Torques(tau_cmd));
          }

          return franka::Torques(tau_cmd);
        });
  }
  void ArmFranka::gripperFeedbackLoop()
  {
    while (true)
    {
      franka::GripperState state = gripper_.readOnce();
      gripper_width_ = state.width;
      is_grasped_ = state.is_grasped;
    }
  }
  MotionGenerator::MotionGenerator(double speed_factor, const std::array<double, 7> q_goal)
      : q_goal_(q_goal.data())
  {
    dq_max_ *= speed_factor;
    ddq_max_start_ *= speed_factor;
    ddq_max_goal_ *= speed_factor;
    dq_max_sync_.setZero();
    q_start_.setZero();
    delta_q_.setZero();
    t_1_sync_.setZero();
    t_2_sync_.setZero();
    t_f_sync_.setZero();
    q_1_.setZero();
  }

  bool MotionGenerator::calculateDesiredValues(double t, Vector7d *delta_q_d) const
  {
    // 初始化运动方向标记（1正方向，-1负方向）
    Vector7i sign_delta_q;
    sign_delta_q << delta_q_.cwiseSign().cast<int>();

    // 计算各阶段同步时间参数
    Vector7d t_d = t_2_sync_ - t_1_sync_;            // 匀速阶段持续时间
    Vector7d delta_t_2_sync = t_f_sync_ - t_2_sync_; // 减速阶段时间窗口
    std::array<bool, 7> joint_motion_finished{};     // 关节运动完成标记

    // 遍历7个关节计算期望位置
    for (size_t i = 0; i < 7; i++)
    {
      // 检查关节运动是否已完成（位置误差小于阈值）
      if (std::abs(delta_q_[i]) < kDeltaQMotionFinished)
      {
        (*delta_q_d)[i] = 0;
        joint_motion_finished[i] = true;
      }
      else
      {
        // 根据当前时间t所处的运动阶段计算位置
        if (t < t_1_sync_[i])
        { // 加速阶段
          // 三次多项式轨迹：q(t) = q0 + dq_max * (0.5*t³/(t1³) - t³/(2*t1²))
          (*delta_q_d)[i] = -1.0 / std::pow(t_1_sync_[i], 3.0) * dq_max_sync_[i] * sign_delta_q[i] *
                            (0.5 * t - t_1_sync_[i]) * std::pow(t, 3.0);
        }
        else if (t >= t_1_sync_[i] && t < t_2_sync_[i])
        { // 匀速阶段
          // 线性运动：q(t) = q1 + dq_max*(t - t1)
          (*delta_q_d)[i] = q_1_[i] + (t - t_1_sync_[i]) * dq_max_sync_[i] * sign_delta_q[i];
        }
        else if (t >= t_2_sync_[i] && t < t_f_sync_[i])
        { // 减速阶段
          // 混合多项式轨迹，实现平滑停止
          (*delta_q_d)[i] = delta_q_[i] + 0.5 * (1.0 / std::pow(delta_t_2_sync[i], 3.0) * (t - t_1_sync_[i] - 2.0 * delta_t_2_sync[i] - t_d[i]) * std::pow((t - t_1_sync_[i] - t_d[i]), 3.0) + (2.0 * t - 2.0 * t_1_sync_[i] - delta_t_2_sync[i] - 2.0 * t_d[i])) * dq_max_sync_[i] * sign_delta_q[i];
        }
        else
        { // 运动完成
          (*delta_q_d)[i] = delta_q_[i];
          joint_motion_finished[i] = true;
        }
      }
    }

    // 当所有关节运动完成时返回true
    return std::all_of(joint_motion_finished.cbegin(), joint_motion_finished.cend(),
                       [](bool x)
                       { return x; });
  }

  void MotionGenerator::calculateSynchronizedValues()
  {
    // 初始化运动参数容器
    Vector7d dq_max_reach(dq_max_);             // 各关节实际可达最大速度
    Vector7d t_f = Vector7d::Zero();            // 各关节预估总时间
    Vector7d delta_t_2 = Vector7d::Zero();      // 减速阶段时间
    Vector7d t_1 = Vector7d::Zero();            // 加速阶段时间
    Vector7d delta_t_2_sync = Vector7d::Zero(); // 同步后的减速阶段时间
    Vector7i sign_delta_q;                      // 运动方向标记（1正/-1负）
    sign_delta_q << delta_q_.cwiseSign().cast<int>();

    // 第一阶段：计算各关节初始时间参数
    for (size_t i = 0; i < 7; i++)
    {
      if (std::abs(delta_q_[i]) > kDeltaQMotionFinished)
      {
        // 当运动距离较小时，调整最大速度避免过冲
        if (std::abs(delta_q_[i]) < (3.0 / 4.0 * (std::pow(dq_max_[i], 2.0) / ddq_max_start_[i]) +
                                     3.0 / 4.0 * (std::pow(dq_max_[i], 2.0) / ddq_max_goal_[i])))
        {
          dq_max_reach[i] = std::sqrt(4.0 / 3.0 * delta_q_[i] * sign_delta_q[i] *
                                      (ddq_max_start_[i] * ddq_max_goal_[i]) /
                                      (ddq_max_start_[i] + ddq_max_goal_[i]));
        }
        // 计算各阶段基础时间参数
        t_1[i] = 1.5 * dq_max_reach[i] / ddq_max_start_[i];      // 加速阶段时间
        delta_t_2[i] = 1.5 * dq_max_reach[i] / ddq_max_goal_[i]; // 减速阶段时间
        t_f[i] = t_1[i] / 2 + delta_t_2[i] / 2 +                 // 总时间 = 加速时间/2 + 减速时间/2 + 匀速时间
                 std::abs(delta_q_[i]) / dq_max_reach[i];        // 匀速阶段持续时间
      }
    }

    // 第二阶段：同步所有关节运动时间
    double max_t_f = t_f.maxCoeff(); // 获取最长的关节运动时间
    for (size_t i = 0; i < 7; i++)
    {
      if (std::abs(delta_q_[i]) > kDeltaQMotionFinished)
      {
        // 解二次方程求同步后的最大速度：a*dq² + b*dq + c = 0
        double a = 1.5 / 2 * (ddq_max_goal_[i] + ddq_max_start_[i]);
        double b = -1.0 * max_t_f * ddq_max_goal_[i] * ddq_max_start_[i];
        double c = std::abs(delta_q_[i]) * ddq_max_goal_[i] * ddq_max_start_[i];
        double delta = b * b - 4 * a * c;

        // 计算有效解
        dq_max_sync_[i] = (-b - std::sqrt(std::max(delta, 0.0))) / (2 * a);

        // 计算同步后的时间参数
        t_1_sync_[i] = 1.5 * dq_max_sync_[i] / ddq_max_start_[i];     // 同步加速时间
        delta_t_2_sync[i] = 1.5 * dq_max_sync_[i] / ddq_max_goal_[i]; // 同步减速时间
        t_f_sync_[i] = t_1_sync_[i] / 2 + delta_t_2_sync[i] / 2 +     // 同步总时间
                       std::abs(delta_q_[i] / dq_max_sync_[i]);
        t_2_sync_[i] = t_f_sync_[i] - delta_t_2_sync[i]; // 匀速阶段结束时间

        // 计算加速阶段结束时的位置
        q_1_[i] = dq_max_sync_[i] * sign_delta_q[i] * (0.5 * t_1_sync_[i]);
      }
    }
  }

  franka::JointPositions MotionGenerator::operator()(const franka::RobotState &robot_state,
                                                     franka::Duration period)
  {
    time_ += period.toSec(); // 累计运动时间

    // 初始化阶段：获取起始位置并计算运动参数
    if (time_ == 0.0)
    {
      q_start_ = Vector7d(robot_state.q.data()); // 记录初始关节位置
      delta_q_ = q_goal_ - q_start_;             // 计算目标位置与初始位置的差值
      calculateSynchronizedValues();             // 计算同步运动参数
    }

    Vector7d delta_q_d;                                               // 当前时刻的关节位置增量
    bool motion_finished = calculateDesiredValues(time_, &delta_q_d); // 生成轨迹点

    // 构建输出关节位置指令
    std::array<double, 7> joint_positions;
    Eigen::VectorXd::Map(&joint_positions[0], 7) = (q_start_ + delta_q_d); // 将Eigen向量映射到数组
    franka::JointPositions output(joint_positions);                        // 创建控制指令
    output.motion_finished = motion_finished;                              // 设置运动完成标志
    return output;
  }
}

