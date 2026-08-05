"""Given a list of images of checkboards and it's corresponding 3D corner points, returns the intrinsic and extrinsic 
paramaters."""

import cv2
import imutils.paths
import numpy as np
from typing import List, Tuple, Optional, Tuple, Sequence
import imutils
from numpy.typing import ArrayLike
import os
from .calibration_utils import get_objpoints, _find_chessboard_corners


def calibrate_camera(image_path_list: List[str], corners_3d_list: List[List[float]],
                     XX: int, YY: int,
                     find_chessboard_corners_flags: int = cv2.CALIB_CB_ADAPTIVE_THRESH+cv2.CALIB_CB_FAST_CHECK
                     + cv2.CALIB_CB_NORMALIZE_IMAGE,
                     corner_refine_criteria=(cv2.TERM_CRITERIA_MAX_ITER | cv2.TERM_CRITERIA_EPS, 30, 0.001),
                     corner_refine_winsize=(11, 11),
                     verbose=True) \
        -> Tuple[bool, np.array, np.array, np.array, np.array]:
    imgpoints = []
    objpoints = []
    image_size = None
    for i in range(0, len(image_path_list)):
        image_path = image_path_list[i]
        img = cv2.imread(image_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if image_size is None:
            image_size = gray.shape[::-1]
        find_corners_ret, corners = _find_chessboard_corners(
            gray, XX, YY, find_chessboard_corners_flags, corner_refine_criteria, corner_refine_winsize)

        # corners: order in row by row, and left to right in each row
        if find_corners_ret:
            imgpoints.append(corners)
            objp = corners_3d_list[i]
            objpoints.append(objp)
        else:
            print(f"Can not find checkerboard corners of {image_path}, Skip.")

    ret, mtx, dist, rvecs, tvecs = cv2.calibrateCamera(objpoints, imgpoints, image_size, None, None)

    mean_error = 0
    for i in range(len(objpoints)):
        imgpoints2, _ = cv2.projectPoints(objpoints[i], rvecs[i], tvecs[i], mtx, dist)
        error = cv2.norm(imgpoints[i], imgpoints2, cv2.NORM_L2)/len(imgpoints2)
        if verbose:
            print(f"{i} error: {error}")
        mean_error += error
    if verbose:
        print("total error: {}".format(mean_error/len(objpoints)))
    return ret, mtx, dist, rvecs, tvecs


def _calibrate_intrinsic_camera_parameters(
    image_paths: Sequence[str],
    XX: int,
    YY: int,
    L: float,
    verbose: bool = True
) -> Tuple[ArrayLike, ArrayLike]:
    """Calibrate the intrinsic parameters of a camera using a set of images of a checkboard pattern.
    Args:
        CAM_CALIB_DATA_DIR (str): The directory containing the images of the checkboard pattern.
        XX (int): The number of inner corners along the X axis of the checkboard pattern.
        YY (int): The number of inner corners along the Y axis of the checkboard pattern.
        L (float): The length of each square side on the checkboard in real-world units (meter).
        image_idxs (Optional[Sequence[int]], optional): The image indexs involves in computation. Defaults to None.
        verbose (bool, optional): Printing verbose information. Defaults to True.

    Returns:
        Tuple[ArrayLike, ArrayLike]: The intrinsic camera matrix and the distortion coefficients.
    """

    objpoints = get_objpoints(len(image_paths), XX, YY, L)

    """Performing camera calibration by passing the value of known 3D point(objpoints) and corresponding pixel coordinates 
    of the detected corners(imgpoints)"""
    # 标定,得到图案在相机坐标系下的位姿
    # ret, mtx, dist, rvecs, tvecs = calibrate_camera(image_paths, objpoints, XX, YY)
    ret, mtx, dist, rvecs_board2cam, tvecs_board2cam = calibrate_camera(image_paths, objpoints, XX, YY, verbose=verbose)
    return mtx, dist


def calibrate_intrinsic_camera_parameters(
    CAM_CALIB_DATA_DIR: str,
    XX: int,
    YY: int,
    L: float,
    image_idxs: Optional[Sequence[int]] = None,
    verbose: bool = True
) -> Tuple[ArrayLike, ArrayLike]:
    """Calibrate the intrinsic parameters of a camera using a set of images of a checkboard pattern.
    Args:
        CAM_CALIB_DATA_DIR (str): The directory containing the images of the checkboard pattern.
        XX (int): The number of inner corners along the X axis of the checkboard pattern.
        YY (int): The number of inner corners along the Y axis of the checkboard pattern.
        L (float): The length of each square side on the checkboard in real-world units (meter).
        image_idxs (Optional[Sequence[int]], optional): The image indexs involves in computation. Defaults to None.
        verbose (bool, optional): Printing verbose information. Defaults to True.

    Returns:
        Tuple[ArrayLike, ArrayLike]: The intrinsic camera matrix and the distortion coefficients.
    """

    image_paths = list(imutils.paths.list_images(CAM_CALIB_DATA_DIR))
    image_paths.sort(key=lambda x: int(os.path.split(x)[-1].split('.')[0]))
    calib_image_paths = image_paths if image_idxs is None else np.array(image_paths)[image_idxs].flatten()

    return _calibrate_intrinsic_camera_parameters(calib_image_paths, XX, YY, L, verbose=verbose)


def calibrate_extrinsic_camera_parameters(CAM_CALIB_DATA_DIR, XX, YY, L, image_idxs=None, verbose=True):
    """Calibrate the extrinsic parameters (the position of checkerboard in camera coordiate) of a camera using a set of 
    images of a checkboard pattern.

    Args:
        CAM_CALIB_DATA_DIR (_type_): The directory containing the images of the checkboard pattern.s
        XX (_type_): The number of inner corners along the X axis of the checkboard pattern.
        YY (_type_): The number of inner corners along the Y axis of the checkboard pattern.
        L (_type_): The length of each square side on the checkboard in real-world units (meter).
        image_idxs (_type_, optional): The image indexs involves in computations. Defaults to None.
        verbose (bool, optional): Printing verbose information. Defaults to True.

    Returns:
        _type_: _description_
    """
    image_paths = list(imutils.paths.list_images(CAM_CALIB_DATA_DIR))
    image_paths.sort(key=lambda x: int(os.path.split(x)[-1].split('.')[0]))
    calib_image_paths = image_paths if image_idxs is None else np.array(image_paths)[image_idxs].flatten()

    rvecs_board2cam, tvecs_board2cam = _calibrate_extrinsic_camera_parameters(
        calib_image_paths, XX, YY, L, verbose=verbose)
    return rvecs_board2cam, tvecs_board2cam


def _calibrate_extrinsic_camera_parameters(extrinsic_calib_image_paths, XX, YY, L, verbose=True):
    objpoints = get_objpoints(len(extrinsic_calib_image_paths), XX, YY, L)

    # Step 2: Do camera calibration to get H_cam2board
    ret, _, _, rvecs_board2cam, tvecs_board2cam = calibrate_camera(
        extrinsic_calib_image_paths, objpoints, XX, YY, verbose)
    return rvecs_board2cam, tvecs_board2cam