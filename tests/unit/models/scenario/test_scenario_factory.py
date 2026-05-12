"""
ScenarioFactory tests
"""

import pytest
from unittest.mock import patch
from krkn_ai.models.scenario.factory import ScenarioFactory
from krkn_ai.models.config import ConfigFile, FitnessFunction, ScenarioConfig
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.custom_errors import MissingScenarioError, ScenarioInitError
from krkn_ai.models.scenario.scenario_dummy import DummyScenario


class TestScenarioFactory:
    """Test ScenarioFactory static methods"""

    def test_list_scenarios_returns_enabled_scenarios(self):
        """Test that list_scenarios returns only enabled scenarios from config"""
        cluster = ClusterComponents(namespaces=[], nodes=[])
        # Use the alias format that matches the Field alias
        config = ConfigFile(
            kubeconfig_file_path="/tmp/kubeconfig",
            fitness_function=FitnessFunction(query="test"),
            scenario=ScenarioConfig(**{"pod-scenarios": {"enable": True}}),
            cluster_components=cluster,
        )
        candidates = ScenarioFactory.list_scenarios(config)
        assert len(candidates) == 1
        assert candidates[0][0] == "pod_scenarios"

    def test_list_scenarios_filters_out_disabled_scenarios(self):
        """Test that list_scenarios excludes disabled scenarios"""
        cluster = ClusterComponents(namespaces=[], nodes=[])
        config = ConfigFile(
            kubeconfig_file_path="/tmp/kubeconfig",
            fitness_function=FitnessFunction(query="test"),
            scenario=ScenarioConfig(**{"pod-scenarios": {"enable": False}}),
            cluster_components=cluster,
        )
        candidates = ScenarioFactory.list_scenarios(config)
        assert len(candidates) == 0

    @patch("krkn_ai.models.scenario.factory.initialize_kubeconfig")
    def test_generate_valid_scenarios_raises_error_when_no_scenarios(
        self, mock_initialize_kubeconfig
    ):
        """Test that generate_valid_scenarios raises MissingScenarioError when no scenarios enabled"""
        cluster = ClusterComponents(namespaces=[], nodes=[])
        config = ConfigFile(
            kubeconfig_file_path="/tmp/kubeconfig",
            fitness_function=FitnessFunction(query="test"),
            scenario=ScenarioConfig(),
            cluster_components=cluster,
        )
        with pytest.raises(MissingScenarioError, match="No scenarios found"):
            ScenarioFactory.generate_valid_scenarios(config)

    @patch("krkn_ai.models.scenario.factory.initialize_kubeconfig")
    def test_generate_valid_scenarios_raises_error_when_no_valid_scenarios(
        self, mock_initialize_kubeconfig
    ):
        """Test that generate_valid_scenarios raises error when all scenarios fail initialization"""
        cluster = ClusterComponents(namespaces=[], nodes=[])
        config = ConfigFile(
            kubeconfig_file_path="/tmp/kubeconfig",
            fitness_function=FitnessFunction(query="test"),
            scenario=ScenarioConfig(**{"pod-scenarios": {"enable": True}}),
            cluster_components=cluster,
        )
        # Mock scenario class to raise exception during initialization
        with patch(
            "krkn_ai.models.scenario.scenario_pod.PodScenario"
        ) as mock_scenario_class:
            from krkn_ai.models.custom_errors import ScenarioParameterInitError

            mock_scenario_class.side_effect = ScenarioParameterInitError(
                "Invalid parameters"
            )
            with pytest.raises(MissingScenarioError, match="No valid scenarios found"):
                ScenarioFactory.generate_valid_scenarios(config)

    def test_generate_random_scenario_creates_scenario_instance(self):
        """Test that generate_random_scenario creates a scenario instance from candidates"""
        cluster = ClusterComponents(namespaces=[], nodes=[])
        config = ConfigFile(
            kubeconfig_file_path="/tmp/kubeconfig",
            fitness_function=FitnessFunction(query="test"),
            cluster_components=cluster,
        )
        candidates = [("dummy_scenarios", DummyScenario)]
        scenario = ScenarioFactory.generate_random_scenario(config, candidates)
        assert isinstance(scenario, DummyScenario)

    def test_generate_random_scenario_raises_error_on_failure(self):
        """Test that generate_random_scenario raises ScenarioInitError on initialization failure"""
        cluster = ClusterComponents(namespaces=[], nodes=[])
        config = ConfigFile(
            kubeconfig_file_path="/tmp/kubeconfig",
            fitness_function=FitnessFunction(query="test"),
            cluster_components=cluster,
        )

        # Create a mock scenario class that raises an exception
        class FailingScenario:
            def __init__(self, **kwargs):
                raise Exception("Initialization failed")

        candidates = [("failing", FailingScenario)]
        with pytest.raises(ScenarioInitError):
            ScenarioFactory.generate_random_scenario(config, candidates)

    def test_create_dummy_scenario_returns_dummy_scenario(self):
        """Test that create_dummy_scenario returns a DummyScenario instance"""
        scenario = ScenarioFactory.create_dummy_scenario()
        assert isinstance(scenario, DummyScenario)
        assert scenario._cluster_components == ClusterComponents()

    def test_generate_random_scenario_error_message_is_string_not_tuple(self):
        """ScenarioInitError message must be a readable string, not a raw tuple"""
        cluster = ClusterComponents(namespaces=[], nodes=[])
        config = ConfigFile(
            kubeconfig_file_path="/tmp/kubeconfig",
            fitness_function=FitnessFunction(query="test"),
            cluster_components=cluster,
        )

        class FailingScenario:
            def __init__(self, **kwargs):
                raise ValueError("cluster components missing")

        candidates = [("failing", FailingScenario)]
        with pytest.raises(ScenarioInitError) as exc_info:
            ScenarioFactory.generate_random_scenario(config, candidates)

        message = str(exc_info.value)
        assert "cluster components missing" in message
        assert message.startswith("(") is False
