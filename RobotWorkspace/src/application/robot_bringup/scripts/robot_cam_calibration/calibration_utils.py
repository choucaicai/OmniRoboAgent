import numpy as np
from typing import Sequence, Tuple
from numpy.typing import ArrayLike
import cv2
import os


def get_objpoints(num_images: int, XX: int, YY: int, L: float) -> Sequence[ArrayLike]:
    """Generate a list of 3D object points for each image of a checkboard pattern used in camera calibration.

    Args:
        num_images (int): The number of images used for calibration.
        XX (int): The number of inner corners along the X axis of the checkboard pattern.
        YY (int): The number of inner corners along the Y axis of the checkboard pattern.
        L (float): The length of each square side on the checkboard in real-world units (meter).

    Returns:
        Sequence[ArrayLike]: A list containing the 3D points for each image's checkboard pattern.
    """

    # Creating a list to store the 3D points for each checkboard image
    objpoints = []
    for i in range(0, num_images):
        # Initialize a zero array to store the 3D points for the checkboard corners
        objp = np.zeros((XX * YY, 3), np.float32)
        # Set the x and y coordinates for each corner on the checkboard (z-coordinates are zero)
        objp[:, :2] = np.mgrid[0:XX, 0:YY].T.reshape(-1, 2)
        # Scale the object points by the size of each square (L)
        objp *= L
        # Append the 3D points for the current checkboard to the list
        objpoints.append(objp)

    return objpoints


def calculate_reproject_error_fast(imgpoints, objpoints,
                                   rvecs_target2cam, tvecs_target2cam, mtx, dist,
                                   image_paths=None, XX=None, YY=None, vis=False, save_fig=False, save_dir='output',
                                   verbose=True):
    """rvecs, tvecs represent transformation of checkerboard to camera
    To avoid re-calculate the 3D points for each image, we pass the objpoints as input
    To avoid re-calculate the corners for each image, we pass the imgpoints as input
    """
    num_images = len(imgpoints)

    mean_error = 0
    for image_idx in range(0, num_images):
        imgpoints2, _ = cv2.projectPoints(
            objpoints[image_idx], rvecs_target2cam[image_idx], tvecs_target2cam[image_idx], mtx, dist)
        error = cv2.norm(imgpoints[image_idx], imgpoints2, cv2.NORM_L2)/len(imgpoints2)
        if verbose:
            print(f"{image_idx} error: {error}")
        mean_error += error
        if vis or save_fig:
            imagei = cv2.imread(image_paths[image_idx])
            img_draw = cv2.drawChessboardCorners(imagei, (XX, YY), imgpoints2, True)
            if save_fig:
                if not os.path.isdir(save_dir):
                    os.makedirs(save_dir)
                cv2.imwrite(f'{save_dir}/{image_idx}_reproject_corners.png', img_draw)
            if vis:
                cv2.imshow('img_draw', img_draw)
                cv2.waitKey(0)
    if verbose:
        print("total error: {}".format(mean_error/len(objpoints)))
    return mean_error/len(objpoints)


def calculate_single_image_reprojection_error(image_path, rvec_board2cam, tvec_board2cam, mtx, dist, XX, YY, L, vis=False, save_fig=False, save_dir='output', verbose=True):
    imgpoints = get_chessboard_corners([image_path], XX, YY)
    objpoints = get_objpoints(1, XX, YY, L)

    reprojected_imgpoints, _ = cv2.projectPoints(objpoints[0], rvec_board2cam, tvec_board2cam, mtx, dist)
    error = cv2.norm(imgpoints[0], reprojected_imgpoints, cv2.NORM_L2)/len(reprojected_imgpoints)
    if verbose:
        print(f"{image_path} error: {error}")
    if vis or save_fig:
        img = cv2.imread(image_path)
        img_draw = cv2.drawChessboardCorners(img, (XX, YY), reprojected_imgpoints, True)
        if save_fig:
            if not os.path.isdir(save_dir):
                os.makedirs(save_dir)
            cv2.imwrite(f'{save_dir}/{image_path}_reproject_corners.png', img_draw)
        if vis:
            cv2.imshow('img_draw', img_draw)
            cv2.waitKey(0)
    return error


def _find_chessboard_corners(gray: np.array, XX: int, YY: int, flags: int, criteria: Tuple[int, int, float], winsize: Tuple[int, int]):
    ret, corners = cv2.findChessboardCorners(gray, (XX, YY), cv2.CALIB_CB_ADAPTIVE_THRESH+cv2.CALIB_CB_FAST_CHECK
                                             + cv2.CALIB_CB_NORMALIZE_IMAGE)
    if ret:
        # refining pixel coordinates for given 2d points
        corners2 = cv2.cornerSubPix(gray, corners, winsize, (-1, -1), criteria)
        return True, corners2
    else:
        return False, []


def get_chessboard_corners(image_paths, XX, YY):
    imgpoints = []
    image_size = None
    for i in range(0, len(image_paths)):
        image_path = image_paths[i]
        img = cv2.imread(image_path)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if image_size is None:
            image_size = gray.shape[::-1]
        find_corners_ret, corners = _find_chessboard_corners(gray, XX, YY, flags=cv2.CALIB_CB_ADAPTIVE_THRESH+cv2.CALIB_CB_FAST_CHECK
                                                             + cv2.CALIB_CB_NORMALIZE_IMAGE,
                                                             criteria=(cv2.TERM_CRITERIA_MAX_ITER |
                                                                       cv2.TERM_CRITERIA_EPS, 30, 0.001),
                                                             winsize=(11, 11))

        # corners: order in row by row, and left to right in each row
        if find_corners_ret:
            imgpoints.append(corners)
        else:
            print(f"Can not find checkerboard corners of {image_path}, Skip.")
    return imgpoints


def calculate_reproject_error(image_paths,
                              rvecs_target2cam, tvecs_target2cam, mtx, dist,
                              XX, YY, L,
                              vis=False, save_fig=False, save_dir='output'):
    # TBD: remove this function
    """rvecs, tvecs represent transformation of checkerboard to camera
    """
    imgpoints = get_chessboard_corners(image_paths, XX, YY)

    num_images = len(image_paths)
    objpoints = get_objpoints(num_images, XX, YY, L)

    return calculate_reproject_error_fast(imgpoints, objpoints,
                                          rvecs_target2cam, tvecs_target2cam, mtx, dist,
                                          image_paths, XX, YY, vis, save_fig, save_dir)