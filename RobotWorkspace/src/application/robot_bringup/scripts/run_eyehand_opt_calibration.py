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
                        default=f"{os.environ['WORKDIR']}/data/calib/eyehand/prepare_data_11_28_344422300343")
    parser.add_argument('--output_path', type=str,
                        default=f"{os.environ['WORKDIR']}/data/calib/eyehand/results_11_28_344422300343")
    parser.add_argument('--intrinsic_path', type=str, default=f"{os.environ['WORKDIR']}/data/calib/intrinsic/results_344422300343")
    parser.add_argument('--num_images', type=int, default=51)

    args = parser.parse_args()

    os.makedirs(args.output_path, exist_ok=True)

    calibrator = HandEyeOptCalibrator(XX=11, YY=8, L=0.02)

    extrinsic_calib_image_idxs = np.arange(0, args.num_images)
    excluded_image_idxs = [11,12,13,14,15,16,17,18,21,22,23,24,30,31,35,38,39,43,44,45,46]
    extrinsic_calib_image_idxs = np.delete(extrinsic_calib_image_idxs, excluded_image_idxs)

    calibrator.load_camera_intrinsics(args.intrinsic_path)
    calibrator.load_calibration_images(args.calib_data_path, extrinsic_calib_image_idxs)
    calibrator.load_calibration_ee_xyzrpy(args.calib_data_path, extrinsic_calib_image_idxs)
    calibrator.calibrate()
    # ensure the intrinsics if correct
    cam_calib_errors = calibrator.cam_calib_reproject_error(vis=False)

    # errors = calibrator.handeye_calib_reproject_error(vis=True)
    # # find errors > 1
    # extrinsic_calib_image_idxs = extrinsic_calib_image_idxs[errors<1]
    calibrator.load_calibration_images(args.calib_data_path, extrinsic_calib_image_idxs)
    calibrator.load_calibration_ee_xyzrpy(args.calib_data_path, extrinsic_calib_image_idxs)
    calibrator.calibrate()
    cam_calib_errors = calibrator.handeye_calib_reproject_error(vis=False)
    argmin_error_idx = np.argmin(cam_calib_errors)
    print(f'argmin_error_idx: {argmin_error_idx}')

    # calibrator.load_initial_eyehand_calibration_result('./output/calib_data/handeye')
    calibrator.set_initial_imageid(argmin_error_idx)
    calibrator.optmize()
    errors = calibrator.opt_handeye_calib_reproject_error(vis=True)
    calibrator.save(save_dir=args.output_path)

    # Find index of error > 0.3
    errors = np.array(errors)
    idx = np.where(errors > 0.3)[0]
    print(f"error > 0.3: {idx.tolist()}")

    mean_err = errors.mean()
    print(np.array(errors).mean())
    # save reproject error to file
    with open(os.path.join(args.output_path, "reprojection_error.txt"), "w") as f:
        f.write(str(mean_err))
        f.close()