#!/usr/bin/env python3
import os
from pathlib import Path
import paramiko

# ===================== 配置区 =====================

REMOTE_USER = "rpp"
REMOTE_PASSWORD = "passward"          # ← 在这里填写密码
REMOTE_HOST = "192.168.3.17"        # ← 服务器 IP

# 远端根目录
REMOTE_DATE_DIR = "/data/parse/2025-12-05"

# 本地保存目录（主相机 + 腕相机）
LOCAL_MAIN_DIR = "videos\main"
LOCAL_WRIST_DIR = "videos\wrist"

# 生成文件名中的日期部分
DATE_STR = "2025_12_05"

# ==================================================


def list_remote_dirs(ssh):
    """列出远端轨迹目录，如 15:40:01"""
    cmd = (
        f"cd {REMOTE_DATE_DIR} && "
        f"find . -maxdepth 1 -mindepth 1 -type d -printf '%f\n'"
    )
    stdin, stdout, stderr = ssh.exec_command(cmd)
    dirs = [d.strip() for d in stdout.read().decode().split("\n") if d.strip()]
    return dirs


def remote_file_exists(ssh, path):
    """检查远端文件是否存在"""
    cmd = f"test -f '{path}' && echo yes || echo no"
    stdin, stdout, stderr = ssh.exec_command(cmd)
    return stdout.read().decode().strip() == "yes"


def download(sftp, remote_path, local_path):
    """执行文件下载"""
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    print(f"[INFO] 下载 {remote_path} → {local_path}")
    sftp.get(remote_path, local_path)


def process_trajectory(traj, ssh, sftp):
    """下载一条轨迹的 main 和 wrist 视频"""

    if traj.count(":") != 2:
        print(f"[WARN] 跳过非时间目录：{traj}")
        return

    HH, MM, SS = traj.split(":")
    filename = f"{DATE_STR}_{HH}_{MM}_{SS}.mp4"

    # ----------- 主相机 ---------------
    remote_main = f"{REMOTE_DATE_DIR}/{traj}/video_main.mp4"
    local_main = f"{LOCAL_MAIN_DIR}/{filename}"

    if remote_file_exists(ssh, remote_main):
        download(sftp, remote_main, local_main)
    else:
        print(f"[WARN] 未找到主相机视频：{remote_main}")

    # ----------- 腕相机 ---------------
    # 文件名依你之前给的是 video_wrist.mp4，我保持一致
    remote_wrist = f"{REMOTE_DATE_DIR}/{traj}/video_wrist.mp4"
    local_wrist = f"{LOCAL_WRIST_DIR}/{filename}"

    if remote_file_exists(ssh, remote_wrist):
        download(sftp, remote_wrist, local_wrist)
    else:
        print(f"[WARN] 未找到腕部相机视频：{remote_wrist}")


def main():
    print("[INFO] 正在连接服务器...")

    # SSH 登录
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(REMOTE_HOST, username=REMOTE_USER, password=REMOTE_PASSWORD)

    sftp = ssh.open_sftp()

    # 列出轨迹
    print(f"[INFO] 读取目录：{REMOTE_DATE_DIR}")
    traj_dirs = list_remote_dirs(ssh)
    print(f"[INFO] 共发现 {len(traj_dirs)} 条轨迹：")
    for d in traj_dirs:
        print(" -", d)

    print("\n[INFO] 开始下载...\n")

    for traj in traj_dirs:
        process_trajectory(traj, ssh, sftp)

    sftp.close()
    ssh.close()

    print("\n[OK] 下载完成！")
    print(f"主相机保存在：{LOCAL_MAIN_DIR}")
    print(f"腕相机保存在：{LOCAL_WRIST_DIR}")


if __name__ == "__main__":
    main()
