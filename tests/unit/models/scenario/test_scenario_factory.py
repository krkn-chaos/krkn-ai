"""
ScenarioFactory tests
"""

import pytest
from unittest.mock import patch
from krkn_ai.models.scenario.factory import ScenarioFactory
from krkn_ai.models.config import ConfigFile, FitnessFunction, ScenarioConfig
from krkn_ai.models.cluster_components import (
    ClusterComponents,
    Namespace,
    Pod,
    Node,
)
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

    def test_scenario_config_accepts_underscore_names(self):
        """ScenarioConfig accepts underscore field names (populate_by_name)."""
        cluster = ClusterComponents(namespaces=[], nodes=[])
        config = ConfigFile(
            kubeconfig_file_path="/tmp/kubeconfig",
            fitness_function=FitnessFunction(query="test"),
            scenario=ScenarioConfig(pod_scenarios={"enable": True}),
            cluster_components=cluster,
        )
        candidates = ScenarioFactory.list_scenarios(config)
        assert len(candidates) == 1
        assert candidates[0][0] == "pod_scenarios"

    def test_scenario_config_accepts_both_naming_conventions(self):
        """ScenarioConfig accepts hyphen and underscore names in the same call."""
        cluster = ClusterComponents(namespaces=[], nodes=[])
        config = ConfigFile(
            kubeconfig_file_path="/tmp/kubeconfig",
            fitness_function=FitnessFunction(query="test"),
            scenario=ScenarioConfig(
                **{"pod-scenarios": {"enable": True}},
                node_cpu_hog={"enable": True},
            ),
            cluster_components=cluster,
        )
        candidates = ScenarioFactory.list_scenarios(config)
        names = {name for name, _ in candidates}
        assert "pod_scenarios" in names
        assert "node_cpu_hog" in names

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


class TestRecommendEnabledScenarios:
    """Test ScenarioFactory.recommend_enabled_scenarios"""

    @patch("krkn_ai.models.scenario.factory.initialize_kubeconfig")
    def test_node_scenarios_depend_on_nodes(self, _mock_init):
        """Node scenarios are recommended only with nodes."""
        with_nodes = ScenarioFactory.recommend_enabled_scenarios(
            ClusterComponents(
                namespaces=[Namespace(name="shop", pods=[Pod(name="redis")])],
                nodes=[Node(name="n1")],
            ),
            "/tmp/kubeconfig",
        )
        without_nodes = ScenarioFactory.recommend_enabled_scenarios(
            ClusterComponents(
                namespaces=[Namespace(name="shop", pods=[Pod(name="redis")])]
            ),
            "/tmp/kubeconfig",
        )
        assert with_nodes["node_cpu_hog"] is True
        assert without_nodes["node_cpu_hog"] is False

    @patch("krkn_ai.models.scenario.factory.initialize_kubeconfig")
    def test_namespace_scenarios_depend_on_pods(self, _mock_init):
        """Pod scenarios are recommended only with pods."""
        with_pods = ScenarioFactory.recommend_enabled_scenarios(
            ClusterComponents(
                namespaces=[Namespace(name="shop", pods=[Pod(name="redis")])],
                nodes=[Node(name="n1")],
            ),
            "/tmp/kubeconfig",
        )
        nodes_only = ScenarioFactory.recommend_enabled_scenarios(
            ClusterComponents(nodes=[Node(name="n1")]), "/tmp/kubeconfig"
        )
        assert with_pods["dns_outage"] is True
        assert nodes_only["dns_outage"] is False

    @patch("krkn_ai.models.scenario.factory.initialize_kubeconfig")
    def test_all_disabled_for_empty_cluster(self, _mock_init):
        """Empty cluster disables all scenarios."""
        result = ScenarioFactory.recommend_enabled_scenarios(
            ClusterComponents(), "/tmp/kubeconfig"
        )
        assert isinstance(result, dict)
        assert not any(result.values())

    @patch(
        "krkn_ai.models.scenario.factory.ScenarioFactory.generate_valid_scenarios",
        side_effect=RuntimeError("boom"),
    )
    def test_all_disabled_on_unexpected_error(self, _mock_gen):
        """Errors return all-disabled dict instead of raising."""
        cluster = ClusterComponents(namespaces=[Namespace(name="shop")])
        result = ScenarioFactory.recommend_enabled_scenarios(cluster, "/tmp/kubeconfig")
        assert isinstance(result, dict)
        assert not any(result.values())
