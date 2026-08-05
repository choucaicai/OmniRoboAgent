#!/usr/bin/env python3
import os
import csv
import argparse
import importlib

import rosbag2_py
from rclpy.serialization import deserialize_message


def get_msg_class_from_type(type_str: str):
    """
    ROS2 类型字符串 -> Python 消息类
    例如: 'sensor_msgs/msg/JointState' -> sensor_msgs.msg.JointState
    """
    pkg, _, name = type_str.split('/')  # 'sensor_msgs', 'msg', 'JointState'
    module = importlib.import_module(f"{pkg}.msg")
    return getattr(module, name)


def bag_joint_to_csv(bag_path: str, topic_name: str, output_csv: str):
    if not os.path.isdir(bag_path):
        raise FileNotFoundError(f"{bag_path} is not a directory (rosbag2 expects a directory).")

    # 1. 打开 bag
    storage_options = rosbag2_py.StorageOptions(
        uri=bag_path,
        storage_id='sqlite3',
    )
    converter_options = rosbag2_py.ConverterOptions(
        input_serialization_format='cdr',
        output_serialization_format='cdr',
    )

    reader = rosbag2_py.SequentialReader()
    reader.open(storage_options, converter_options)

    # 2. 找到目标 topic 的类型 & msg class
    topics_meta = reader.get_all_topics_and_types()
    topic_type_map = {t.name: t.type for t in topics_meta}

    if topic_name not in topic_type_map:
        raise RuntimeError(f"Topic '{topic_name}' not found in bag. Available topics: {list(topic_type_map.keys())}")

    type_str = topic_type_map[topic_name]
    msg_cls = get_msg_class_from_type(type_str)

    if type_str != "sensor_msgs/msg/JointState":
        print(f"[WARN] Topic '{topic_name}' type is '{type_str}', not 'sensor_msgs/msg/JointState'.")

    # 3. 遍历消息，写 CSV
    os.makedirs(os.path.dirname(os.path.abspath(output_csv)), exist_ok=True)

    with open(output_csv, "w", newline="") as f:
        writer = csv.writer(f)
        # 表头：时间戳 + 7 个关节
        header = ["timestamp_ms"] + [f"joint{i}" for i in range(1, 8)]
        writer.writerow(header)

        count = 0

        while reader.has_next():
            topic, data, t = reader.read_next()

            if topic != topic_name:
                continue

            msg = deserialize_message(data, msg_cls)

            # t 是写入 bag 时的 int 纳秒时间戳
            timestamp_ms = t // 1_000_000

            # 确保至少有 7 个关节
            if len(msg.position) < 7:
                print(f"[WARN] message at t={timestamp_ms} has only {len(msg.position)} positions, skip.")
                continue

            row = [timestamp_ms] + [msg.position[i] for i in range(7)]
            writer.writerow(row)
            count += 1

    print(f"Done. Wrote {count} messages to {output_csv}")


def main():
    parser = argparse.ArgumentParser(description="Convert JointState rosbag2 to CSV.")
    parser.add_argument("--bag_path", default="/home/rpp/rpp_ws/data/bags/2025-12-02 15:12:41/joint")
    parser.add_argument("--topic_name", default="/slave_arm/right/joint_states")
    parser.add_argument("--output_csv", default="/home/rpp/rpp_ws/data/bags/2025-12-02 15:12:41/joint.csv")

    args = parser.parse_args()

    bag_joint_to_csv(args.bag_path, args.topic_name, args.output_csv)


if __name__ == "__main__":
    main()
