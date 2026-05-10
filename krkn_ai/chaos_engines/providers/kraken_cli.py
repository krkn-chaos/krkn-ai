import os
import json
import tempfile
from typing import Optional, Tuple, Any
from krkn_ai.chaos_engines.base import ChaosProvider
from krkn_ai.models.scenario.base import (
    BaseScenario,
    Scenario,
    CompositeScenario,
    CompositeDependency,
)
from krkn_ai.models.scenario.factory import ScenarioFactory
from krkn_ai.utils import run_shell
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)

KRKNCTL_TEMPLATE = "krknctl run {name} --telemetry-prometheus-backup False --wait-duration {wait_duration} --kubeconfig {kubeconfig} {env_list} {{es_env_list}}"
KRKNCTL_ES_TEMPLATE = ' --enable-es True --es-server "{server}" --es-port "{port}" --es-username "{username}" --es-password "{password}" --es-verify-certs "{verify_certs}" '
KRKNCTL_GRAPH_RUN_TEMPLATE = "krknctl graph run {path} --kubeconfig {kubeconfig}"


class KrakenCliProvider(ChaosProvider):
    def __init__(self, kubeconfig: str, wait_duration: int, output_dir: str = "/tmp"):
        super().__init__(kubeconfig, wait_duration, output_dir)

    def get_name(self) -> str:
        return "kraken-cli"

    def validate_availability(self) -> bool:
        _, returncode = run_shell("krknctl --version", do_not_log=True)
        return returncode == 0

    def run(
        self, scenario: BaseScenario, generation_id: int, elastic_config: Any = None
    ) -> Tuple[str, int, Optional[str], str]:
        if isinstance(scenario, CompositeScenario):
            command = self._generate_graph_command(scenario)
        elif isinstance(scenario, Scenario):
            command = self._generate_command(scenario)
        else:
            raise NotImplementedError(f"Unsupported scenario type: {type(scenario)}")

        # Patch ES config
        command = self._process_es_env_string(command, elastic_config)

        log, returncode = run_shell(command)
        return log, returncode, None, command

    def _generate_command(self, scenario: Scenario) -> str:
        env_list = ""
        for parameter in scenario.parameters:
            param_name = parameter.get_name(return_krknhub_name=False)
            env_list += f'--{param_name} "{parameter.get_value()}" '

        return KRKNCTL_TEMPLATE.format(
            wait_duration=self.wait_duration,
            env_list=env_list,
            kubeconfig=self.kubeconfig,
            name=scenario.krknctl_name,
        )

    def _generate_graph_command(self, scenario: CompositeScenario) -> str:
        graph_dir = os.path.join(self.output_dir, "graphs")
        os.makedirs(graph_dir, exist_ok=True)

        scenario_json = self._expand_composite_json(scenario)
        with tempfile.NamedTemporaryFile(
            suffix=".json", dir=graph_dir, delete=False, mode="w", encoding="utf-8"
        ) as f:
            json.dump(scenario_json, f, ensure_ascii=False, indent=4)
            path = f.name

        return KRKNCTL_GRAPH_RUN_TEMPLATE.format(path=path, kubeconfig=self.kubeconfig)

    def _expand_composite_json(
        self, scenario: CompositeScenario, root: str = "$", depends_on: str = None
    ):
        result = {}
        key_root, key_a, key_b = root, root + "l", root + "r"

        if scenario.dependency == CompositeDependency.NONE:
            result[key_root] = self._gen_scenario_json(
                ScenarioFactory.create_dummy_scenario(), depends_on
            )

        # Scenario A
        dep_a = (
            key_b
            if scenario.dependency == CompositeDependency.A_ON_B
            else (
                depends_on
                if scenario.dependency
                in [CompositeDependency.B_ON_A, CompositeDependency.NONE]
                else None
            )
        )
        if isinstance(scenario.scenario_a, CompositeScenario):
            result.update(
                self._expand_composite_json(scenario.scenario_a, key_a, dep_a)
            )
        else:
            result[key_a] = self._gen_scenario_json(scenario.scenario_a, dep_a)

        # Scenario B
        dep_b = (
            depends_on
            if scenario.dependency == CompositeDependency.A_ON_B
            else (
                key_b if scenario.dependency == CompositeDependency.B_ON_A else key_root
            )
        )
        if isinstance(scenario.scenario_b, CompositeScenario):
            result.update(
                self._expand_composite_json(scenario.scenario_b, key_b, dep_b)
            )
        else:
            result[key_b] = self._gen_scenario_json(scenario.scenario_b, dep_b)

        return result

    def _gen_scenario_json(self, scenario: Scenario, depends_on: str = None):
        env = {p.get_name(True): str(p.get_value()) for p in scenario.parameters}
        res = {
            "image": scenario.krknhub_image,
            "name": scenario.krknctl_name,
            "env": env,
        }
        if depends_on:
            res["depends_on"] = depends_on
        return res

    def _process_es_env_string(self, command: str, elastic_config: Any):
        if not elastic_config or not elastic_config.enable:
            return command.replace("{es_env_list}", "")

        es_list = KRKNCTL_ES_TEMPLATE.format(
            server=elastic_config.server,
            port=elastic_config.port,
            username=elastic_config.username,
            password=elastic_config.password,
            verify_certs=elastic_config.verify_certs,
        )
        return command.replace("{es_env_list}", es_list)
