from typing import Optional, Tuple, Any
from krkn_ai.chaos_engines.base import ChaosProvider
from krkn_ai.models.scenario.base import BaseScenario
from krkn_ai.utils import run_shell


class ShellProvider(ChaosProvider):
    def __init__(
        self, kubeconfig: str = "", wait_duration: int = 0, output_dir: str = ""
    ):
        super().__init__(kubeconfig, wait_duration, output_dir)

    """
    A provider that runs arbitrary shell commands.
    Useful for custom chaos scripts not supported by Kraken.
    """

    def get_name(self) -> str:
        return "shell"

    def validate_availability(self) -> bool:
        # Shell is always available
        return True

    def run(
        self, scenario: BaseScenario, generation_id: int, elastic_config: Any = None
    ) -> Tuple[str, int, Optional[str], str]:
        # This assumes the scenario has a way to provide a shell command
        # For now, we'll try to get it from a 'command' attribute or metadata
        command = getattr(scenario, "command", None)
        if not command:
            command = f"echo 'No command defined for scenario {scenario}'"

        log, returncode = run_shell(command)
        return log, returncode, None, command
