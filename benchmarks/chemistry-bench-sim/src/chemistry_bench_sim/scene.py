"""Isaac Sim 场景：从 semantics.yaml 程序化搭建化学实验台。

约束：本模块只能在 SimulationApp 初始化之后 import（omni.* 延迟导入）。
液体渲染近似：容器=固定圆柱，液体=按体积缩放的彩色圆柱（displayColor
由化学引擎的 color_of 驱动）——验收标准是 VLM 可判读，不是物理流体。
代码需兼容 Python 3.10。
"""

from __future__ import annotations

import io
from typing import Any

import numpy as np
from chemistry_bench_chemistry import COLOR_RGB, Vessel, color_of, mix, ph_of
from PIL import Image, ImageDraw, ImageFont

TABLE_TOP = 0.76  # 桌面高度（米）
VESSEL_R = {"bottle": 0.035, "beaker": 0.05, "flask": 0.045}
VESSEL_H = {"bottle": 0.18, "beaker": 0.12, "flask": 0.15}
# 液体高度换算：h = volume_ml / (πr² * 1e6) 太细 → 用满杯比例近似
FRANKA_HOME = [0.0, -1.0, 0.0, -2.2, 0.0, 1.6, 0.79, 0.04, 0.04]
BASE_H = 0.025  # 容器底座高度


