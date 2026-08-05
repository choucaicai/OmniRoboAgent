import numpy as np
from scipy.spatial.transform import Rotation as Rot
from urchin import URDF
from urchin.utils import matrix_to_xyz_rpy

def arm2camera(endmat_arm: np.ndarray, eyehand_mat_path: str) -> np.ndarray:
    r"""Transform the end effector pose from arm frame to camera frame.
    
    Args:
        - endmat_arm (np.ndarray) : The end effector pose in arm frame.
        - eyehand_mat_path (str) : The path to the eye-to-hand calibration matrix.

    Returns:
        - end_mat_camera (np.ndarray): The end effector pose in camera frame.
    """
    eyehand = np.load(eyehand_mat_path)
    eyehand = np.linalg.inv(eyehand)
    endmat_camera = eyehand @ endmat_arm 
    return endmat_camera

def camera2arm(endmat_camera: np.ndarray, eyehand_mat_path: str) -> np.ndarray:
    r"""Transform the end effector pose from camera frame to arm frame.
    
    Args:
        - endmat_camera (np.ndarray) : The end effector pose in camera frame.
        - eyehand_mat_path (str) : The path to the eye-to-hand calibration matrix.

    Returns:
        - end_mat_arm (np.ndarray) : The end effector pose in arm frame.
    """
    eyehand = np.load(eyehand_mat_path)
    end_mat_arm = eyehand @ endmat_camera
    return end_mat_arm

def rotmat2poseeuler(rotmat: np.ndarray) -> np.ndarray:
    r"""Convert the rotation matrix to position and euler angles.
    
    Args:
        - rotmat (np.ndarray) : The rotation matrix.

    Returns:
        - pose_euler (np.ndarray) : The position and euler angles(xyzrpy).
    """
    position = rotmat[:3, 3]   
    rotation_matrix = rotmat[:3, :3]  

    rot_m = Rot.from_matrix(rotation_matrix)

    euler_angles = rot_m.as_euler('xyz')
    pose_euler = np.concatenate((position, euler_angles))
    return pose_euler

def poseeuler2rotmat(pose_euler: np.ndarray) -> np.ndarray:
    r"""Convert the position and euler angles to rotation matrix.
    
    Args:
        - pose_euler (np.ndarray) : The position and euler angles(xyzrpy).

    Returns:
        - rotmat (np.ndarray) : The rotation matrix.
    """
    position = pose_euler[:3]
    euler_angles = pose_euler[3:]

    rot_m = Rot.from_euler('xyz', euler_angles)
    rotmat = np.eye(4)
    rotmat[:3, :3] = rot_m.as_matrix()
    rotmat[:3, 3] = position
    return rotmat

def rotmat2poserotvec(rotmat: np.ndarray) -> np.ndarray:
    r"""Convert the rotation matrix to position and rotation vector.
    
    Args:
        - rotmat (np.ndarray) : The rotation matrix.

    Returns:
        - pose_rotvec (np.ndarray) : [x,y,z,rotx,roty,rotz,angle].
    """
    position = rotmat[:3, 3]   
    rotation_matrix = rotmat[:3, :3]  

    rot_m = Rot.from_matrix(rotation_matrix)

    rotvec = rot_m.as_rotvec()

    angle = np.linalg.norm(rotvec)
    normed_rotvec = rotvec / angle

    pose_rotvec = np.concatenate((position, rotvec, [angle]))
    return pose_rotvec

def poserotvec2rotmat(pose_rotvec: np.ndarray) -> np.ndarray:
    r"""Convert the position and rotation vector to rotation matrix.
    
    Args:
        - pose_rotvec (np.ndarray) : [x,y,z,rotx,roty,rotz,angle].

    Returns:
        - rotmat (np.ndarray) : The rotation matrix.
    """
    position = pose_rotvec[:3]
    rotvec = pose_rotvec[3:6]
    angle = pose_rotvec[6]

    rotvec = rotvec * angle

    rot_m = Rot.from_rotvec(rotvec)
    rotmat = np.eye(4)
    rotmat[:3, :3] = rot_m.as_matrix()
    rotmat[:3, 3] = position
    return rotmat


def rotmat2posequat(rotmat: np.ndarray) -> np.ndarray:
    r"""Convert the rotation matrix to position and quaternion.
    
    Args:
        - rotmat (np.ndarray) : The 4x4 homogeneous rotation matrix.

    Returns:
        - pose_quat (np.ndarray) : [x, y, z, qx, qy, qz, qw].
    """
    # 位置
    position = rotmat[:3, 3]
    # 旋转部分 3x3
    rotation_matrix = rotmat[:3, :3]

    rot_m = Rot.from_matrix(rotation_matrix)

    # scipy 的 as_quat() 默认返回 [x, y, z, w]
    quat = rot_m.as_quat()

    # 拼成 [x, y, z, qx, qy, qz, qw]
    pose_quat = np.concatenate((position, quat))
    return pose_quat


def posequat2rotmat(pose_quat: np.ndarray) -> np.ndarray:
    r"""Convert the position and quaternion to rotation matrix.
    
    Args:
        - pose_quat (np.ndarray) : [x, y, z, qx, qy, qz, qw].

    Returns:
        - rotmat (np.ndarray) : The 4x4 homogeneous rotation matrix.
    """
    # 位置
    position = pose_quat[:3]
    # 四元数 [qx, qy, qz, qw]
    quat = pose_quat[3:]

    rot_m = Rot.from_quat(quat)

    rotmat = np.eye(4)
    rotmat[:3, :3] = rot_m.as_matrix()
    rotmat[:3, 3] = position
    return rotmat


class FkArm:
    def __init__(self, urdf_path: str):
        r"""
        Compute the forward kinematics for franka arm.

        Args:
        - urdf_path (str): Path to robot.urdf
        """
        self.robot_model = URDF.load(urdf_path, lazy_load_meshes=True)

    def __call__(self, jointsAng_rad: np.ndarray) -> np.ndarray:
        r"""Compute the end effector pose given the joint angles.
        
        Args:
        - jointsAng_rad (np.ndarray): The joint angles in rad.

        Returns:
        - end_mat (np.ndarray): The end effector pose.
        """
        fk_all = self.robot_model.link_fk(cfg=
            {
                "mk1000_fr3_joint1": jointsAng_rad[0],
                "mk1000_fr3_joint2": jointsAng_rad[1],
                "mk1000_fr3_joint3": jointsAng_rad[2],
                "mk1000_fr3_joint4": jointsAng_rad[3],
                "mk1000_fr3_joint5": jointsAng_rad[4],
                "mk1000_fr3_joint6": jointsAng_rad[5],
                "mk1000_fr3_joint7": jointsAng_rad[6],
            }
        )
        end_mat = fk_all[self.robot_model.link_map["mk1000_fr3_link8"]]
        return end_mat