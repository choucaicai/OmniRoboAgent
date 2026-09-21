"""Optional loopback protocol test; not an Isaac Sim integration test."""

import json
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
from PIL import Image

from omniroboagent.environments.benchmarks.chemistry_bench import (
    ChemistryBenchEnvironment,
)
from omniroboagent.environments.benchmarks.chemistry_bench.environment import TASK_ID


def test_real_grpc_serialization_and_reset():
    grpc = pytest.importorskip("grpc")
    pb = pytest.importorskip("chemistry_bench_proto.embodiment_pb2")
    services = pytest.importorskip("chemistry_bench_proto.embodiment_pb2_grpc")
    assert pb.DESCRIPTOR.package == "chemistry_bench"
    stream = BytesIO()
    Image.new("RGB", (16, 16), "white").save(stream, format="PNG")

    class Worker(services.SimBackendServicer):
        def Health(self, request, context):
            return pb.HealthReply(ok=True, version="test-only")

        def LoadScene(self, request, context):
            assert "naoh_bottle" in request.scene_yaml
            assert "dof: 7" in request.embodiment_spec_yaml
            self.volume = 0
            self.findings = []
            return pb.Ack(ok=True)

        def Act(self, request, context):
            assert request.kind == "primitive"
            params = json.loads(request.params_json)
            if request.primitive == "pour":
                self.volume += params["volume_ml"]
            elif request.primitive == "record_finding":
                self.findings.append(params["text"])
            return pb.ActionResultMsg(ok=True)

        def Observe(self, request, context):
            return pb.ObservationMsg(
                timestamp=1,
                cameras=[
                    pb.CameraFrameMsg(
                        name="main", width=16, height=16, png=stream.getvalue()
                    )
                ],
                privileged_json=json.dumps(
                    {
                        "vessels": {
                            "beaker": {
                                "color": "pink" if self.volume > 50 else "colorless"
                            }
                        },
                        "findings": self.findings,
                    }
                ),
            )

    executor = ThreadPoolExecutor(max_workers=1)
    server = grpc.server(executor)
    services.add_SimBackendServicer_to_server(Worker(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    assert port != 0
    server.start()
    env = ChemistryBenchEnvironment(address=f"127.0.0.1:{port}", timeout_seconds=5)
    try:
        env.reset(TASK_ID)
        assert not env.execute("record finding: beaker is pink")["task_success"]
        assert not env.execute("pour 30 ml into beaker")["task_success"]
        assert env.execute("pour 30 ml into beaker")["task_success"]
        env.reset(TASK_ID)
        assert not env.execute("record finding: beaker is pink")["task_success"]
    finally:
        env.close()
        server.stop(0).wait()
        executor.shutdown()
