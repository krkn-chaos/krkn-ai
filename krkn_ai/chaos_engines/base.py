from abc import ABC, abstractmethod
from typing import Optional, Tuple, Any
from krkn_ai.models.scenario.base import BaseScenario


class ChaosProvider(ABC):
    """
    Abstract base class for all chaos providers.
    A provider is responsible for executing a chaos scenario and returning the result.
    """

    def __init__(
        self, kubeconfig: str = "", wait_duration: int = 0, output_dir: str = ""
    ):
        self.kubeconfig = kubeconfig
        self.wait_duration = wait_duration
        self.output_dir = output_dir

    @abstractmethod
    def validate_availability(self) -> bool:
        """
        Check if the provider's dependencies (e.g., binaries, API access) are available.
        """
        pass

    @abstractmethod
    def run(
        self, scenario: BaseScenario, generation_id: int, elastic_config: Any = None
    ) -> Tuple[str, int, Optional[str], str]:
        """
        Execute the given chaos scenario.
        Returns a tuple of (log, returncode, run_uuid, command).
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """
        Return the unique name of the provider.
        """
        pass
