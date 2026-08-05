from .camera_intrinsic_params_calibrator import CameraIntrinsicParamsCalibrator
import imutils
import os
import numpy as np
from .camera_calibrator import _calibrate_extrinsic_camera_parameters
from .utils import xyz_rpy_to_matrix, inverse_transform_matrix
import cv2
from .calibration_utils import calculate_reproject_error_fast, calculate_single_image_reprojection_error


class EyetoHandCalibrator:
    """Calibrate the camera to robot transformation using the eye-to-hand method."""

    def __init__(self, XX, YY, L):
        self.XX = XX
        self.YY = YY
        self.L = L

        self.ntx = None
        self.dist = None

        self.extrinsic_calib_image_paths = None

        self.base2ee_Ms = None
        self.ee2base_Ms = None

        self.target2ee_Ms = []

    def load_camera_intrinsics(self, save_dir):
        mtx, dist = CameraIntrinsicParamsCalibrator.reload(save_dir)
        self.mtx = mtx
        self.dist = dist

    def load_calibration_images(self, HANDEYE_CALIB_DATA_DIR, selected_idxs=None):
        extrinsic_calib_image_paths = list(imutils.paths.list_images(HANDEYE_CALIB_DATA_DIR))
        extrinsic_calib_image_paths.sort(key=lambda x: int(os.path.split(x)[-1].split('.')[0]))

        self.extrinsic_calib_image_paths = extrinsic_calib_image_paths if selected_idxs is None else np.array(
            extrinsic_calib_image_paths)[selected_idxs].flatten()

    def load_calibration_ee_xyzrpy(self, HANDEYE_CALIB_DATA_DIR, selected_idxs=None):
        """load the list of end2base matrix from xyzrpy.npy file got from robot API"""
        xyzrpy_list = []
        end2base_Ms = []
        from glob import glob
        end_xyzrpy_paths = glob(f"{HANDEYE_CALIB_DATA_DIR}/*_xyzrpy.npy")
        end_xyzrpy_paths = sorted(end_xyzrpy_paths, key=lambda x: int(os.path.split(x)[-1].split('_')[0]))
        selected_end_xyzrpy_paths = end_xyzrpy_paths if selected_idxs is None else np.array(end_xyzrpy_paths)[
            selected_idxs].flatten()

        for path in selected_end_xyzrpy_paths:
            xyzrpy = np.load(path)
            xyzrpy_list.append(xyzrpy)
            end2base_M = xyz_rpy_to_matrix(xyzrpy)
            end2base_Ms.append(end2base_M)
        base2end_Ms = np.array([inverse_transform_matrix(x) for x in end2base_Ms])
        self.base2ee_Ms = np.array(base2end_Ms)
        self.ee2base_Ms = np.array(end2base_Ms)

    def calibrate(self, verbose=True):
        if self.mtx is None or self.dist is None:
            raise ValueError("Camera intrinsic parameters have not been loaded yet.")

        if self.extrinsic_calib_image_paths is None:
            raise ValueError("Extrinsic calibration images have not been loaded yet.")

        rvecs_board2cam, tvecs_board2cam = _calibrate_extrinsic_camera_parameters(self.extrinsic_calib_image_paths,
                                                                                  self.XX, self.YY, self.L, verbose)
        self.rvecs_board2cam = rvecs_board2cam
        self.tvecs_board2cam = tvecs_board2cam

        # using opencv calibrateHandEye
        """
        void
        cv::calibrateHandEye(InputArrayOfArrays 	R_gripper2base,	// <=> R_base2end
                            InputArrayOfArrays 	t_gripper2base,	// <=> T_base2end
                            InputArrayOfArrays 	R_target2cam,	// <=> R_board2cam
                            InputArrayOfArrays 	t_target2cam,	// <=> T_board2cam
                            OutputArray 	        R_cam2gripper,	// <=> R_cam2base
                            OutputArray 	        t_cam2gripper,	// <=> T_cam2base
                            HandEyeCalibrationMethod method = CALIB_HAND_EYE_TSAI)	
        """
        # base2ee_Ms = load_end2base(EXTRINSIC_CALIB_DATA_DIR)

        ee2base_Ms = np.array([inverse_transform_matrix(x) for x in self.base2ee_Ms])
        base2gripper_Rs = self.base2ee_Ms[:, :3, :3]
        base2gripper_ts = self.base2ee_Ms[:, :3, 3]
        target2cam_Rs = rvecs_board2cam
        target2cam_ts = tvecs_board2cam

        cam2base_R, cam2base_t = cv2.calibrateHandEye(
            base2gripper_Rs, base2gripper_ts, rvecs_board2cam, tvecs_board2cam, cv2.CALIB_HAND_EYE_HORAUD)
        self.cam2base_R = cam2base_R
        self.cam2base_t = cam2base_t
        self.cam2base_4x4 = np.eye(4)
        self.cam2base_4x4[:3, :3] = cam2base_R
        self.cam2base_4x4[:3, 3] = cam2base_t[:, 0]
        pass

    def cam_calib_reproject_error(self, vis=False):
        errors = []
        for i in range(0, len(self.extrinsic_calib_image_paths)):
            error = calculate_single_image_reprojection_error(
                self.extrinsic_calib_image_paths[i],
                self.rvecs_board2cam[i], self.tvecs_board2cam[i], self.mtx, self.dist, self.XX, self.YY, self.L, vis=vis)
            errors.append(error)
        return np.array(errors)

    def handeye_calib_reproject_error(self, vis=False):

        base2cam_4x4 = np.linalg.inv(self.cam2base_4x4)

        errors = []
        for i in range(0, len(self.base2ee_Ms)):
            target2cam_4x4 = xyz_rpy_to_matrix(self.tvecs_board2cam[i].flatten(
            ).tolist() + self.rvecs_board2cam[i].flatten().tolist())
            target2ee_4x4 = self.base2ee_Ms[i] @ self.cam2base_4x4 @ target2cam_4x4
            self.target2ee_Ms.append(target2ee_4x4)
            eyehand_target2cam_4x4 = base2cam_4x4 @ self.ee2base_Ms[i] @ target2ee_4x4
            error = calculate_single_image_reprojection_error(
                self.extrinsic_calib_image_paths[i],
                eyehand_target2cam_4x4[:3, :3], eyehand_target2cam_4x4[:3, 3], self.mtx, self.dist, self.XX, self.YY, self.L, vis=vis)
            errors.append(error)
        return np.array(errors)

    def save(self, save_dir):
        if not os.path.isdir(save_dir):
            os.makedirs(save_dir)
        np.save(f'{save_dir}/cam2base_R.npy', self.cam2base_R)
        np.save(f'{save_dir}/cam2base_t.npy', self.cam2base_t)
        np.save(f'{save_dir}/cam2base_4x4.npy', self.cam2base_4x4)

        np.save(f'{save_dir}/ee2base_Ms.npy', self.ee2base_Ms)
        np.save(f'{save_dir}/rvecs_board2cam.npy', self.rvecs_board2cam)
        np.save(f'{save_dir}/tvecs_board2cam.npy', self.tvecs_board2cam)