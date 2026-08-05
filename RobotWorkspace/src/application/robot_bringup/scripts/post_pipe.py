#!/usr/bin/env python3
import os
import ast
from pathlib import Path

import numpy as np
import pandas as pd
import convert


class PostProcessPipeline:
    def __init__(self,
        base_dir: str = "/remote-home/share/teledata/raw/2025-12-23-split2",       # 根目录：这一天的所有轨迹
        gripper_col: str = "Gripper",                   # ee_pose_30fps.csv 中夹爪状态的列名（0/1）
        pos_eps: float = 1e-4,                          # 静止判定阈值(m)
        rot_eps: float = 1e-3,                          # 静止判定阈值(rad)
        keep_after_gripper_change: int = 5,             # 夹爪变化后额外保留的帧数（总窗口 = 1 + KEEP_AFTER）
        episodes_dir_name: str = "episodes",            # episode 目录名（30Hz + 删静止）
        episodes_5hz_dir_name: str = "episodes_5hz",    # 下采样后 episode 目录名（5Hz + 6 offset）
        downsample_step: int = 6,                       # 每 6 帧取 1 帧, 30Hz -> 5Hz
        offsets: list = list(range(6)),                 # 生成 6 条轨迹：offset 0..5
        min_len_after_ds: int = 2,                      # 下采样后长度太短就丢弃该 offset
    ):
        self.base_dir = base_dir
        self.gripper_col = gripper_col
        self.pos_eps = pos_eps
        self.rot_eps = rot_eps
        self.keep_after_gripper_change = keep_after_gripper_change
        self.episodes_dir_name = episodes_dir_name
        self.episodes_5hz_dir_name = episodes_5hz_dir_name
        self.downsample_step = downsample_step
        self.offsets = offsets
        self.min_len_after_ds = min_len_after_ds


    def parse_vec_column(self, series: pd.Series) -> np.ndarray:
        """
        把一列形如 '[-0.1, 0.2, 0.3]' 的字符串解析成 (N, 3) 数组。
        """
        arr = series.apply(ast.literal_eval).values
        return np.vstack(arr)  # (N, 3)


    def remove_static_frames(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        在一个子轨迹 df 内删除静止帧：
        - 使用 trans/euler 判断静止；
        - 当夹爪状态发生变化时，保留该帧以及之后 keep_after_grip 帧；
        - 其他静止帧（位置、欧拉角几乎不变）删除。
        """
        if len(df) <= 1:
            return df.reset_index(drop=True)

        if "trans" not in df.columns or "euler" not in df.columns:
            raise KeyError("DataFrame 中缺少 'trans' 或 'euler' 列。")

        trans = self.parse_vec_column(df["trans"])   # (N, 3)
        euler = self.parse_vec_column(df["euler"])   # (N, 3)

        if self.gripper_col in df.columns:
            g = df[self.gripper_col].to_numpy()
        else:
            g = np.zeros(len(df), dtype=int)

        N = len(df)
        keep_indices = []
        protect_until = -1  # 保护窗口结束 index（开区间）

        for i in range(N):
            if i == 0:
                keep_indices.append(i)
                continue

            # 夹爪状态是否变化
            gripper_changed = (g[i] != g[i - 1])

            if gripper_changed:
                keep_indices.append(i)
                protect_until = max(protect_until, i + 1 + self.keep_after_gripper_change)
                continue

            # 在保护窗口内：直接保留
            if i < protect_until:
                keep_indices.append(i)
                continue

            # 判断是否静止（trans/euler 几乎不变）
            pos_delta = np.linalg.norm(trans[i] - trans[i - 1])
            rot_delta = np.linalg.norm(euler[i] - euler[i - 1])

            if (pos_delta > self.pos_eps) or (rot_delta > self.rot_eps):
                keep_indices.append(i)
            else:
                # 静止帧且不在保护区内 -> 删除（不加入 keep_indices）
                pass

        return df.iloc[keep_indices].reset_index(drop=True)


    def load_labels(self, label_path: Path) -> pd.DataFrame:
        """
        加载 label.csv
        期望格式: start_frame, end_frame, description
        自动跳过无法转 int 的首行（表头）
        """
        df = pd.read_csv(label_path, header=None)
        # 判断第 1 行是否是数据，如果不是就跳过
        try:
            _ = int(str(df.iloc[0, 0]).strip())
        except ValueError:
            df = df.iloc[1:]

        df = df.iloc[:, :3]  # 保留前三列
        df.columns = ["start", "end", "desc"]
        df["start"] = df["start"].astype(int)
        df["end"] = df["end"].astype(int)
        df["desc"] = df["desc"].astype(str)
        return df


    def add_action_columns_from_pose(self, df: pd.DataFrame) -> pd.DataFrame:
        N = len(df)
        if N < 2:
            return pd.DataFrame(
                columns=list(df.columns) +
                ["action_x", "action_y", "action_z",
                "action_roll", "action_pitch", "action_yaw"]
            )

        trans = self.parse_vec_column(df["trans"])   # (N, 3)
        euler = self.parse_vec_column(df["euler"])   # (N, 3)

        action_x = []
        action_y = []
        action_z = []
        action_roll = []
        action_pitch = []
        action_yaw = []

        for i in range(N - 1):
            t1 = trans[i]
            t2 = trans[i + 1]
            rpy1 = euler[i]
            rpy2 = euler[i + 1]

            P1 = convert.poseeuler2rotmat(np.concatenate((t1, rpy1)))
            P2 = convert.poseeuler2rotmat(np.concatenate((t2, rpy2)))

            R1 = P1[:3, :3]
            R2 = P2[:3, :3]

            A = np.eye(4)
            A[:3, :3] = R2 @ R1.T
            A[:3, 3] = P2[:3, 3] - P1[:3, 3]

            Pa = convert.rotmat2poseeuler(A)   # array([x,y,z,roll,pitch,yaw])

            action_x.append(Pa[0])
            action_y.append(Pa[1])
            action_z.append(Pa[2])
            action_roll.append(Pa[3])
            action_pitch.append(Pa[4])
            action_yaw.append(Pa[5])

        df_out = df.iloc[:-1].copy().reset_index(drop=True)

        df_out["action_x"] = action_x
        df_out["action_y"] = action_y
        df_out["action_z"] = action_z
        df_out["action_roll"] = action_roll
        df_out["action_pitch"] = action_pitch
        df_out["action_yaw"] = action_yaw

        return df_out


    def downsample_and_add_action(
        self,
        df: pd.DataFrame,
        out_dir: Path,
        ep_name: str,
    ):
        """
        对单个 episode 的 DataFrame df 做 30->5Hz 下采样，并生成 6 个 offset 版本。
        Joint1~7 从角度转换为弧度。
        输出到 out_dir，文件名形如 ep_name_o0.csv。
        """
        out_dir.mkdir(parents=True, exist_ok=True)

        for o in self.offsets:
            ds_df = df.iloc[o::self.downsample_step].copy().reset_index(drop=True)
            if len(ds_df) < self.min_len_after_ds:
                print(f"[INFO] {ep_name} offset {o} 下采样后太短 ({len(ds_df)} 行)，跳过。")
                continue

            # === 新增：Joint1~Joint7 角度 -> 弧度 ===
            joint_cols = [f"Joint{i}" for i in range(1, 8)]
            missing = [c for c in joint_cols if c not in ds_df.columns]
            if missing:
                raise KeyError(f"{ep_name} offset {o} 缺少关节列: {missing}")

            ds_df[joint_cols] = np.deg2rad(ds_df[joint_cols])

            ds_with_action = self.add_action_columns_from_pose(ds_df)
            if ds_with_action.empty:
                print(f"[INFO] {ep_name} offset {o} 加 action 后为空，跳过。")
                continue

            # === 修改：不再 drop Joint1~7, trans, euler, task ===
            final_ds = ds_with_action.drop(
                [
                    'rot_angel',
                    'delta_x',
                    'delta_y',
                    'delta_z',
                    'rotvec',
                ],
                axis=1,
                errors="ignore",  # 更稳健，防止缺列报错
            )

            out_path = out_dir / f"{ep_name}_o{o}.csv"
            final_ds.to_csv(out_path, index=False)
            print(
                f"[OK] {ep_name} offset {o} -> {out_path.name}, "
                f"原帧数 {len(ds_df)}, 加 action 后 {len(final_ds)} 行"
            )


    def __call__(self, traj_dir: Path):
        """
        处理单个轨迹目录：
        1. 读取 ee_pose_30fps.csv 和 label.csv
        2. 按 label 切子轨迹
        3. 对每个子轨迹删除静止帧，保存 episodes/episode_i.csv
        4. 再对 episode_i 做 30->5Hz，生成 episodes_5hz/episode_i_o{offset}.csv
        """
        ee_path = traj_dir / "ee_pose_30fps.csv"
        label_path = traj_dir / "label.csv"

        if not ee_path.exists():
            print(f"[WARN] {ee_path} 不存在，跳过该轨迹。")
            return
        if not label_path.exists():
            print(f"[WARN] {label_path} 不存在，跳过该轨迹。")
            return

        print(f"\n[INFO] 处理轨迹: {traj_dir.name}")

        ee_df = pd.read_csv(ee_path)
        labels_df = self.load_labels(label_path)
        num_frames = len(ee_df)

        episodes_dir = traj_dir / self.episodes_dir_name
        episodes_dir.mkdir(exist_ok=True)

        episodes_5hz_dir = traj_dir / self.episodes_5hz_dir_name
        episodes_5hz_dir.mkdir(exist_ok=True)

        for idx, row in labels_df.iterrows():
            start = row["start"]
            end = row["end"]
            desc = row["desc"]

            start_idx = max(0, start)
            end_idx = min(num_frames - 1, end)
            if start_idx > end_idx:
                print(f"[WARN] label[{idx}] 区间无效: start={start}, end={end}")
                continue

            # 1) 先从原 30Hz 轨迹中切出子段
            sub_df = ee_df.iloc[start_idx:end_idx + 1].copy()

            # 2) 在子段内部删除静止帧
            sub_df = self.remove_static_frames(sub_df)

            if sub_df.empty:
                print(f"[WARN] 轨迹 {traj_dir.name} 的 episode_{idx} 删除静止帧后为空，跳过。")
                continue

            # 3) 添加 task 列
            sub_df["task"] = desc

            # 4) 保存 30Hz（删静止后）的 episode
            ep_name = f"episode_{idx}"
            ep_path = episodes_dir / f"{ep_name}.csv"
            sub_df.to_csv(ep_path, index=False)

            print(
                f"[OK] {traj_dir.name}: {ep_name}.csv  "
                f"(原区间 {start_idx}~{end_idx}, 删静止后 {len(sub_df)} 行, task='{desc}')"
            )

            # 5) 对该 episode 做 30->5Hz 下采样并生成 6 个 offset 版本
            self.downsample_and_add_action(sub_df, episodes_5hz_dir, ep_name)


def main():
    pipe = PostProcessPipeline()
    base = Path(pipe.base_dir)
    if not base.exists():
        print("[ERROR] BASE_DIR 不存在:", pipe.base_dir)
        return

    traj_dirs = sorted(d for d in base.iterdir() if d.is_dir())
    if not traj_dirs:
        print(f"[WARN] {pipe.base_dir} 下没有轨迹目录。")
        return

    print(f"[INFO] 在 {pipe.base_dir} 下发现 {len(traj_dirs)} 个轨迹目录：")
    for d in traj_dirs:
        print(" -", d.name)

    for traj_dir in traj_dirs:
        pipe(traj_dir)


if __name__ == "__main__":
    main()
