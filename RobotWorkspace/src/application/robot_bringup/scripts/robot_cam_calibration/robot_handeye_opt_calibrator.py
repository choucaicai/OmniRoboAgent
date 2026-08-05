# from robot_camera_calibration
import imutils
import os
import numpy as np
from .calibration_utils import calculate_reproject_error_fast
from .utils import xyz_rpy_to_matrix, inverse_transform_matrix, matrix_to_xyz_rpy
from .camera_intrinsic_params_calibrator import CameraIntrinsicParamsCalibrator
from .calibration_utils import get_chessboard_corners, get_objpoints
import nlopt
from .eyehand_calibrator import EyetoHandCalibrator
from .calibration_utils import calculate_reproject_error_fast, calculate_single_image_reprojection_error


class HandEyeOptCalibrator(EyetoHandCalibrator):
    def __init__(self, XX, YY, L):
        super().__init__(XX, YY, L)

        self.OPT_FTOL_REL = 10e-6
        self.OPT_MAXEVAL = 10000

        # eyehand calibration data and result
        self.ee2base_Ms = None
        self.cam2base_4x4 = None

        self.init_target2ee_4x4 = None
        self.target2ee_4x4 = None
        self.init_cam2base_4x4 = None
        self.cam2base_4x4 = None

    def load(self):
        pass

    # def load_initial_eyehand_calibration_result(self, save_dir):
    #     self.cam2base_R = np.load(f"{save_dir}/cam2base_R.npy")
    #     self.cam2base_t = np.load(f"{save_dir}/cam2base_t.npy")
    #     self.ee2base_Ms = np.load(f"{save_dir}/ee2base_Ms.npy")

    #     self.base2ee_Ms = np.array([inverse_transform_matrix(x) for x in self.ee2base_Ms])

    #     # reformat cam2base_4x4
    #     self.cam2base_4x4 = np.eye(4)
    #     self.cam2base_4x4[:3, :3] = self.cam2base_R
    #     self.cam2base_4x4[:3, 3] = self.cam2base_t.flatten()
    #     self.init_cam2base_4x4 = self.cam2base_4x4

    #     self.base2cam_4x4 = np.linalg.inv(self.cam2base_4x4)

    #     self.rvecs_board2cam = np.load(f"{save_dir}/rvecs_board2cam.npy")
    #     self.tvecs_board2cam = np.load(f"{save_dir}/tvecs_board2cam.npy")

    def load_calibration_images(self, HANDEYE_CALIB_DATA_DIR, selected_idxs=None):
        extrinsic_calib_image_paths = list(imutils.paths.list_images(HANDEYE_CALIB_DATA_DIR))
        extrinsic_calib_image_paths.sort(key=lambda x: int(os.path.split(x)[-1].split('.')[0]))

        self.extrinsic_calib_image_paths = extrinsic_calib_image_paths if selected_idxs is None else np.array(
            extrinsic_calib_image_paths)[selected_idxs].flatten()

        num_images = len(self.extrinsic_calib_image_paths)
        self.objpoints = get_objpoints(num_images, self.XX, self.YY, self.L)
        self.imgpoints = get_chessboard_corners(self.extrinsic_calib_image_paths, self.XX, self.YY)

    def optmize(self):
        # Iterative optimization loop
        for i in range(3):
            print(f"############### ITERATION {i+1} ################")
            print("------------OPT target2ee ---------------------")
            # optimize target2ee
            self.opt_target2ee(verbose=False)
            print("------------OPT cam2base ---------------------")
            # optmize cam2base
            self.opt_cam2base(verbose=False)

    def save(self, save_dir):
        if not os.path.isdir(save_dir):
            os.makedirs(save_dir)

        # save opt target2ee matrx
        np.save(f"{save_dir}/target2ee_4x4.npy", self.target2ee_4x4)
        np.save(f"{save_dir}/init_target2ee_4x4.npy", self.init_target2ee_4x4)
        np.save(f"{save_dir}/cam2base_4x4.npy", self.cam2base_4x4)
        np.save(f"{save_dir}/init_cam2base_4x4.npy", self.init_cam2base_4x4)

    def set_initial_imageid(self, init_target2cam_image_idx):
        self.init_target2cam_image_idx = init_target2cam_image_idx

    def opt_target2ee(self, verbose: bool = True):
        if self.init_target2cam_image_idx is None:
            raise ValueError("Initial target2cam image index has not been set yet.")
        # init pos
        # self.init_target2cam_image_idx = 32
        x_target2cam, y_target2cam, z_target2cam, roll_target2cam, pitch_target2cam, yaw_target2cam = \
            self.tvecs_board2cam[self.init_target2cam_image_idx][0].item(), \
            self.tvecs_board2cam[self.init_target2cam_image_idx][1].item(), \
            self.tvecs_board2cam[self.init_target2cam_image_idx][2].item(), \
            self.rvecs_board2cam[self.init_target2cam_image_idx][0].item(), \
            self.rvecs_board2cam[self.init_target2cam_image_idx][1].item(), \
            self.rvecs_board2cam[self.init_target2cam_image_idx][2].item()

        target2cam_4x4 = xyz_rpy_to_matrix([x_target2cam, y_target2cam, z_target2cam,
                                            roll_target2cam, pitch_target2cam, yaw_target2cam])
        target2ee_4x4 = self.base2ee_Ms[self.init_target2cam_image_idx] @ self.cam2base_4x4 @ target2cam_4x4
        if self.init_target2ee_4x4 is None:
            self.init_target2ee_4x4 = target2ee_4x4
        x, y, z, roll, pitch, yaw = matrix_to_xyz_rpy(target2ee_4x4)

        # Choose the NL_NELDERMEAD algorithm (gradient-free)
        opt = nlopt.opt(nlopt.LN_NELDERMEAD, 6)  # 6 is the number of variables

        # Set the objective function
        opt.set_min_objective(self.objective_function_target2ee)

        # Set lower and upper bounds for each variable
        lower_bounds = [-10, -10, -10, -10, -10, -10]
        upper_bounds = [10, 10, 10, 10, 10, 10]
        opt.set_lower_bounds(lower_bounds)
        opt.set_upper_bounds(upper_bounds)

        # Set stopping criteria (e.g., tolerance)
        opt.set_ftol_rel(self.OPT_FTOL_REL)
        # opt.set_maxeval(self.OPT_MAXEVAL)s

        # Set an initial guess for the variables
        # x_initial = [1, 1, 1, 1, 1, 1]
        x_initial = [x, y, z, roll, pitch, yaw]
        # x_initial = [x_target2cam, y_target2cam, z_target2cam, roll_target2cam, pitch_target2cam, yaw_target2cam]
        print(f"X initial: {x_initial}")

        # opt.set_initial_step(0.1)  # Sets the initial step size to 0.1 for all variables
        # Manually try specific x values
        x_test = x_initial
        test_result = self.objective_function_target2ee(x_test, None)
        print(f"Loss initial: {test_result}")

        # Run the optimizer
        x_optimal = opt.optimize(x_initial)
        optimal_value = opt.last_optimum_value()

        print(f"Optimal variables: {x_optimal}")
        x_opt, y_opt, z_opt, roll_opt, pitch_opt, yaw_opt = x_optimal[0], x_optimal[1], x_optimal[2], \
            x_optimal[3], x_optimal[4], x_optimal[5]

        print(f"Optimcal loss: {optimal_value}")
        # return x_opt, y_opt, z_opt, roll_opt, pitch_opt, yaw_opt
        self.target2ee_4x4 = xyz_rpy_to_matrix([x_opt, y_opt, z_opt, roll_opt, pitch_opt, yaw_opt])

    def objective_function_target2ee(self, x, grad=None):
        """accuracy of target2cam results in reprojection error"""
        x_, y_, z_, roll_,  pitch_, yaw_ = x[0], x[1], x[2], x[3], x[4], x[5]

        # target2cam_4x4_list = calculate_target2cam_4x4_list(x_, y, z, roll, pitch, yaw, init_target2cam_image_idx)
        target2cam_4x4_list = self.calculate_target2cam_4x4_list_target2ee(x_, y_, z_, roll_,  pitch_, yaw_, self.cam2base_4x4,
                                                                           self.ee2base_Ms)
        rvecs_v2 = np.array(target2cam_4x4_list)[:, :3, :3]
        tvecs_v2 = np.array(target2cam_4x4_list)[:, :3, 3]
        # print(tvecs_v2[0])

        error = calculate_reproject_error_fast(
            imgpoints=self.imgpoints,
            objpoints=self.objpoints,
            rvecs_target2cam=rvecs_v2,
            tvecs_target2cam=tvecs_v2,
            mtx=self.mtx,
            dist=self.dist,
            image_paths=self.extrinsic_calib_image_paths,
            XX=self.XX,
            YY=self.YY,
            vis=False,
            save_fig=False)

        # Update previous loss
        current_loss = error
        return current_loss

    def calculate_target2cam_4x4_list_target2ee(self, x, y, z, roll, pitch, yaw, cam2base_H, end2base_Ms):
        """x, y, z, roll, pitch, yaw represents transformation from target(checkerboard) to camera"""
        target2cam_4x4_list = []

        target2gripper_4x4 = xyz_rpy_to_matrix([x, y, z, roll, pitch, yaw])

        # base2cam
        base2cam_4x4 = np.linalg.inv(cam2base_H)

        # calculate target2cam per image
        for end2base_M in end2base_Ms:
            # gripper2base
            gripper2base_4x4 = end2base_M

            # target2cam
            target2cam_4x4 = base2cam_4x4 @ gripper2base_4x4 @ target2gripper_4x4
            target2cam_4x4_list.append(target2cam_4x4)
        return target2cam_4x4_list  # (num_images, 4, 4)

    def calculate_target2cam_list_on_cam2base2(self, cam2base_x, cam2base_y, cam2base_z, cam2base_roll, cam2base_yaw,
                                               cam2base_pitch, ee2base_Ms, target2ee_4x4):
        # target2cam = target2ee(gt) * ee2base(gt) * base2cam
        cam2base_4x4 = xyz_rpy_to_matrix([cam2base_x, cam2base_y, cam2base_z,
                                          cam2base_roll, cam2base_yaw, cam2base_pitch])

        # target2cam = target2ee * ee2base * base2cam
        eyehand_target2cam_4x4_list = []
        # base2cam
        base2cam_4x4 = np.linalg.inv(cam2base_4x4)
        for idx in range(0, len(ee2base_Ms)):
            eyehand_target2cam_4x4 = base2cam_4x4 @ ee2base_Ms[idx] @ target2ee_4x4
            eyehand_target2cam_4x4_list.append(eyehand_target2cam_4x4)
        return eyehand_target2cam_4x4_list

    def objective_function_cam2base(self, x, grad=None):
        x_, y_, z_, roll_,  pitch_, yaw_ = x[0], x[1], x[2], x[3], x[4], x[5]

        # target2cam_4x4_list = calculate_target2cam_4x4_list(x_, y, z, roll, pitch, yaw, init_target2cam_image_idx)
        target2cam_4x4_list = self.calculate_target2cam_list_on_cam2base2(x_, y_, z_, roll_,  pitch_, yaw_,
                                                                          self.ee2base_Ms,
                                                                          self.target2ee_4x4)
        rvecs_v2 = np.array(target2cam_4x4_list)[:, :3, :3]
        tvecs_v2 = np.array(target2cam_4x4_list)[:, :3, 3]
        # print(tvecs_v2[0])

        error = calculate_reproject_error_fast(
            imgpoints=self.imgpoints,
            objpoints=self.objpoints,
            image_paths=self.extrinsic_calib_image_paths,
            rvecs_target2cam=rvecs_v2,
            tvecs_target2cam=tvecs_v2,
            mtx=self.mtx,
            dist=self.dist,
            XX=self.XX,
            YY=self.YY,
            vis=False,
            save_fig=False)

        # Update previous loss
        current_loss = error

        # calculate_target2cam_4x4_list()
        return current_loss

    def opt_cam2base(self, verbose: bool = True):

        # # init pos
        x_target2cam, y_target2cam, z_target2cam, roll_target2cam, pitch_target2cam, yaw_target2cam = \
            self.tvecs_board2cam[self.init_target2cam_image_idx][0].item(), \
            self.tvecs_board2cam[self.init_target2cam_image_idx][1].item(), \
            self.tvecs_board2cam[self.init_target2cam_image_idx][2].item(), \
            self.rvecs_board2cam[self.init_target2cam_image_idx][0].item(), \
            self.rvecs_board2cam[self.init_target2cam_image_idx][1].item(), \
            self.rvecs_board2cam[self.init_target2cam_image_idx][2].item()

        target2cam_4x4 = xyz_rpy_to_matrix([x_target2cam, y_target2cam, z_target2cam,
                                            roll_target2cam, pitch_target2cam, yaw_target2cam])
        # init cam2base by opt target2ee
        cam2base_4x4 = self.ee2base_Ms[self.init_target2cam_image_idx] @ self.target2ee_4x4 @ inverse_transform_matrix(
            target2cam_4x4)
        x, y, z, roll, pitch, yaw = matrix_to_xyz_rpy(cam2base_4x4)

        # Choose the NL_NELDERMEAD algorithm (gradient-free)
        opt = nlopt.opt(nlopt.LN_NELDERMEAD, 6)  # 6 is the number of variables

        # Set the objective function
        opt.set_min_objective(self.objective_function_cam2base)

        # Set lower and upper bounds for each variable
        lower_bounds = [-10, -10, -10, -10, -10, -10]
        upper_bounds = [10, 10, 10, 10, 10, 10]
        opt.set_lower_bounds(lower_bounds)
        opt.set_upper_bounds(upper_bounds)

        # Set stopping criteria (e.g., tolerance)
        opt.set_ftol_rel(self.OPT_FTOL_REL)
        # opt.set_maxeval(OPT_MAXEVAL)

        # Set an initial guess for the variables
        # x_initial = [1, 1, 1, 1, 1, 1]
        x_initial = [x, y, z, roll, pitch, yaw]
        # x_initial = [x_target2cam, y_target2cam, z_target2cam, roll_target2cam, pitch_target2cam, yaw_target2cam]
        print(f"X initial: {x_initial}")

        # opt.set_initial_step(0.1)  # Sets the initial step size to 0.1 for all variables
        # Manually try specific x values
        x_test = x_initial
        test_result = self.objective_function_cam2base(x_test, None)
        print(f"Loss initial: {test_result}")

        # Run the optimizer
        x_optimal = opt.optimize(x_initial)
        optimal_value = opt.last_optimum_value()

        print(f"Optimal variables: {x_optimal}")
        x_opt, y_opt, z_opt, roll_opt, pitch_opt, yaw_opt = x_optimal[0], x_optimal[1], x_optimal[2], \
            x_optimal[3], x_optimal[4], x_optimal[5]

        print(f"Optimal loss: {optimal_value}")
        # return x_opt, y_opt, z_opt, roll_opt, pitch_opt, yaw_opt
        self.optimized_cam2base = xyz_rpy_to_matrix([x_opt, y_opt, z_opt, roll_opt, pitch_opt, yaw_opt])

    def opt_handeye_calib_reproject_error(self, vis=False):

        base2cam_4x4 = np.linalg.inv(self.cam2base_4x4)

        errors = []
        for i in range(0, len(self.base2ee_Ms)):
            # target2cam_4x4 = xyz_rpy_to_matrix(self.tvecs_board2cam[i].flatten().tolist() + self.rvecs_board2cam[i].flatten().tolist())
            # target2ee_4x4 = self.base2ee_Ms[i] @ self.cam2base_4x4 @ target2cam_4x4
            # self.target2ee_Ms.append(target2ee_4x4)
            eyehand_target2cam_4x4 = base2cam_4x4 @ self.ee2base_Ms[i] @ self.target2ee_4x4
            error = calculate_single_image_reprojection_error(
                self.extrinsic_calib_image_paths[i],
                eyehand_target2cam_4x4[:3, :3], eyehand_target2cam_4x4[:3, 3], self.mtx, self.dist, self.XX, self.YY, self.L, vis=vis)
            errors.append(error)
        return np.array(errors)

    @classmethod
    def reload(cls, save_dir):
        target2ee_4x4 = np.load(f"{save_dir}/target2ee_4x4.npy")
        init_target2ee_4x4 = np.load(f"{save_dir}/init_target2ee_4x4.npy")
        cam2base_4x4 = np.load(f"{save_dir}/cam2base_4x4.npy")
        # init_cam2base_4x4 = np.load(f"{save_dir}/init_cam2base_4x4.npy")

        calibrator = cls(None, None, None)
        calibrator.target2ee_4x4 = target2ee_4x4
        calibrator.init_target2ee_4x4 = init_target2ee_4x4
        calibrator.cam2base_4x4 = cam2base_4x4
        # calibrator.init_cam2base_4x4 = init_cam2base_4x4

        return calibrator