from chaos_ai.models.cluster_components import ClusterComponents
from chaos_ai.models.config import ConfigFile
from chaos_ai.models.custom_errors import MissingScenarioError, ScenarioInitError
from chaos_ai.utils.rng import rng

from chaos_ai.models.scenario.scenario_dummy import DummyScenario
from chaos_ai.models.scenario.scenario_pod import PodScenario
from chaos_ai.models.scenario.scenario_app_outage import AppOutageScenario
from chaos_ai.models.scenario.scenario_container import ContainerScenario
from chaos_ai.models.scenario.scenario_cpu_hog import NodeCPUHogScenario
from chaos_ai.models.scenario.scenario_memory_hog import NodeMemoryHogScenario
from chaos_ai.models.scenario.scenario_time import TimeScenario

class ScenarioFactory:
    @staticmethod
    def generate_random_scenario(
        config: ConfigFile,
    ):
        scenario_specs = [
            ("pod_scenarios", PodScenario),
            ("application_outages", AppOutageScenario),
            ("container_scenarios", ContainerScenario),
            ("node_cpu_hog", NodeCPUHogScenario),
            ("node_memory_hog", NodeMemoryHogScenario),
            ("time_scenarios", TimeScenario),
        ]

        # Fetch scenarios that are set in config
        candidates = [
            (getattr(config.scenario, attr), factory)
            for attr, factory in scenario_specs
            if getattr(config.scenario, attr).enable
        ]

        if len(candidates) == 0:
            raise MissingScenarioError("No scenarios found. Please provide atleast 1 scenario.")

        try:
            # Unpack Scenario class and create instance
            print("No. of candidates: ", len(candidates))
            _, cls = rng.choice(candidates)
            return cls(cluster_components=config.cluster_components)
        except Exception as error:
            raise ScenarioInitError("Unable to initialize scenario: %s", error)

    @staticmethod
    def create_dummy_scenario():
        return DummyScenario(cluster_components=ClusterComponents())
