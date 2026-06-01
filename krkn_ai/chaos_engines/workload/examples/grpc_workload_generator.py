"""
Example: Custom gRPC workload generator.

This is an example showing how to implement a custom workload generator
for gRPC endpoints. Copy this file and adapt generate() for your use case.

To use it, point to your class in krkn-ai.yaml:

    health_checks:
      applications:
      - name: my-grpc-app
        url: "grpc://my-service:50051"
        workload:
          generator: "krkn_ai.chaos_engines.workload.examples.grpc_workload_generator.GrpcWorkloadGenerator"
          config:
            host: "my-service"
            port: 50051
            timeout: 5

Requirements:
    pip install grpcio
"""

import time
from krkn_ai.chaos_engines.workload.base_workload_generator import (
    BaseWorkloadGenerator,
    WorkloadResult,
)


class GrpcWorkloadGenerator(BaseWorkloadGenerator):
    """
    Example custom workload generator for gRPC endpoints.

    Config keys:
        host (str): gRPC server hostname
        port (int): gRPC server port
        timeout (float): Call timeout in seconds (default: 5)
    """

    def setup(self) -> None:
        """
        Initialize your gRPC channel here.
        Called once before the workload loop starts.

        Example:
            import grpc
            self.channel = grpc.insecure_channel(
                f"{self.config['host']}:{self.config['port']}"
            )
            self.stub = your_pb2_grpc.YourServiceStub(self.channel)
        """
        pass

    def generate(self) -> WorkloadResult:
        """
        Make a single gRPC call.
        Replace the body with your actual stub call.
        """
        start = time.monotonic()
        try:
            # Replace this with your actual gRPC call, e.g:
            # response = self.stub.Check(your_pb2.HealthCheckRequest())
            # success = response.status == "SERVING"
            elapsed = time.monotonic() - start
            return WorkloadResult(
                success=True,
                response_time=elapsed,
            )
        except Exception as e:
            elapsed = time.monotonic() - start
            return WorkloadResult(
                success=False,
                response_time=elapsed,
                error=str(e),
            )

    def teardown(self) -> None:
        """
        Close your gRPC channel here.
        Called once after the workload loop ends.

        Example:
            self.channel.close()
        """
        pass
