#!/usr/bin/env python3
import os
import re
import datetime
import importlib
import time

import rclpy
from rclpy.qos import qos_profile_sensor_data
from rclpy.node import Node
from rclpy.serialization import serialize_message
from sensor_msgs.msg import Image, JointState
import rosbag2_py


class TopicRecorder(Node):
    def __init__(self, node_name: str, topic_name: str, msg_type_str: str):
        """
        :param topic_name: 例如 '/pc_arm/body_camera/color/image_raw'
        :param msg_type_str: 例如 'sensor_msgs/Image'
        """
        super().__init__(node_name)

        self.topic_name = topic_name
        self.msg_type_str = msg_type_str
        self.msg_type = self.get_msg_class(self.msg_type_str)

        if self.msg_type is None:
            self.get_logger().error(f"Failed to load message type: {self.msg_type_str}")
            raise ValueError("Invalid message type provided")

        # 订阅 topic
        self.subscription = self.create_subscription(
            self.msg_type,
            self.topic_name,
            self._callback,
            1000
        )

        self.writer = None          # rosbag2_py writer
        self.is_recording = False
        self.bag_topic_registered = False

    def _callback(self, msg):
        # self.get_logger().info("Get Msg")
        if self.is_recording and self.writer is not None:
            # 优先使用消息本身的时间戳（std_msgs/Header）
            timestamp = None
            if hasattr(msg, 'header') and hasattr(msg.header, 'stamp'):
                # ROS2 Time -> int nanoseconds
                timestamp = msg.header.stamp.sec * 10**9 + msg.header.stamp.nanosec
            else:
                # 没有 header 的情况，退回到本地 clock
                self.get_logger().warn("Message has no header.stamp, falling back to node clock time.")
                timestamp = self.get_clock().now().nanoseconds

            serialized = serialize_message(msg)
            self.writer.write(self.topic_name, serialized, timestamp)

    def start_recording(self,
                        path_name=None,
                        bag_name=None):
        """
        :param path_name: bag 存放根目录，默认 $WORKDIR/data/bags 或 ./bags
        :param bag_name: bag 目录名，默认: <sanitized_topic>_YYYYmmdd_HHMMSS
        """
        if path_name is None:
            default_root = os.path.join(os.environ.get('WORKDIR', os.getcwd()), "data", "bags")
            path_name = default_root

        if not os.path.exists(path_name):
            os.makedirs(path_name, exist_ok=True)

        if bag_name is None:
            sanitized_topic_name = re.sub(r'[^\w\s-]', '_', self.topic_name)
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            bag_name = f"{sanitized_topic_name}_{timestamp}"

        # rosbag2 是一个目录，不是单个 .bag 文件
        full_bag_path = os.path.join(path_name, bag_name)

        # 等待有 publisher 连接上来（类似 rospy.wait_for_message 的逻辑）
        if self.count_publishers(self.topic_name) == 0:
            self.get_logger().warn(
                f"No publishers connected to {self.topic_name}. Waiting for connection..."
            )
            while rclpy.ok() and self.count_publishers(self.topic_name) == 0:
                time.sleep(0.1)
            self.get_logger().info(
                f"Publisher found for {self.topic_name}. Starting recording."
            )

        # 配置 rosbag2 writer
        storage_options = rosbag2_py.StorageOptions(
            uri=full_bag_path,        # 输出目录
            storage_id='sqlite3',     # 一般默认 sqlite3
        )
        converter_options = rosbag2_py.ConverterOptions(
            input_serialization_format='cdr',
            output_serialization_format='cdr',
        )

        self.writer = rosbag2_py.SequentialWriter()
        self.writer.open(storage_options, converter_options)

        # 注册 topic 元数据（只需要一次）
        topic_metadata = rosbag2_py.TopicMetadata(
            name=self.topic_name,
            type=self.get_ros2_msg_type_str(self.msg_type),
            serialization_format='cdr',
        )
        self.writer.create_topic(topic_metadata)
        self.bag_topic_registered = True

        self.is_recording = True
        self.get_logger().info(f"Recording to {full_bag_path}")

    def stop_recording(self):
        if self.writer is not None:
            # rosbag2_py 的 writer 没有单独的 close，赋 None 即可结束写入
            self.writer = None
        self.is_recording = False
        self.get_logger().info("Recording stopped.")

    # ----------------- 工具函数 -----------------

    def get_msg_class(self, msg_type: str):
        """
        输入类似 'robot_arm_pkg/ArmStatusMsg'
        返回 Python 消息类 robot_arm_pkg.msg.ArmStatusMsg
        """
        try:
            pkg, name = msg_type.split('/')
            module = importlib.import_module(f"{pkg}.msg")
            return getattr(module, name)
        except Exception as e:
            self.get_logger().error(
                f"Error importing message type {msg_type}: {e}"
            )
            return None

    @staticmethod
    def get_ros2_msg_type_str(msg_cls) -> str:
        """
        将消息类转换为 ROS2 类型字符串，比如：
        <class 'sensor_msgs.msg._image.Image'> -> 'sensor_msgs/msg/Image'
        """
        module = msg_cls.__module__     # 如 'sensor_msgs.msg._image'
        pkg = module.split('.')[0]      # 'sensor_msgs'
        name = msg_cls.__name__         # 'Image'
        return f"{pkg}/msg/{name}"


            
def main():
    rclpy.init()
    try:
        # 示例：和你原来的 main 保持类似
        recorder = TopicRecorder('right_arm_status', 'robot_arm_pkg/ArmStatusMsg')

        # 开始录制（路径和 bag 名可以不传，走默认）
        recorder.start_recording()

        # 这里简单 spin，一直到 Ctrl+C
        try:
            rclpy.spin(recorder)
        except KeyboardInterrupt:
            recorder.get_logger().info("KeyboardInterrupt, stopping recorder...")

        recorder.stop_recording()
    except ValueError as e:
        print(e)
    finally:
        if 'recorder' in locals():
            recorder.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()