#!/usr/bin/env python3
import sys
import select
import termios
import tty
import requests
import os

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from std_msgs.msg import Float32, Bool
from sensor_msgs.msg import Image, JointState

from datetime import datetime
from topic_recorder import TopicRecorder

def send_message_to_local_host(message):
    url = 'http://192.168.3.14:5000/receive_message'
    data = {'message': message}
    requests.post(url, json=data)

class LoggingNode(Node):
    def __init__(self):
        super().__init__("teleop_logging_node")

        # Subscribers
        self.arm_sub = TopicRecorder("arm_log", "/slave_arm/right/joint_states", "sensor_msgs/JointState")
        self.cam_sub = TopicRecorder("cam_log", "/pc_arm/body_camera/color/image_raw", "sensor_msgs/Image")
        self.wrist_cam_sub = TopicRecorder("wrist_cam_log", "/pc_arm/wrist_camera/color/image_raw", "sensor_msgs/Image")
        self.gripper_sub = TopicRecorder("gripper_log", "/gripper_control_signal", "std_msgs/Float32")
        self.logging_control_sub = self.create_subscription(Bool, "/logging_control_signal", self.logging_control_callback, 10)
        self.gripper_control_sub = self.create_subscription(Float32, "/gripper_control_signal", self.gripper_control_callback, 10)

        # Control Signal & Path Preparation
        self.start_text = "Start"
        self.end_text = "End"
        self.gripper_open_text = "Gripper Opening"
        self.gripper_close_text = "Gripper Closing"
        self.loggingprefix = ''

    def logging_control_callback(self, msg: Bool):
        if msg.data:
            self.start_logging()
        elif not msg.data:
            self.end_logging()
    
    def gripper_control_callback(self, msg: Float32):
        if msg.data < 0.04:
            send_message_to_local_host(self.gripper_close_text)
        elif msg.data >= 0.04:
            send_message_to_local_host(self.gripper_open_text)

    def start_logging(self,):
        self.get_logger().info("Start Logging")
        send_message_to_local_host(self.start_text)
        now = datetime.now()
        self.loggingprefix = now.strftime("%Y-%m-%d %H:%M:%S")
        self.data_path = f"{os.environ['WORKDIR']}/data/bags/{self.loggingprefix}"
        os.makedirs(self.data_path, exist_ok=True)
        
        self.arm_sub.start_recording(self.data_path, "joint")
        self.cam_sub.start_recording(self.data_path, "image")
        self.wrist_cam_sub.start_recording(self.data_path, "wrist_image")
        self.gripper_sub.start_recording(self.data_path, "gripper")

    def end_logging(self,):
        self.get_logger().info("End Logging")
        send_message_to_local_host(self.end_text)
        
        self.arm_sub.stop_recording()
        self.cam_sub.stop_recording()
        self.wrist_cam_sub.stop_recording()
        self.gripper_sub.stop_recording()


if __name__ == "__main__":
    rclpy.init()
    node = LoggingNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)
    executor.add_node(node.arm_sub)
    executor.add_node(node.cam_sub)
    executor.add_node(node.wrist_cam_sub)
    executor.add_node(node.gripper_sub)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.arm_sub.destroy_node()
        node.cam_sub.destroy_node()
        node.wrist_cam_sub.destroy_node()
        node.gripper_sub.destroy_node()
        node.destroy_node()
        rclpy.shutdown()
