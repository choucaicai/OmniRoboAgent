import os

from robot_cam_calibration.robot_handeye_opt_calibrator import HandEyeOptCalibrator
import numpy as np
from robot_cam_calibration.camera_intrinsic_params_calibrator import CameraIntrinsicParamsCalibrator
from pathlib import Path

# # The configurations for camera calibration
# INTRINSIC_CALIB_DATA_DIR = "./data/demo_data/robot_cam_calibration_data_0906/handeye"
# # 角点的个数以及棋盘格间距
# XX = 11 #标定板的中长度对应的角点的个数
# YY = 8  #标定板的中宽度对应的角点的个数
# L = 0.02 #标定板一格的长度  单位为米
# calibrator = CameraIntrinsicParamsCalibrator(XX=XX, YY=YY, L=L)
# calibrator.load_intrinsic_calib_images(INTRINSIC_CALIB_DATA_DIR)
# calibrator.calibrate(verbose=True)
# calibrator.save('./output/calib_data/robot_cam_calibration_data_0906/intrinsic')


import argparse
# TODO: use argparser here, to specfic input and output dir as cli parameters

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Eye-hand calibration")

    parser.add_argument('--calib_data_path', type=str,
                        default=f"{os.environ['WORKDIR']}/data/calib/intrinsic/prepare_data_344422300343")
    parser.add_argument('--output_path', type=str,
                        default=f"{os.environ['WORKDIR']}/data/calib/intrinsic/results_344422300343")
    parser.add_argument('--num_images', type=int, default=26)

    args = parser.parse_args()

    os.makedirs(args.output_path, exist_ok=True)

    calibrator = CameraIntrinsicParamsCalibrator(XX=11, YY=8, L=0.02)

    intrinsic_calib_image_idxs = np.arange(0, args.num_images)
    excluded_image_idxs = []
    intrinsic_calib_image_idxs = np.delete(intrinsic_calib_image_idxs, excluded_image_idxs)

    calibrator.load(args.calib_data_path, intrinsic_calib_image_idxs)
    calibrator.calibrate()
   
    calibrator.save(save_dir=args.output_path)