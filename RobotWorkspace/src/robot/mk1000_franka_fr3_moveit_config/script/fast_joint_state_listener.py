#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState

class JointStateListener(Node):
    def __init__(self):
        super().__init__('joint_state_listener')
        
        # 创建订阅者，订阅 /joint_states 话题
        self.subscription = self.create_subscription(
            JointState,
            '/joint_states',
            self.listener_callback,
            10)
        self.subscription  

    def listener_callback(self, msg):
        joint_names = msg.name
        joint_positions = msg.position
        left_prefix = 'left_'
        right_prefix = 'right_'
        arm_id = 'fr3'

        # 输出 group_state XML 格式
        print('<group_state name="test_pose" group="dual_arm">')
        
        print('  <!-- Left Arm -->')
        # 遍历所有关节，筛选出左臂的关节
        for i, joint_name in enumerate(joint_names):
            if joint_name.startswith(left_prefix):  # 如果是左臂关节
                joint_value = joint_positions[i]
                print(f'  <joint name="{joint_name}" value="{joint_value}"/>')

        print('  <!-- Right Arm -->')
        # 遍历所有关节，筛选出右臂的关节
        for i, joint_name in enumerate(joint_names):
            if joint_name.startswith(right_prefix):  # 如果是右臂关节
                joint_value = joint_positions[i]
                print(f'  <joint name="{joint_name}" value="{joint_value}"/>')
        
        print('</group_state>')

def main(args=None):
    rclpy.init(args=args)

    joint_state_listener = JointStateListener()

    # 循环，保持节点运行
    rclpy.spin(joint_state_listener)

    # 销毁节点
    joint_state_listener.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
