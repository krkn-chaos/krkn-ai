from typing import List, Tuple
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.config import ConfigFile
from krkn_ai.models.custom_errors import MissingScenarioError, ScenarioInitError
from krkn_ai.models.scenario.base import Scenario
from krkn_ai.utils.rng import rng

from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.scenario.scenario_pod import PodScenario
from krkn_ai.models.scenario.scenario_app_outage import AppOutageScenario
from krkn_ai.models.scenario.scenario_container import ContainerScenario
from krkn_ai.models.scenario.scenario_cpu_hog import NodeCPUHogScenario
from krkn_ai.models.scenario.scenario_memory_hog import NodeMemoryHogScenario
from krkn_ai.models.scenario.scenario_time import TimeScenario

scenario_specs = [
    ("pod_scenarios", PodScenario),
    ("application_outages", AppOutageScenario),
    ("container_scenarios", ContainerScenario),
    ("node_cpu_hog", NodeCPUHogScenario),
    ("node_memory_hog", NodeMemoryHogScenario),
    ("time_scenarios", TimeScenario),
]

class ScenarioFactory:
    @staticmethod
    def list_scenarios(config: ConfigFile) -> List[Tuple[str, Scenario]]:
        # List all scenarios that are set in config
        candidates = [
            (getattr(config.scenario, attr), factory)
            for attr, factory in scenario_specs
            if getattr(config.scenario, attr).enable
        ]
        return candidates
    
    @staticmethod
    def generate_random_scenario(
        config: ConfigFile,
    ):
        # List all scenarios that are set in config
        candidates = ScenarioFactory.list_scenarios(config)

        if len(candidates) == 0:
            raise MissingScenarioError("No scenarios found. Please provide atleast 1 scenario.")

        try:
            # Unpack Scenario class and create instance
            _, cls = rng.choice(candidates)
            return cls(cluster_components=config.cluster_components)
        except Exception as error:
            raise ScenarioInitError("Unable to initialize scenario: %s", error)

    @staticmethod
    def create_dummy_scenario():
        return DummyScenario(cluster_components=ClusterComponents())
