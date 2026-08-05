#!/usr/bin/env python3
import os
import csv
import importlib
from concurrent.futures import ProcessPoolExecutor, as_completed

from rclpy.serialization import deserialize_message
import rosbag2_py

from rich.progress import Progress

from cv_bridge import CvBridge
import cv2


# ==================== 通用工具 ====================

def get_msg_class_from_type(type_str: str):
    """
    输入: 'sensor_msgs/msg/Image' 或 'sensor_msgs/msg/CompressedImage'
    返回对应 Python 消息类，例如 sensor_msgs.msg.Image / CompressedImage
    """
    pkg, _, name = type_str.split('/')  # e.g. 'sensor_msgs', 'msg', 'Image'
    module = importlib.import_module(f"{pkg}.msg")
    return getattr(module, name)


def create_reader(bag_path: str):
    """
    :param bag_path: rosbag2 目录，而不是 .db3 文件
    :return: (reader, topic_type_map)
    """
    if not os.path.isdir(bag_path):
        raise FileNotFoundError(f"{bag_path} is not a directory")

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

    topics_meta = reader.get_all_topics_and_types()
    topic_type_map = {}  # topic_name -> (type_str, msg_cls)
    for t in topics_meta:
        msg_cls = get_msg_class_from_type(t.type)
        topic_type_map[t.name] = (t.type, msg_cls)

    if not topic_type_map:
        raise RuntimeError(f"No topics found in bag: {bag_path}")

    return reader, topic_type_map


