#!/usr/bin/env python3
import sys
import select
import termios
import tty

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, Bool


class KeyboardNode(Node):
    def __init__(self):
        super().__init__('keyboard_node')

        # Publisher
        self.gripper_pub = self.create_publisher(Float32, '/gripper_control_signal', 10)
        self.logging_pub = self.create_publisher(Bool, '/logging_control_signal', 10)

        # 配置键盘为非阻塞读取
        self.old_settings = termios.tcgetattr(sys.stdin)
        tty.setcbreak(sys.stdin.fileno())

        # 创建一个计时器定时检查键盘输入（10Hz）
        self.timer = self.create_timer(0.1, self.check_keyboard)

    def check_keyboard(self):
        """非阻塞检测键盘输入"""
        if select.select([sys.stdin], [], [], 0)[0]:
            key = sys.stdin.read(1)

            if key == 'a':
                self.gripper_control(1.0) # Open Gripper
            elif key == 'q':
                self.gripper_control(0.0) # Close Gripper
            elif key == 's':
                self.logging_control(True) # Start Logging
            elif key == 'e':
                self.logging_control(False) # End Logging
            # 其他键忽略

    def gripper_control(self, value: float):
        msg = Float32()
        msg.data = value
        self.gripper_pub.publish(msg)
        self.get_logger().info(f"Published gripper_control_signal: {value}")

    def logging_control(self, value: bool):
        msg = Bool()
        msg.data = value
        self.logging_pub.publish(msg)
        self.get_logger().info(f"Published gripper_control_signal: {value}")

    def destroy_node(self):
        # 恢复键盘设置
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self.old_settings)
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = KeyboardNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
