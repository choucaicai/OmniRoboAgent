import os

import numpy as np
import argparse
from .robot_handeye_opt_calibrator import HandEyeOptCalibrator
from pathlib import Path


def evaluate_handeye_calibration(test_data_path, intrinsic_path, calibration_result_path, num_images):
    """
    监测标定结果在新采集数据上的重投影误差(请确保标定板固定位置不动！)

    Args:
        test_data_path (str): 新采集的数据路径
        intrinsic_path (str): 相机内参路径
        calibration_result_path (str): 原始标定结果路径
        num_images (int): 采集的图片数量
    """
    calibrator = HandEyeOptCalibrator(XX=11, YY=8, L=0.02)
    extrinsic_calib_image_idxs = np.arange(0, num_images)
    excluded_image_idxs = []
    extrinsic_calib_image_idxs = np.delete(extrinsic_calib_image_idxs, excluded_image_idxs)

    calibrator.load_camera_intrinsics(intrinsic_path)
    calibrator.load_calibration_images(test_data_path, extrinsic_calib_image_idxs)
    calibrator.load_calibration_ee_xyzrpy(test_data_path, extrinsic_calib_image_idxs)
    calibrator.calibrate()

    # 加载之前计算得到的手眼标定结果
    calibrator.init_cam2base_4x4 = np.load(Path(calibration_result_path)/"cam2base_4x4.npy")
    calibrator.init_target2ee_4x4 = np.load(Path(calibration_result_path)/"target2ee_4x4.npy")
    calibrator.cam2base_4x4 = calibrator.init_cam2base_4x4
    calibrator.target2ee_4x4 = calibrator.init_target2ee_4x4

    errors = calibrator.opt_handeye_calib_reproject_error(vis=True)

    errors = np.array(errors)
    mean_error = errors.mean()

    return mean_error, errors


# {os.environ['WORKDIR']}
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate HandEye Calibration")
    parser.add_argument('--test_data_path', type=str,
                        default=f"{os.environ['WORKDIR']}/data/calib/output_04-15_3_right")
    parser.add_argument('--intrinsic_path', type=str,
                        default=f"{os.environ['WORKDIR']}/data/intrinsic")
    parser.add_argument('--calibration_result_path', type=str,
                        default=f"{os.environ['WORKDIR']}/data/calib/output_04-15_3_right/results")
    parser.add_argument('--num_images', type=int, default=300)

    args = parser.parse_args()

    mean_error, errors = evaluate_handeye_calibration(args.test_data_path, args.intrinsic_path,
                                                      args.calibration_result_path, args.num_images)

    print(f"Mean Reprojection Error: {mean_error}")