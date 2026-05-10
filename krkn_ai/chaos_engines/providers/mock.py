import time
import uuid
from typing import Optional, Tuple, Any
from krkn_ai.chaos_engines.base import ChaosProvider
from krkn_ai.models.scenario.base import BaseScenario
from krkn_ai.utils.rng import rng


class MockProvider(ChaosProvider):
    def __init__(
        self, kubeconfig: str = "", wait_duration: int = 0, output_dir: str = ""
    ):
        super().__init__(kubeconfig, wait_duration, output_dir)

    """
    A mock provider for testing purposes.
    Simulates a chaos experiment without actually running anything.
    """

    def get_name(self) -> str:
        return "mock"

    def validate_availability(self) -> bool:
        return True

    def run(
        self, scenario: BaseScenario, generation_id: int, elastic_config: Any = None
    ) -> Tuple[str, int, Optional[str], str]:
        # Simulate some work
        time.sleep(rng.uniform(0.1, 0.5))

        # Simulate a successful run
        run_uuid = str(uuid.uuid4())
        log = f"Mock run for scenario {scenario} complete. UUID: {run_uuid}"
        returncode = 0
        command = f"mock run {scenario}"

        return log, returncode, run_uuid, command