def ros_time_to_ms(msg, t_ns: int):
    """
    优先使用 msg.header.stamp，若没有 header，则退回 bag 记录时间 t_ns。
    返回: int 毫秒
    """
    if hasattr(msg, "header") and hasattr(msg.header, "stamp"):
        sec = int(msg.header.stamp.sec)
        nsec = int(msg.header.stamp.nanosec)
        return sec * 1000 + nsec // 1_000_000
    return int(t_ns // 1_000_000)


# ==================== Joint 解析 ====================

def parse_joint_bag(bag_dir: str, out_csv: str):
    print(f"[Joint] Parsing joint bag: {bag_dir}")
    reader, topic_type_map = create_reader(bag_dir)

    # 找 JointState topic（如果只有一个 topic 就直接用）
    joint_topic = None
    for name, (type_str, _) in topic_type_map.items():
        if type_str == "sensor_msgs/msg/JointState":
            joint_topic = name
            break
    if joint_topic is None:
        joint_topic = list(topic_type_map.keys())[0]
        print(f"[Joint][WARN] No JointState topic found, using first topic: {joint_topic}")

    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    count = 0

    with open(out_csv, "w", newline="") as f:
        writer = csv.writer(f)
        header = ["Time"] + [f"Joint{i}" for i in range(1, 8)]
        writer.writerow(header)

        while reader.has_next():
            topic, data, t_ns = reader.read_next()
            if topic != joint_topic:
                continue

            type_str, msg_cls = topic_type_map[topic]
            msg = deserialize_message(data, msg_cls)

            time_ms = ros_time_to_ms(msg, t_ns)

            positions = list(getattr(msg, "position", []))
            positions = (positions + [0.0] * 7)[:7]
            row = [time_ms] + positions
            writer.writerow(row)
            count += 1

    print(f"[Joint] Saved {count} rows to {out_csv}")


# ==================== Gripper 解析 ====================

def get_gripper_value(msg):
    if hasattr(msg, "data"):
        return msg.data
    raise AttributeError("Cannot find gripper state field on message.")


def parse_gripper_bag(bag_dir: str, out_csv: str):
    print(f"[Gripper] Parsing gripper bag: {bag_dir}")
    reader, topic_type_map = create_reader(bag_dir)

    gripper_topic = list(topic_type_map.keys())[0]

    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    count = 0

    with open(out_csv, "w", newline="") as f:
        writer = csv.writer(f)
        header = ["Time", "Gripper_State"]
        writer.writerow(header)

        while reader.has_next():
            topic, data, t_ns = reader.read_next()
            if topic != gripper_topic:
                continue

            type_str, msg_cls = topic_type_map[topic]
            msg = deserialize_message(data, msg_cls)

            time_ms = ros_time_to_ms(msg, t_ns)
            try:
                value = get_gripper_value(msg)
            except AttributeError:
                print("[Gripper][WARN] message has no 'data' field, using 0")
                value = 0.0

            writer.writerow([time_ms, value])
            count += 1

    print(f"[Gripper] Saved {count} rows to {out_csv}")


# ==================== Image / Wrist Image 解析（CompressedImage -> JPEG） ====================

def parse_image_bag(
    bag_dir: str,
    out_dir: str,
    rel_subdir: str,
    csv_path: str,
    csv_col_name: str,
):
    """
    解析 image / wrist_image：
    - topic 类型为 sensor_msgs/msg/CompressedImage 或 sensor_msgs/msg/Image
    - 输出 JPEG: {index}.jpg
    - 生成 csv 记录 Time(ms)、相对路径，如 image/0.jpg 或 wrist_image/0.jpg
    """
    print(f"[Image] Parsing image bag: {bag_dir}")
    reader, topic_type_map = create_reader(bag_dir)

    image_topic = None
    image_type_str = None

    # 优先找 CompressedImage
    for name, (type_str, _) in topic_type_map.items():
        if type_str == "sensor_msgs/msg/CompressedImage":
            image_topic = name
            image_type_str = type_str
            break

    # 如果没有 CompressedImage，再找普通 Image
    if image_topic is None:
        for name, (type_str, _) in topic_type_map.items():
            if type_str == "sensor_msgs/msg/Image":
                image_topic = name
                image_type_str = type_str
                break

    if image_topic is None:
        image_topic = list(topic_type_map.keys())[0]
        image_type_str, _ = topic_type_map[image_topic]
        print(f"[Image][WARN] No Image/CompressedImage topic found, using first topic: {image_topic} ({image_type_str})")
    else:
        print(f"[Image] Using topic: {image_topic} ({image_type_str})")

    bridge = CvBridge()
    os.makedirs(out_dir, exist_ok=True)

    os.makedirs(os.path.dirname(csv_path), exist_ok=True)
    count = 0

    with open(csv_path, "w", newline="") as f_csv:
        writer = csv.writer(f_csv)
        writer.writerow(["Time", csv_col_name])

        idx = 0
        while reader.has_next():
            topic, data, t_ns = reader.read_next()
            if topic != image_topic:
                continue

            type_str, msg_cls = topic_type_map[topic]
            msg = deserialize_message(data, msg_cls)

            time_ms = ros_time_to_ms(msg, t_ns)

            # 文件名 {index}.jpg
            fname = f"{idx}.jpg"
            abs_path = os.path.join(out_dir, fname)
            rel_path = os.path.join(rel_subdir, fname)

            # 解码
            if type_str == "sensor_msgs/msg/CompressedImage":
                cv_img = bridge.compressed_imgmsg_to_cv2(msg, desired_encoding="bgr8")
            elif type_str == "sensor_msgs/msg/Image":
                cv_img = bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            else:
                print(f"[Image][WARN] Unsupported image type: {type_str}, skip")
                continue

            # 保存 JPEG
            cv2.imwrite(abs_path, cv_img)

            writer.writerow([time_ms, rel_path])
            idx += 1
            count += 1

    print(f"[Image] Saved {count} JPEGs to {out_dir}")
    print(f"[Image] Frame index csv saved to {csv_path}")


# ==================== 单条轨迹解析 ====================

def parse_trajectory(traj_dir: str, out_root: str):
    """
    traj_dir 例如: /home/rpp/rpp_ws/data/bags/2025-12-05/15:40:01
    其下有: joint/, gripper/, image/, wrist_image/

    out_root 对应解析输出根目录，例如:
    /data/parse/2025-12-05/15:40:01
    """
    print(f"========== Parsing trajectory ==========")
    print(f"  traj_dir : {traj_dir}")
    print(f"  out_root : {out_root}")

    joint_dir = os.path.join(traj_dir, "joint")
    gripper_dir = os.path.join(traj_dir, "gripper")
    image_bag_dir = os.path.join(traj_dir, "image")
    wrist_image_bag_dir = os.path.join(traj_dir, "wrist_image")

    # 1. joint -> joint_states.csv
    if os.path.isdir(joint_dir):
        parse_joint_bag(
            joint_dir,
            os.path.join(out_root, "joint_states.csv")
        )
    else:
        print(f"[WARN] joint dir not found: {joint_dir}")

    # 2. gripper -> gripper_state.csv
    if os.path.isdir(gripper_dir):
        parse_gripper_bag(
            gripper_dir,
            os.path.join(out_root, "gripper_state.csv")
        )
    else:
        print(f"[WARN] gripper dir not found: {gripper_dir}")

    # 3. image -> image/{index}.jpg + frame.csv
    if os.path.isdir(image_bag_dir):
        parse_image_bag(
            image_bag_dir,
            os.path.join(out_root, "image"),          # 图片输出目录
            "image",                                  # 相对路径前缀
            os.path.join(out_root, "frame.csv"),      # csv 路径
            "Image",                                  # csv 列名
        )
    else:
        print(f"[WARN] image dir not found: {image_bag_dir}")

    # 4. wrist_image -> wrist_image/{index}.jpg + wrist_frame.csv
    if os.path.isdir(wrist_image_bag_dir):
        parse_image_bag(
            wrist_image_bag_dir,
            os.path.join(out_root, "wrist_image"),
            "wrist_image",
            os.path.join(out_root, "wrist_frame.csv"),
            "Wrist_Image",
        )
    else:
        print(f"[WARN] wrist_image dir not found: {wrist_image_bag_dir}")

    print(f"[OK] All parsed data saved under: {out_root}\n")


# ==================== 整个日期目录解析（多进程并行） ====================

def parse_date_folder(bag_date_dir: str,
                      parse_root_base: str = "/data/parse",
                      max_workers: int | None = None):
    """
    例如:
    bag_date_dir   = /home/rpp/rpp_ws/data/bags/2025-12-05
    parse_root_base= /data/parse

    会遍历 2025-12-05 下的每个子目录（每个子目录是一条轨迹），
    并将解析结果写入:
    /data/parse/2025-12-05/<轨迹名>/...
    """
    if not os.path.isdir(bag_date_dir):
        raise FileNotFoundError(f"{bag_date_dir} is not a directory")

    date_name = os.path.basename(os.path.normpath(bag_date_dir))
    parse_date_root = os.path.join(parse_root_base, date_name)

    # 找出所有轨迹子目录
    traj_dirs = []
    for entry in sorted(os.listdir(bag_date_dir)):
        traj_dir = os.path.join(bag_date_dir, entry)
        if os.path.isdir(traj_dir):
            out_root = os.path.join(parse_date_root, entry)
            traj_dirs.append((traj_dir, out_root))

    if not traj_dirs:
        print(f"[WARN] no trajectory dirs found under {bag_date_dir}")
        return

    # 默认 worker 数：CPU 核心数的一半（至少 1）
    if max_workers is None:
        try:
            cpu_cnt = os.cpu_count() or 1
            max_workers = max(1, cpu_cnt // 2)
        except Exception:
            max_workers = 4

    print(f"[INFO] Found {len(traj_dirs)} trajectories, using {max_workers} workers.")

    # 多进程并行解析每条轨迹
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = []
        for traj_dir, out_root in traj_dirs:
            futures.append(
                executor.submit(parse_trajectory, traj_dir, out_root)
            )

        with Progress() as progress:
            task = progress.add_task("[cyan]Parsing trajectories...", total=len(futures))

            for fut in as_completed(futures):
                # 如果有异常，直接在这里抛出来方便调试
                exc = fut.exception()
                if exc is not None:
                    raise exc
                
                progress.update(task, advance=1)


# ==================== main ====================

if __name__ == "__main__":
    # 例如：你现在要处理 /home/rpp/rpp_ws/data/bags/2025-12-05 下面所有轨迹
    BAG_DATE_DIR = "/home/rpp/rpp_ws/data/bags/2025-12-05"
    PARSE_ROOT_BASE = "/data/parse"

    # 确保 /data/parse 有写权限（之前已经用 sudo mkdir / sudo chown 处理过）
    os.makedirs(PARSE_ROOT_BASE, exist_ok=True)

    parse_date_folder(BAG_DATE_DIR, PARSE_ROOT_BASE)
