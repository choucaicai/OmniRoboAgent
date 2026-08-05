import pandas as pd
import numpy as np
import os
import cv2
import convert
from PIL import Image
from tqdm import tqdm

from concurrent.futures import ThreadPoolExecutor, as_completed


class PreProcessPipeline:
    def __init__(self,
        urdf_path: str = "/remote-home/share/liaomz/RobotWorkspace/src/robot/mr1000_description/urdf/robot_arm_only.urdf",
        eyehand_path: str = "/remote-home/share/liaomz/cam2base_4x4.npy",
    ):
        self.urdf_path = urdf_path
        self.eyehand_path = eyehand_path

        self.forwardk = convert.FkArm(self.urdf_path)

    def sync(self, DATA_PATH: str):
        """
        DATA_PATH: 解析后数据所在目录, 例如 ".../parsed/"
        需要存在:
        - frame.csv        (Time, Image)
        - wrist_frame.csv  (Time, Wrist_Image)
        - joint_states.csv (Time, Joint1~7)
        - gripper.csv      (Time, Gripper_State 或 Gripper)
        """
        camera = pd.read_csv(os.path.join(DATA_PATH, "frame.csv"))  # (30Hz) Time, Image
        wrist = pd.read_csv(os.path.join(DATA_PATH, "wrist_frame.csv"))  # (60Hz) Time, Wrist_Image
        joint = pd.read_csv(os.path.join(DATA_PATH, "joint_states.csv"))  # (200Hz) Time, Joint1~Joint7
        # 夹爪状态（状态改变时记录）
        gripper = pd.read_csv(os.path.join(DATA_PATH, "gripper_state.csv"))  # Time, Gripper_State or Gripper
        if "Gripper_State" in gripper.columns and "Gripper" not in gripper.columns:
            gripper = gripper.rename(columns={"Gripper_State": "Gripper"})

        # 保证 Time 是 int64，并按时间排序
        for df in (camera, wrist, joint, gripper):
            df["Time"] = df["Time"].astype("int64")
            df.sort_values("Time", inplace=True)

        # 基准时间轴：主相机
        basetime = camera["Time"]
        base_df = camera[["Time", "Image"]].copy()

        wrist_synced = pd.merge_asof(basetime.to_frame(), wrist, on="Time", direction="nearest")
        wrist_synced = wrist_synced[["Time", "Wrist_Image"]]

        joint_synced = pd.merge_asof(basetime.to_frame(), joint, on="Time", direction="nearest")
        # joint_synced 包含 Time, Joint1~Joint7

        cam_df = basetime.to_frame().rename(columns={"Time": "CamTime"})

        # 将 gripper 的时间叫做 GripperTime，避免和 CamTime 混淆
        gr = gripper[["Time", "Gripper"]].rename(columns={"Time": "GripperTime"})
        gr.sort_values("GripperTime", inplace=True)
        cam_df.sort_values("CamTime", inplace=True)

        # 对齐：每条 gripper 记录找到最近的一帧主相机时间戳 CamTime
        snapped = pd.merge_asof(
            gr,
            cam_df,
            left_on="GripperTime",
            right_on="CamTime",
            direction="nearest",
        )
        # snapped: GripperTime, Gripper, CamTime(最近帧)

        events_on_frames = snapped.set_index("CamTime")["Gripper"]

        # 在主相机时间轴上做一个完整的 Gripper 序列
        gripper_on_cam = pd.DataFrame({"Time": basetime.copy()})
        gripper_on_cam["Gripper"] = pd.NA
        gripper_on_cam.set_index("Time", inplace=True)

        # 把事件写入对应的帧
        # 注意：events_on_frames 的 index 是 CamTime，正好是主相机的 Time
        gripper_on_cam.loc[events_on_frames.index, "Gripper"] = events_on_frames.values

        # 向后填充；前面没有任何记录的地方用初始状态 1(张开)
        gripper_on_cam["Gripper"] = (
            gripper_on_cam["Gripper"]
            .ffill()
            .fillna(1)         # 初始状态为张开
            .astype("int64")
        )
        gripper_synced = gripper_on_cam.reset_index()  # 列: Time, Gripper

        final = (
            base_df
            .merge(wrist_synced, on="Time", how="left")
            .merge(joint_synced, on="Time", how="left")
            .merge(gripper_synced, on="Time", how="left")
        )

        joint_cols = [c for c in final.columns if c.startswith("Joint")]
        final = final[["Time", "Image", "Wrist_Image"] + joint_cols + ["Gripper"]]

        out_path = os.path.join(DATA_PATH, "sync_30fps.csv")
        final.to_csv(out_path, index=False)

    def get_cam_ee_pose(self, row):
        angles = [row[f'Joint{i}'] for i in range(1,8)]
        joints_rad = np.deg2rad(np.array(angles))
        end_mat = self.forwardk(joints_rad)
        end_mat = convert.arm2camera(end_mat, self.eyehand_path)

        pose_euler = convert.rotmat2poseeuler(end_mat)
        pose_rotvec = convert.rotmat2poserotvec(end_mat)

        position = pose_rotvec[:3]
        euler_angles = pose_euler[3:]

        pose = np.concatenate((position, euler_angles, pose_rotvec[3:]))

        return pose.tolist()

    def apply_fk(self, DATA_PATH: str):
        joint_df = pd.read_csv(DATA_PATH+"sync_30fps.csv")
        new_df = joint_df.apply(self.get_cam_ee_pose, axis=1, result_type="expand")
        new_df.columns=['x','y','z','rx','ry','rz','rot_x','rot_y','rot_z','rot_angel']
        df = pd.concat([joint_df,new_df], axis=1)

        df['delta_x'] = df['x'].diff()
        df['delta_y'] = df['y'].diff()
        df['delta_z'] = df['z'].diff()
        df['trans'] = df.apply(lambda row: [row['x'], row['y'], row['z']], axis=1)
        df['euler'] = df.apply(lambda row: [row['rx'], row['ry'], row['rz']], axis=1)
        df['rotvec'] = df.apply(lambda row: [row['rot_x'], row['rot_y'], row['rot_z']], axis=1)
        df = df.drop(['x','y','z','rx','ry','rz','rot_x','rot_y','rot_z'], axis=1)

        df.to_csv(DATA_PATH+"ee_pose_30fps.csv", index=False) # 30Hz

    def load_images_to_numpy(self, folder_path):
        # 获取文件夹中的所有文件名，并按名称排序
        image_files = sorted(
            [f for f in os.listdir(folder_path) if f.endswith('.jpg')],
            key=lambda x: int(os.path.splitext(x)[0])
        )

        # 初始化一个列表，用于存储图片的numpy数组
        images_array = []

        # 遍历每一个文件并将其读取为NumPy数组
        for file_name in tqdm(image_files):
            file_path = os.path.join(folder_path, file_name)
            # 打开图像并转换为RGB模式（如果有需要）
            img = Image.open(file_path).convert('RGB')
            # 将图像转换为numpy数组
            img_array = np.array(img)
            # 添加到图片数组列表
            images_array.append(img_array)

        # 将列表转换为NumPy数组（如果所有图片大小相同）
        images_array = np.array(images_array)

        return images_array

    def save_video_k_fps(self, images, datapath, fps=1, video_name="main"):
        path = datapath + f'video_{video_name}.mp4'
        # save video for debugging
        height, width, _ = images[0].shape
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(path, fourcc, fps, (width, height))

        for image in tqdm(images):
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            out.write(image_rgb)
        out.release()
        return path

    def put_text_list(self, image, text_list):
        height = image.shape[0]
        new_text_list = []
        for text in text_list:
            if '\n' in text:
                new_text_list.extend(text.split('\n'))
            else:
                new_text_list.append(text)
        if height > 500:
            h = 30
            for j, text in enumerate(new_text_list):
                image = cv2.putText(img=image, text=text, org=(10, height - h - j * h), fontFace=cv2.FONT_HERSHEY_SIMPLEX, fontScale=3, color=(255, 255, 255), thickness=2)
        else:
            h = 15
            for j, text in enumerate(new_text_list):
                image = cv2.putText(img=image, text=text, org=(10, height - h - j * h), fontFace=cv2.FONT_HERSHEY_SIMPLEX, fontScale=0.3, color=(50, 50, 50), thickness=1)
        return image
    
    def __call__(self, DATA_PATH):
        print("============ Start to process ============")
        self.sync(DATA_PATH)
        print("============ Sync Done! ============")
        self.apply_fk(DATA_PATH)
        print("============ Apply_fk Done !============")
        print(f"============ Now {DATA_PATH} ============")
        images_array = self.load_images_to_numpy(DATA_PATH+"image")
        for i in range(images_array.shape[0]):
            self.put_text_list(images_array[i], [str(i)])
            
        self.save_video_k_fps(images_array, datapath=DATA_PATH, fps=30, video_name="main")
        print("============ Main Camera Video Done ! ============")
        images_array = self.load_images_to_numpy(DATA_PATH+"wrist_image")
        for i in range(images_array.shape[0]):
            self.put_text_list(images_array[i], [str(i)])
            
        self.save_video_k_fps(images_array, datapath=DATA_PATH, fps=30, video_name="wrist")
        print("============ Wrist Camera Video Done ! ============")

        file_path = DATA_PATH+'label.csv'
        print(file_path)
        if not os.path.exists(file_path):
            with open(file_path, 'w') as file:
                pass 



def process_data_dir(data_dir):
    pipe = PreProcessPipeline()
    cur_data_path = os.path.abspath(data_dir) + '/'
    # if not os.path.exists(cur_data_path + 'label.csv'):
    #     print(cur_data_path + 'label.csv'+" do not exist.")
    pipe(cur_data_path)

if __name__ == "__main__":
    max_workers = 8  # Set the number of threads (adjust based on your system's capabilities)
    data_dirs = []
    
    for root, dirs, files in os.walk("/remote-home/share/teledata/raw/2025-12-26"):
        for dir_name in dirs:
            data_dirs.append(os.path.join(root, dir_name))
            # print(dir_name)
            # process_data_dir(data_dirs[0])
        break

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(process_data_dir, data_dir) for data_dir in data_dirs]

        for future in as_completed(futures):
            future.result() 