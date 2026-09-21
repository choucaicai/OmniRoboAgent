"""sim_worker 入口：SimulationApp(必须最先初始化) → gRPC SimBackend 服务。

启动:  python -m chemistry_bench_sim.worker --port 50051 [--webrtc]
"""

from __future__ import annotations

import argparse
import json
import queue
import threading
import time
from concurrent import futures


class FrameBuffer:
    """最新帧缓冲：主线程写入, 流式 RPC 线程等待读取（不触碰 Kit）。"""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._frame: tuple[bytes, int, int] | None = None
        self._seq = 0

    def push(self, png: bytes, width: int, height: int) -> None:
        with self._cond:
            self._frame = (png, width, height)
            self._seq += 1
            self._cond.notify_all()

    def wait_next(self, last_seq: int, timeout_s: float = 5.0):
        """返回 (seq, frame) 或超时返回 (last_seq, None)。"""
        with self._cond:
            self._cond.wait_for(lambda: self._seq > last_seq, timeout=timeout_s)
            if self._seq > last_seq and self._frame is not None:
                return self._seq, self._frame
            return last_seq, None


class MainThreadExecutor:
    """RPC 线程 → Kit 主线程的命令队列。

    Isaac/Kit 的一切操作(建 World/加载/步进)都必须发生在泵 app.update()
    的主线程上; RPC 处理线程只提交作业并等待结果。
    """

    def __init__(self) -> None:
        self._jobs: queue.Queue = queue.Queue()

    def submit(self, fn, timeout_s: float = 900.0):
        done = threading.Event()
        box: dict = {}

        def job() -> None:
            try:
                box["r"] = fn()
            except BaseException as e:  # noqa: BLE001 — 异常必须传回 RPC 线程
                box["e"] = e
            finally:
                done.set()

        self._jobs.put(job)
        if not done.wait(timeout_s):
            raise TimeoutError("main-loop job timed out")
        if "e" in box:
            raise box["e"]
        return box.get("r")

    def drain(self) -> None:
        while True:
            try:
                self._jobs.get_nowait()()
            except queue.Empty:
                return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=50051)
    parser.add_argument("--webrtc", action="store_true")
    parser.add_argument(
        "--record-dir", help="Optional continuous 20 FPS demo recordings"
    )
    parser.add_argument("--kit-args", nargs=argparse.REMAINDER, default=[])
    args = parser.parse_args()

    # SimulationApp 必须先于一切 omni/isaacsim 模块导入
    import os

    from isaacsim import SimulationApp

    app_cfg = {"headless": True, "width": 1280, "height": 720, "multi_gpu": False}
    app_cfg["extra_args"] = args.kit_args
    gpu = os.environ.get("CHEMISTRY_BENCH_SIM_GPU")
    if gpu is not None:
        # Kit indices must agree with any CUDA_VISIBLE_DEVICES mask.
        app_cfg["active_gpu"] = int(gpu)
        app_cfg["physics_gpu"] = int(gpu)
    app = SimulationApp(app_cfg)
    if args.webrtc:
        from isaacsim.core.utils.extensions import enable_extension

        enable_extension("omni.kit.livestream.webrtc")

    import grpc

    print(f"[worker] grpc {grpc.__version__} from {grpc.__file__}", flush=True)
    from chemistry_bench_proto import embodiment_pb2 as pb
    from chemistry_bench_proto import embodiment_pb2_grpc as pb_grpc
    from isaacsim.core.api import World

    from .scene import ChemScene

    mte = MainThreadExecutor()

    class SimBackendServicer(pb_grpc.SimBackendServicer):
        def __init__(self) -> None:
            self.world = None
            self.scene = None
            self.scene_name = ""
            self._loaded_key = None
            self._initial_snapshot = None
            self._t0 = time.monotonic()
            self.frames = FrameBuffer()

        # -------------------------------------------------------------- #

        def Health(self, request, context):
            return pb.HealthReply(
                ok=True, version="isaacsim-4.5.0", scene=self.scene_name
            )

        def LoadScene(self, request, context):
            import yaml

            try:
                return mte.submit(lambda: self._load_scene(request, yaml))
            except Exception as e:  # noqa: BLE001
                import traceback

                traceback.print_exc()
                return pb.Ack(ok=False, error=str(e))

        def _load_scene(self, request, yaml):
            try:
                key = hash(request.scene_yaml + "\x00" + request.embodiment_spec_yaml)
                print("[worker] LoadScene begin", flush=True)
                if self.world is not None and key == self._loaded_key:
                    self.scene.finish_recording()
                    # 同场景重载：快速复位（world.clear 后关节体重建在 4.5 不可靠）
                    self.world.reset()
                    self.scene.post_reset()
                    self.scene.restore(dict(self._initial_snapshot))
                    self.scene.steps(30)
                    if args.record_dir:
                        self.scene.start_recording(args.record_dir)
                    print("[worker] LoadScene done (fast reset)", flush=True)
                    return pb.Ack(ok=True)
                if self.world is not None:
                    return pb.Ack(
                        ok=False,
                        error="scene switch requires worker restart (M2 limitation)",
                    )
                semantics = yaml.safe_load(request.scene_yaml) or {}
                spec = yaml.safe_load(request.embodiment_spec_yaml) or {}
                self.world = World(stage_units_in_meters=1.0)
                self.scene = ChemScene(self.world, semantics, spec)
                self.scene.on_live_frame = self.frames.push
                self.world.reset()
                self.scene.post_reset()
                self.scene.sync_visuals()
                self.scene.steps(60)  # 首帧渲染稳定
                self.scene_name = semantics.get("name", "scene")
                self._loaded_key = key
                self._initial_snapshot = self.scene.snapshot()
                if args.record_dir:
                    self.scene.start_recording(args.record_dir)
                print("[worker] LoadScene done", flush=True)
                return pb.Ack(ok=True)
            except Exception as e:  # noqa: BLE001 — 错误必须过网线
                import traceback

                traceback.print_exc()
                return pb.Ack(ok=False, error=str(e))

        def Observe(self, request, context):
            return mte.submit(self._observe)

        def _observe(self):
            png, w, h = self.scene.rgb_png()
            prop = self.scene.proprio()
            msg = pb.ObservationMsg(
                timestamp=self._now(),
                privileged_json=json.dumps(self.scene.privileged_payload()),
            )
            msg.cameras.append(
                pb.CameraFrameMsg(name="main", png=png, width=w, height=h)
            )
            msg.proprio.joint_positions.extend(prop.get("joint_positions", []))
            msg.proprio.ee_pose.extend(prop.get("ee_pose") or [])
            gw = prop.get("gripper_width")
            if gw is not None:
                msg.proprio.gripper_width = float(gw)
                msg.proprio.has_gripper = True
            return msg

        def Act(self, request, context):
            try:
                return mte.submit(lambda: self._act(request))
            except Exception as e:  # noqa: BLE001
                return pb.ActionResultMsg(ok=False, error=str(e))

        def _act(self, request):
            self.scene.traj_buffer = []
            try:
                if request.kind != "primitive":
                    return pb.ActionResultMsg(
                        ok=False, error="sim_worker M2 only supports primitive actions"
                    )
                params = json.loads(request.params_json or "{}")
                err = None
                detail = {}
                prim = request.primitive
                self.scene.action_label = f"{prim} {json.dumps(params)}"
                self.scene.action_status = "RUNNING"
                print(f"[worker] action begin: {self.scene.action_label}", flush=True)
                if prim == "pick":
                    err = self.scene.pick(str(params.get("object", "")))
                elif prim == "place":
                    err = self.scene.place(params.get("position", [0.5, 0.0, 0.1]))
                elif prim == "pour":
                    err = self.scene.pour(
                        str(params.get("target", "")),
                        float(params.get("volume_ml", 10.0)),
                    )
                elif prim == "open_container":
                    err = self.scene.open_container(str(params.get("object", "")))
                elif prim in ("wait", "observe_closely"):
                    self.scene.steps(30)
                elif prim == "record_finding":
                    text = str(params.get("text", ""))
                    self.scene.record_finding(text)
                    detail = {"recorded": text}
                else:
                    err = "unknown primitive: " + prim
                from chemistry_bench_chemistry import color_of

                beaker = self.scene.vessels.get("beaker")
                self.scene.task_success = bool(
                    beaker and color_of(beaker) == "pink" and self.scene.findings
                )
                self.scene.action_status = (
                    "TASK SUCCESS"
                    if self.scene.task_success
                    else "FAILED"
                    if err
                    else "COMPLETED"
                )
                self.scene.steps(90 if self.scene.task_success else 24)
                if self.scene.task_success:
                    self.scene.finish_recording()
                print(f"[worker] action done: {prim}, error={err}", flush=True)
                if self.scene.traj_buffer:
                    detail["traj_segment"] = [
                        r | {"action": prim} for r in self.scene.traj_buffer
                    ]
                    self.scene.traj_buffer = None
                return pb.ActionResultMsg(
                    ok=err is None, error=err or "", detail_json=json.dumps(detail)
                )
            except Exception as e:  # noqa: BLE001
                import traceback

                traceback.print_exc()
                return pb.ActionResultMsg(ok=False, error=str(e))

        def Reset(self, request, context):
            try:
                return mte.submit(lambda: self._reset(request))
            except Exception as e:  # noqa: BLE001
                return pb.Ack(ok=False, error=str(e))

        def _reset(self, request):
            try:
                payload = json.loads(request.payload_json or "{}")
                self.scene.finish_recording()
                self.world.reset()
                self.scene.post_reset()
                self.scene.restore(payload) if payload else self.scene.sync_visuals()
                self.scene.steps(30)
                if args.record_dir:
                    self.scene.start_recording(args.record_dir)
                return pb.Ack(ok=True)
            except Exception as e:  # noqa: BLE001
                return pb.Ack(ok=False, error=str(e))

        def Step(self, request, context):
            mte.submit(lambda: self.scene.steps(int(request.n)))
            return pb.Ack(ok=True)

        def GetClock(self, request, context):
            return pb.ClockReply(now=self._now())

        def StreamFrames(self, request, context):
            """帧推流：只读 FrameBuffer, 不经 MainThreadExecutor——
            长动作执行期间 steps() 内部旁路捕获持续供帧。"""
            fps = request.fps if request.fps > 0 else 5.0
            min_interval = 1.0 / fps
            seq = 0
            last_sent = 0.0
            while context.is_active():
                seq, frame = self.frames.wait_next(seq, timeout_s=2.0)
                if frame is None:
                    continue  # 空闲期无新帧: 继续等待, 保持流存活
                wait = min_interval - (time.monotonic() - last_sent)
                if wait > 0:
                    time.sleep(wait)
                last_sent = time.monotonic()
                png, w, h = frame
                yield pb.CameraFrameMsg(name="main", png=png, width=w, height=h)

        def _now(self) -> float:
            if self.world is not None:
                try:
                    return float(self.world.current_time)
                except Exception:
                    pass
            return time.monotonic() - self._t0

    # 多 RPC 线程仅为并发流式推帧; 一切 Kit 操作仍经 MainThreadExecutor 串行
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
    servicer = SimBackendServicer()
    pb_grpc.add_SimBackendServicer_to_server(servicer, server)
    bound = server.add_insecure_port(f"127.0.0.1:{args.port}")
    if bound == 0:
        bound = server.add_insecure_port(f"[::1]:{args.port}")
    if bound == 0:
        raise RuntimeError(f"failed to bind gRPC port {args.port}")
    server.start()
    print(f"sim_worker ready on :{bound}", flush=True)
    # 主线程：泵 Kit 事件循环 + 执行 RPC 线程提交的作业（命令队列模式）
    try:
        while app.is_running():
            app.update()
            mte.drain()
            if servicer.scene is not None:
                servicer.scene.capture_live()  # 空闲期也供帧(节流在 scene 内)
    finally:
        try:
            if servicer.scene is not None:
                servicer.scene.finish_recording()
        finally:
            server.stop(2)
            app.close()


if __name__ == "__main__":
    main()