class ChemScene:
    """实验台世界：Isaac 物件 + 化学状态（vessels 为唯一事实源）。"""

    def __init__(self, world: Any, semantics: dict, spec: dict):
        self.world = world
        self.semantics = semantics
        self.spec = spec
        self.vessels: dict[str, Vessel] = {}
        self.held_object: str | None = None
        self.findings: list[str] = []
        self._prims: dict[str, Any] = {}
        self._liquids: dict[str, Any] = {}
        self.franka = None
        self.camera = None
        self._kinematics = None
        self._held_offset = None
        self._held_rotation = None
        self._record_tick = 0
        self.recorder = None
        self.action_label = "Ready"
        self.action_status = "READY"
        self.task_success = False
        self._build()

    # ------------------------------------------------------------------ #

    def _build(self) -> None:
        import os

        from isaacsim.core.api.objects import FixedCuboid, VisualCylinder
        from isaacsim.sensors.camera import Camera

        print("[scene] building table & vessels", flush=True)

        self.world.scene.add_default_ground_plane()
        FixedCuboid(
            prim_path="/World/table",
            position=np.array([0.35, 0.0, TABLE_TOP / 2]),
            scale=np.array([1.2, 1.1, TABLE_TOP]),
            color=np.array([0.23, 0.29, 0.35]),
        )
        from isaacsim.core.utils.stage import get_current_stage
        from pxr import UsdLux

        light = UsdLux.DomeLight.Define(get_current_stage(), "/World/lab_light")
        light.CreateIntensityAttr(700.0)

        for obj in self.semantics.get("objects", []):
            if obj.get("category") not in VESSEL_R:
                continue
            init = obj.get("init", {})
            name = obj["name"]
            pos = init.get("position", [0.5, 0.0, 0.1])
            v = Vessel(
                name=name,
                category=obj["category"],
                position=[pos[0], pos[1], TABLE_TOP],
                volume_ml=float(init.get("volume_ml", 0.0)),
                capacity_ml=float(init.get("capacity_ml", 250.0)),
                solute=init.get("solute"),
                concentration=float(init.get("concentration", 0.0)),
                indicator=init.get("indicator"),
                is_open=bool(init.get("is_open", True)),
                graspable="graspable" in obj.get("affordances", []),
                pourable="pourable" in obj.get("affordances", []),
            )
            self.vessels[name] = v
            r, h = VESSEL_R[v.category], VESSEL_H[v.category]
            # 容器 = 底座矮圆柱（灰）; 液体 = 其上按体积伸缩的彩色圆柱（主可见体）
            self._prims[name] = VisualCylinder(
                prim_path=f"/World/{name}",
                radius=r,
                height=BASE_H,
                position=np.array(
                    [v.position[0], v.position[1], TABLE_TOP + BASE_H / 2]
                ),
                color=np.array([0.45, 0.48, 0.52]),
            )
            self._liquids[name] = VisualCylinder(
                prim_path=f"/World/{name}_liquid",
                radius=r * 0.92,
                height=h,
                position=np.array(
                    [v.position[0], v.position[1], TABLE_TOP + BASE_H + h / 2]
                ),
                color=np.array([0.9, 0.9, 0.9]),
            )

        robot_usd = os.environ.get(
            "CHEMISTRY_BENCH_FRANKA_USD"
        )  # 本地路径或云路径; 未设=无机器人
        if robot_usd:
            print(f"[scene] loading robot from {robot_usd}", flush=True)
            from isaacsim.core.utils.stage import add_reference_to_stage

            add_reference_to_stage(usd_path=robot_usd, prim_path="/World/franka")
            from isaacsim.core.api.robots import Robot

            self.franka = self.world.scene.add(
                Robot(
                    prim_path="/World/franka",
                    name="franka",
                    position=np.array([0.0, 0.0, TABLE_TOP]),
                )
            )
        print("[scene] adding camera", flush=True)

        self.camera = Camera(prim_path="/World/main_camera", resolution=(1280, 720))
        self.camera.set_focal_length(1.8)  # 18 mm USD lens, full bench/arm framing.
        from isaacsim.core.utils.viewports import set_camera_view

        set_camera_view(
            eye=[1.65, -1.55, 1.8],
            target=[0.28, 0.0, TABLE_TOP + 0.3],
            camera_prim_path="/World/main_camera",
        )

    def post_reset(self) -> None:
        if self.camera is not None:
            self.camera.initialize()
        if self.franka is not None:
            from isaacsim.core.utils.extensions import enable_extension

            enable_extension("isaacsim.robot_motion.motion_generation")
            from isaacsim.robot_motion.motion_generation import (
                ArticulationKinematicsSolver,
                LulaKinematicsSolver,
                interface_config_loader,
            )

            solver = LulaKinematicsSolver(
                **interface_config_loader.load_supported_lula_kinematics_solver_config(
                    "Franka"
                )
            )
            solver.set_robot_base_pose(*self.franka.get_world_pose())
            self._kinematics = ArticulationKinematicsSolver(
                self.franka, solver, "right_gripper"
            )
            self._set_joints(np.array(FRANKA_HOME))
        self._held_offset = self._held_rotation = None
        self.task_success = False
        self.action_label, self.action_status = "Ready", "READY"
        self.sync_visuals()

    # ------------------------------------------------------------------ #

    def sync_visuals(self) -> None:
        """化学状态 → 液体 prim（液位=高度缩放, 颜色=displayColor）。"""
        for name, v in self.vessels.items():
            liquid = self._liquids[name]
            frac = (
                1.0
                if v.category == "bottle"
                else max(min(v.volume_ml / v.capacity_ml, 1.0), 0.08)
            )
            h = VESSEL_H[v.category]
            if self.held_object == name and self._held_offset is not None:
                position, hand_rotation = self._kinematics.compute_end_effector_pose()
                origin = position + hand_rotation @ self._held_offset
                rotation = hand_rotation @ self._held_rotation
            else:
                origin = np.array([v.position[0], v.position[1], TABLE_TOP])
                rotation = np.eye(3)
            from isaacsim.core.utils.rotations import rot_matrix_to_quat

            quat = rot_matrix_to_quat(rotation)
            liquid.set_local_scale(np.array([1.0, 1.0, frac]))
            liquid.set_world_pose(
                position=origin + rotation @ np.array([0, 0, BASE_H + h * frac / 2]),
                orientation=quat,
            )
            rgb = COLOR_RGB.get(color_of(v), COLOR_RGB["clear"])
            try:
                liquid.get_applied_visual_material().set_color(np.array(rgb))
            except Exception:
                from pxr import Gf, UsdGeom

                UsdGeom.Gprim(liquid.prim).GetDisplayColorAttr().Set([Gf.Vec3f(*rgb)])
            body = self._prims[name]
            body.set_world_pose(
                position=origin + rotation @ np.array([0, 0, BASE_H / 2]),
                orientation=quat,
            )

    def hand_pos(self) -> list[float]:
        if self._kinematics is None:
            raise RuntimeError("Demo requires an initialized Franka robot")
        position, _ = self._kinematics.compute_end_effector_pose()
        return list(position)

    def steps(self, n: int) -> None:
        for _ in range(n):
            self._record_tick += 1
            # Physics stays at 60 Hz; render only the 20 Hz frames we present.
            rendered = self._record_tick % 3 == 0
            self.world.step(render=rendered)
            self._sample_traj()
            if rendered:
                self.capture_live()
            if self.recorder is not None and self._record_tick % 3 == 0:
                self.recorder.add(
                    self.rgb_png()[0],
                    self.action_label,
                    self.action_status,
                    self.task_success,
                )

    def start_recording(self, directory: str) -> None:
        from .recording import DemoRecorder

        self.finish_recording()
        self.recorder = DemoRecorder(directory)
        self._record_tick = 0
        self.steps(60)

    def finish_recording(self) -> None:
        if self.recorder is not None:
            self.recorder.close()
            self.recorder = None

    def capture_live(self) -> None:
        """实时帧旁路：节流(~5Hz)渲染主相机推入 worker 的 FrameBuffer。

        在 steps() 内部调用, 长动作(倒液/运动)执行期间控制台直播不断流;
        worker 主循环在空闲期也调用, 保证静止画面存活。"""
        cb = getattr(self, "on_live_frame", None)
        if cb is None:
            return
        import time  # 节流用途, 不参与仿真时序

        now = time.monotonic()
        if now - getattr(self, "_live_t", 0.0) < 0.2:
            return
        self._live_t = now
        try:
            cb(*self.rgb_png())
        except Exception:  # noqa: BLE001 — 直播失败不得影响仿真
            pass

    def _sample_traj(self) -> None:
        """~每6步采样一帧关节态进当前动作的轨迹缓冲（60Hz 物理 → ~10Hz）。"""
        self._traj_tick = getattr(self, "_traj_tick", 0) + 1
        if self._traj_tick % 6:
            return
        buf = getattr(self, "traj_buffer", None)
        if buf is None:
            return
        jp = [0.0] * 7
        grip = 0.03 if self.held_object else 0.08
        if self.franka is not None:
            try:
                arr = [float(x) for x in np.array(self.franka.get_joint_positions())]
                jp, grip = arr[:7], abs(arr[-1]) * 2 if len(arr) > 7 else grip
            except Exception:
                pass
        buf.append(
            {"t": round(float(self.world.current_time), 3), "state": jp + [grip]}
        )

    # ---- 原语（与 mock 后端同一套语义） ---------------------------------- #

    def pick(self, target: str) -> str | None:
        if target not in self.vessels:
            return "object not found: " + target
        if self.held_object is not None:
            return "gripper already holding " + self.held_object
        if not self.vessels[target].graspable:
            return target + " is not graspable"
        v = self.vessels[target]
        self._gripper(0.04)
        self._move_tcp([v.position[0], v.position[1], TABLE_TOP + 0.4])
        self._move_tcp([v.position[0], v.position[1], TABLE_TOP + 0.14], frames=45)
        self._gripper(0.032)
        position, rotation = self._kinematics.compute_end_effector_pose()
        self._held_offset = rotation.T @ (np.array(v.position) - position)
        self._held_rotation = rotation.T
        self.held_object = target
        self.sync_visuals()
        self._move_tcp([v.position[0], v.position[1], TABLE_TOP + 0.4])
        self.steps(30)
        return None

    def place(self, position: list[float]) -> str | None:
        if self.held_object is None:
            return "gripper is empty"
        v = self.vessels[self.held_object]
        self._move_tcp([float(position[0]), float(position[1]), TABLE_TOP + 0.4])
        self._move_tcp(
            [float(position[0]), float(position[1]), TABLE_TOP + 0.14], frames=45
        )
        self._gripper(0.04)
        v.position = [float(position[0]), float(position[1]), TABLE_TOP]
        self.held_object = None
        self._held_offset = self._held_rotation = None
        self.sync_visuals()
        self._move_tcp([float(position[0]), float(position[1]), TABLE_TOP + 0.4])
        self._animate_arm(FRANKA_HOME, frames=60)
        self.steps(30)
        return None

    def pour(self, target: str, volume_ml: float) -> str | None:
        if self.held_object is None:
            return "gripper is empty, cannot pour"
        if target not in self.vessels:
            return "target vessel not found: " + target
        src, tgt = self.vessels[self.held_object], self.vessels[target]
        if not src.is_open:
            return src.name + " is not open"
        if not tgt.is_open:
            return target + " is not open"
        if not np.isfinite(volume_ml) or volume_ml <= 0:
            return "pour volume must be positive and finite"
        # Deterministic Cartesian waypoints, without collision/contact planning.
        position = [tgt.position[0], tgt.position[1] - 0.10, TABLE_TOP + 0.38]
        self._move_tcp(position)
        from isaacsim.core.utils.rotations import euler_angles_to_quat

        tilted = euler_angles_to_quat(np.array([np.pi - np.deg2rad(65), 0.0, 0.0]))
        self._move_tcp(position, orientation=tilted, frames=45)
        for _ in range(60):
            mix(tgt, src, float(volume_ml) / 60)
            self.sync_visuals()
            self.steps(1)
        self._move_tcp(position, frames=45)
        self.steps(30)
        return None

    def open_container(self, target: str) -> str | None:
        if target not in self.vessels:
            return "object not found: " + target
        self.vessels[target].is_open = True
        return None

    def record_finding(self, text: str) -> None:
        self.findings.append(text)

    def _set_joints(self, joints: np.ndarray) -> None:
        if self.franka is None:
            raise RuntimeError("Scripted arm motion requires a Franka asset")
        from isaacsim.core.utils.types import ArticulationAction

        self.franka.set_joint_positions(joints)
        self.franka.set_joint_velocities(np.zeros_like(joints))
        # Keep articulation drive targets consistent with the scripted pose.
        self.franka.apply_action(ArticulationAction(joint_positions=joints))

    def _animate_arm(self, joints: list[float], frames: int = 45) -> None:
        if self.franka is None:
            raise RuntimeError("Scripted arm motion requires a Franka asset")
        current = np.array(self.franka.get_joint_positions())
        goal = np.array(joints)
        if goal.shape != current.shape:
            raise RuntimeError("Scripted joint target does not match the robot")
        for t in np.linspace(0.0, 1.0, frames):
            weight = t * t * (3 - 2 * t)
            self._set_joints(current * (1 - weight) + goal * weight)
            self.sync_visuals()
            self.steps(1)

    def _gripper(self, opening: float) -> None:
        if self.franka is None:
            raise RuntimeError("Gripper motion requires a Franka asset")
        goal = np.array(self.franka.get_joint_positions())
        if len(goal) != 9:
            raise RuntimeError("Expected seven arm and two finger joints")
        goal[7:] = opening
        self._animate_arm(goal, frames=24)

    def _move_tcp(
        self, position: list[float], orientation=None, frames: int = 60
    ) -> None:
        if self._kinematics is None:
            raise RuntimeError("Franka kinematics is not initialized")
        action, success = self._kinematics.compute_inverse_kinematics(
            target_position=np.array(position),
            target_orientation=np.array([0.0, 1.0, 0.0, 0.0])
            if orientation is None
            else orientation,
            position_tolerance=0.002,
            orientation_tolerance=0.02,
        )
        if not success:
            raise RuntimeError(f"Scripted waypoint is unreachable: {position}")
        goal = np.array(self.franka.get_joint_positions())
        goal[action.joint_indices] = action.joint_positions
        self._animate_arm(goal, frames=frames)

    # ---- 观测与快照 ------------------------------------------------------ #

    def rgb_png(self) -> tuple[bytes, int, int]:
        rgba = self.camera.get_rgba() if self.camera is not None else None
        if rgba is None or getattr(rgba, "size", 0) == 0:
            raise RuntimeError("Camera has no rendered frame")
        else:
            arr = np.asarray(rgba)
            img = Image.fromarray(arr[:, :, :3].astype(np.uint8))
        # Static object names only: no privileged chemistry values in planner RGB.
        try:
            font = ImageFont.truetype("DejaVuSans.ttf", 17)
        except OSError:
            font = ImageFont.load_default()
        draw = ImageDraw.Draw(img)
        for name, liquid in self._liquids.items():
            position, _ = liquid.get_world_pose()
            pixel = self.camera.get_image_coords_from_world_points(
                np.array([position])
            )[0]
            if not np.all(np.isfinite(pixel)):
                continue
            x, y = int(pixel[0]) + 18, int(pixel[1]) - 24
            if not (0 <= x < img.width - 140 and 0 <= y < img.height - 24):
                continue
            box = draw.textbbox((x, y), name, font=font)
            draw.rectangle(
                (box[0] - 5, box[1] - 3, box[2] + 5, box[3] + 3), fill=(20, 31, 45)
            )
            draw.text((x, y), name, font=font, fill=(234, 243, 251))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue(), img.width, img.height

    def proprio(self) -> dict:
        hp = self.hand_pos()
        ee = [hp[0], hp[1], hp[2], 1.0, 0.0, 0.0, 0.0]
        grip = 0.03 if self.held_object is not None else 0.08
        jp = [0.0] * int(self.spec.get("dof", 7))
        if self.franka is not None:
            try:
                jp = [float(x) for x in np.array(self.franka.get_joint_positions())][:7]
            except Exception:
                pass
        return {"joint_positions": jp, "gripper_width": grip, "ee_pose": ee}

    def privileged_payload(self) -> dict:
        return {
            "vessels": {
                n: {
                    "position": list(v.position),
                    "volume_ml": round(v.volume_ml, 3),
                    "solute": v.solute,
                    "concentration": round(v.concentration, 6),
                    "ph": round(ph_of(v), 3),
                    "color": color_of(v),
                    "is_open": v.is_open,
                }
                for n, v in self.vessels.items()
            },
            "held_object": self.held_object,
            "findings": list(self.findings),
        }

    def snapshot(self) -> dict:
        return {
            "vessels": {n: v.to_dict() for n, v in self.vessels.items()},
            "held_object": self.held_object,
            "findings": list(self.findings),
        }

    def restore(self, payload: dict) -> None:
        if payload.get("vessels"):
            self.vessels = {n: Vessel(**d) for n, d in payload["vessels"].items()}
        self.held_object = payload.get("held_object")
        self.findings = list(payload.get("findings", []))
        self.sync_visuals()
