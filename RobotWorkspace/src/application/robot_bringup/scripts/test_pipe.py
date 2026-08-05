#!/usr/bin/env python3
import os
from pathlib import Path

import cv2
import pandas as pd
from tqdm import tqdm

# ==================== 配置 ====================

# 这一天的 episode 根目录
BASE_DIR = "/data/parse/2025-12-05"

# episode csv 所在的子目录名
EPISODES_DIR_NAME = "episodes_5hz"

# CSV 中记录主视角相机相对路径的列名
IMAGE_COL = "Image"

# 视频帧率（按你原始/处理后数据设置）
FPS = 5

# =================================================


def build_video_for_episode_csv(traj_dir: Path, episode_csv: Path):
    """
    针对单个 episode_*.csv 重建一个 mp4 视频。
    - traj_dir: 轨迹根目录（例如 .../2025-12-05/15:40:01）
    - episode_csv: 该轨迹下 episodes/episode_0.csv
    """
    print(f"[INFO] 处理 {episode_csv}")

    df = pd.read_csv(episode_csv)
    if IMAGE_COL not in df.columns:
        print(f"[WARN] {episode_csv} 中没有列 '{IMAGE_COL}'，跳过。")
        return

    image_rel_paths = df[IMAGE_COL].tolist()
    if len(image_rel_paths) == 0:
        print(f"[WARN] {episode_csv} 中 Image 列为空，跳过。")
        return

    # 找到第一张能成功读取的图片以确定分辨率
    first_frame = None
    for rel in image_rel_paths:
        abs_path = traj_dir / rel
        if abs_path.exists():
            img = cv2.imread(str(abs_path))
            if img is not None:
                first_frame = img
                break

    if first_frame is None:
        print(f"[ERROR] 在 {episode_csv} 对应的图片中找不到任何可读帧，跳过。")
        return

    height, width, _ = first_frame.shape
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")

    # 视频输出：和 episode_x.csv 同目录，改扩展名为 .mp4
    out_video_path = episode_csv.with_suffix(".mp4")
    out = cv2.VideoWriter(str(out_video_path), fourcc, FPS, (width, height))

    # 按 CSV 行的顺序写入每一帧
    for rel in tqdm(image_rel_paths, desc=f"{episode_csv.name} -> video", leave=False):
        abs_path = traj_dir / rel
        frame = cv2.imread(str(abs_path))
        if frame is None:
            print(f"[WARN] 无法读取图片: {abs_path}，跳过该帧。")
            continue
        out.write(frame)

    out.release()
    print(f"[OK] 保存视频: {out_video_path}")


def process_trajectory(traj_dir: Path):
    """
    对单个轨迹目录：
    - 找到 episodes/ 目录
    - 针对其中的每个 episode_*.csv 重建一个 mp4
    """
    episodes_dir = traj_dir / EPISODES_DIR_NAME
    if not episodes_dir.exists() or not episodes_dir.is_dir():
        print(f"[WARN] 轨迹 {traj_dir.name} 下没有 {EPISODES_DIR_NAME}/ 目录，跳过。")
        return

    # 找出所有 .csv（你也可以限制前缀 episode_）
    episode_csvs = sorted(
        [p for p in episodes_dir.glob("*.csv") if p.is_file()]
    )
    if not episode_csvs:
        print(f"[WARN] {episodes_dir} 下没有 episode csv，跳过。")
        return

    print(f"[INFO] 轨迹 {traj_dir.name} 下发现 {len(episode_csvs)} 个 episode csv")

    for csv_path in episode_csvs:
        build_video_for_episode_csv(traj_dir, csv_path)


def main():
    base = Path(BASE_DIR)
    if not base.exists():
        print(f"[ERROR] BASE_DIR 不存在: {BASE_DIR}")
        return

    # 遍历当天所有轨迹目录
    traj_dirs = sorted([d for d in base.iterdir() if d.is_dir()])
    if not traj_dirs:
        print(f"[WARN] {BASE_DIR} 下找不到任何轨迹目录。")
        return

    print(f"[INFO] 在 {BASE_DIR} 下发现 {len(traj_dirs)} 条轨迹：")
    for d in traj_dirs:
        print(" -", d.name)
    print()

    for traj_dir in traj_dirs:
        process_trajectory(traj_dir)


if __name__ == "__main__":
    main()
