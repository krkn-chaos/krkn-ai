from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class WorkloadResult:
    """
    Result of a single workload generation iteration.

    Attributes:
        success: True if workload completed successfully
        response_time: Time taken in seconds (-1 if not available)
        status_code: HTTP status code or -1 if not applicable (e.g. gRPC)
        error: Error message if workload failed, None otherwise
    """

    success: bool
    response_time: float
    status_code: int = -1
    error: Optional[str] = None


class BaseWorkloadGenerator(ABC):
    """
    Abstract base class for custom workload generators.

    To create a custom workload:
    1. Extend this class
    2. Implement the generate() method
    3. Point to your class in krkn-ai.yaml under health_checks

    Example:
        class MyWorkload(BaseWorkloadGenerator):
            def generate(self) -> WorkloadResult:
                # your custom load logic here
                return WorkloadResult(success=True, response_time=0.1)

    YAML config:
        health_checks:
          applications:
          - name: my-app
            url: "http://my-app/health"
            workload:
              generator: "my_package.my_module.MyWorkload"
              config:
                key: value
    """

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def generate(self) -> WorkloadResult:
        """
        Run one iteration of the workload.
        This is called in a loop during the chaos scenario.
        Must return a WorkloadResult.
        """
        ...

    def setup(self) -> None:
        """
        Called once before the workload loop starts.
        Use this to initialize connections, clients etc.
        Override if needed.
        """
        pass

    def teardown(self) -> None:
        """
        Called once after the workload loop ends.
        Use this to close connections, clean up resources etc.
        Override if needed.
        """
        pass
