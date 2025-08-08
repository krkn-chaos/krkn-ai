import random
from chaos_ai.models.config import ConfigFile
from chaos_ai.models.custom_errors import MissingScenarioError, ScenarioInitError
from chaos_ai.models.scenario.base import Scenario
from chaos_ai.models.scenario.parameters import DummyParameter

from chaos_ai.models.scenario.scenario_pod import PodScenario
from chaos_ai.models.scenario.scenario_app_outage import AppOutageScenario

class ScenarioFactory:
    @staticmethod
    def generate_random_scenario(
        config: ConfigFile,
    ):
        scenario_specs = [
            ("pod_scenarios", PodScenario),
            ("application_outages", AppOutageScenario),
            ("container_scenarios", None),
            ("node_cpu_hog", None),
            ("node_memory_hog", None),
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
            _, cls = random.choice(candidates)
            return cls(cluster_components=config.cluster_components)
        except Exception as error:
            raise ScenarioInitError("Unable to initialize scenario: %s", error)

    @staticmethod
    def create_dummy_scenario():
        return Scenario(
            name="dummy-scenario",
            parameters=[
                DummyParameter(name="END", value=10),
                DummyParameter(name="EXIT_STATUS", value=0),
            ]
        )
