from .camera_calibrator import _calibrate_intrinsic_camera_parameters
import numpy as np
import imutils
import os


class CameraIntrinsicParamsCalibrator:
    def __init__(self, XX, YY, L):
        # input
        self.XX = XX
        self.YY = YY
        self.L = L
        self.intrinsic_calib_image_paths = None

        # output
        self.dist = None
        self.mtx = None

    def load_intrinsic_calib_images(self, INTRINSIC_CALIB_DATA_DIR, image_idxs=None):
        """Load the intrinsic calibration images from the specified image paths."""
        image_paths = list(imutils.paths.list_images(INTRINSIC_CALIB_DATA_DIR))
        image_paths.sort(key=lambda x: int(os.path.split(x)[-1].split('.')[0]))
        calib_image_paths = image_paths if image_idxs is None else np.array(image_paths)[image_idxs].flatten()

        self.intrinsic_calib_image_paths = calib_image_paths

    def load(self, INTRINSIC_CALIB_DATA_DIR, image_idxs=None):
        """Load the intrinsic calibration images from the specified directory."""
        self.load_intrinsic_calib_images(INTRINSIC_CALIB_DATA_DIR, image_idxs)

    def calibrate(self, verbose=False):
        """Run calibration."""
        if self.XX is None or self.YY is None or self.L is None:
            raise ValueError("Checkerboard size has not been loaded yet.")

        if self.intrinsic_calib_image_paths is None:
            raise ValueError("Intrinsic calibration images have not been loaded yet.")

        mtx, dist = _calibrate_intrinsic_camera_parameters(
            self.intrinsic_calib_image_paths, self.XX, self.YY, self.L, verbose=verbose)

        self.camera_matrix = mtx
        self.distortion_coefficients = dist

    def save(self, save_dir):
        """Save the intrinsic parameters to the specified directory."""
        if not os.path.isdir(save_dir):
            os.makedirs(save_dir)
        np.save(f'{save_dir}/mtx.npy', self.camera_matrix)
        np.save(f'{save_dir}/dist.npy', self.distortion_coefficients)

    def get_params(self):
        return self.camera_matrix, self.distortion_coefficients

    @classmethod
    def reload(cls, save_dir):
        camera_matrix_path = f'{save_dir}/mtx.npy'
        if not os.path.isfile(camera_matrix_path):
            raise ValueError(f"Camera intrinsic parameters have not been saved at {save_dir} yet.")
        distortion_coefficients_path = f'{save_dir}/dist.npy'
        if not os.path.isfile(distortion_coefficients_path):
            raise ValueError(f"Camera distortion coefficients have not been saved at {save_dir} yet.")

        camera_matrix = np.load(camera_matrix_path)
        distortion_coefficients = np.load(distortion_coefficients_path)
        return camera_matrix, distortion_coefficients