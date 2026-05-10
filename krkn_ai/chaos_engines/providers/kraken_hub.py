from typing import Optional, Tuple, Any
from krkn_ai.chaos_engines.base import ChaosProvider
from krkn_ai.models.scenario.base import BaseScenario, Scenario
from krkn_ai.utils import run_shell
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)

PODMAN_TEMPLATE = 'podman run -e PUBLISH_KRAKEN_STATUS="False" -e TELEMETRY_PROMETHEUS_BACKUP="False" -e WAIT_DURATION={wait_duration} {env_list} {{es_env_list}} --net=host -v {kubeconfig}:/home/krkn/.kube/config:Z {image}'
PODMAN_ES_TEMPLATE = ' -e ENABLE_ES="True" -e ES_SERVER="{server}" -e ES_PORT="{port}" -e ES_USERNAME="{username}" -e ES_PASSWORD="{password}" -e ES_VERIFY_CERTS="{verify_certs}" '


class KrakenHubProvider(ChaosProvider):
    def __init__(self, kubeconfig: str, wait_duration: int, output_dir: str = "/tmp"):
        super().__init__(kubeconfig, wait_duration, output_dir)

    def get_name(self) -> str:
        return "kraken-hub"

    def validate_availability(self) -> bool:
        _, returncode = run_shell("podman --version", do_not_log=True)
        return returncode == 0

    def run(
        self, scenario: BaseScenario, generation_id: int, elastic_config: Any = None
    ) -> Tuple[str, int, Optional[str], str]:
        if isinstance(scenario, Scenario):
            command = self._generate_command(scenario)
        else:
            raise NotImplementedError(
                "Composite scenarios are not supported by KrakenHubProvider"
            )

        # Patch ES config
        command = self._process_es_env_string(command, elastic_config)

        log, returncode = run_shell(command)
        return log, returncode, None, command

    def _generate_command(self, scenario: Scenario) -> str:
        env_list = ""
        for parameter in scenario.parameters:
            env_list += f' -e {parameter.get_name(return_krknhub_name=True)}="{parameter.get_value()}" '

        return PODMAN_TEMPLATE.format(
            wait_duration=self.wait_duration,
            env_list=env_list,
            kubeconfig=self.kubeconfig,
            image=scenario.krknhub_image,
        )

    def _process_es_env_string(self, command: str, elastic_config: Any):
        if not elastic_config or not elastic_config.enable:
            return command.replace("{es_env_list}", "")

        es_list = PODMAN_ES_TEMPLATE.format(
            server=elastic_config.server,
            port=elastic_config.port,
            username=elastic_config.username,
            password=elastic_config.password,
            verify_certs=elastic_config.verify_certs,
        )
        return command.replace("{es_env_list}", es_list)
