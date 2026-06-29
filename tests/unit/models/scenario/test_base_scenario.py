"""
BaseScenario and CompositeScenario model tests
"""

from krkn_ai.models.scenario.base import (
    BaseParameter,
    CompositeScenario,
    CompositeDependency,
)
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.scenario.scenario_dummy import DummyScenario


class TestBaseParameter:
    """Test BaseParameter model"""

    def test_get_name_returns_correct_name_based_on_parameter(self):
        """Test that get_name returns krknctl_name by default and krknhub_name when requested"""
        param = BaseParameter(
            krknctl_name="test-param", krknhub_name="TEST_PARAM", value=42
        )
        # Test default behavior (krknctl_name)
        assert param.get_name() == "test-param"
        assert param.get_name(return_krknhub_name=False) == "test-param"
        # Test with return_krknhub_name=True
        assert param.get_name(return_krknhub_name=True) == "TEST_PARAM"

    def test_get_value_returns_parameter_value(self):
        """Test that get_value returns the parameter value"""
        param = BaseParameter(
            krknctl_name="test", krknhub_name="TEST", value="test-value"
        )
        assert param.get_value() == "test-value"


class TestScenario:
    """Test Scenario model"""

    def test_create_scenario_with_cluster_components(self):
        """Test creating Scenario with cluster components"""
        cluster = ClusterComponents(namespaces=[], nodes=[])
        scenario = DummyScenario(cluster_components=cluster)
        assert scenario.name == "dummy-scenario"
        assert scenario.krknctl_name == "dummy-scenario"
        assert scenario._cluster_components == cluster

    def test_scenario_equality_and_hash(self):
        """Test that Scenario equality and hash compare name and parameter values"""
        cluster = ClusterComponents(namespaces=[], nodes=[])
        scenario1 = DummyScenario(cluster_components=cluster)
        scenario1.end.value = 10
        scenario1.exit_status.value = 0

        scenario2 = DummyScenario(cluster_components=cluster)
        scenario2.end.value = 10
        scenario2.exit_status.value = 0

        scenario3 = DummyScenario(cluster_components=cluster)
        scenario3.end.value = 20
        scenario3.exit_status.value = 0

        # Test equality
        assert scenario1 == scenario2
        assert scenario1 != scenario3
        assert scenario1 != "not-a-scenario"

        # Test hash (same scenarios should have same hash)
        assert hash(scenario1) == hash(scenario2)

        # Test string representation (used in logging)
        str_repr = str(scenario1)
        assert "10" in str_repr
        assert "0" in str_repr


class TestCompositeScenario:
    """Test CompositeScenario model"""

    def test_create_composite_scenario_with_two_scenarios(self):
        """Test creating CompositeScenario with two scenarios"""
        cluster = ClusterComponents(namespaces=[], nodes=[])
        scenario_a = DummyScenario(cluster_components=cluster)
        scenario_b = DummyScenario(cluster_components=cluster)

        composite = CompositeScenario(
            name="composite-test",
            scenario_a=scenario_a,
            scenario_b=scenario_b,
            dependency=CompositeDependency.NONE,
        )
        assert composite.name == "composite-test"
        assert composite.scenario_a == scenario_a
        assert composite.scenario_b == scenario_b
        assert composite.dependency == CompositeDependency.NONE
        assert composite.krknctl_name == ""
        assert composite.krknhub_image == ""

    def test_composite_scenario_equality_and_hash(self):
        """Test CompositeScenario equality and hash based on scenarios"""
        cluster = ClusterComponents(namespaces=[], nodes=[])
        scenario_a = DummyScenario(cluster_components=cluster)
        scenario_a.end.value = 10
        scenario_b = DummyScenario(cluster_components=cluster)
        scenario_b.end.value = 20  # Different value to make scenarios different

        composite1 = CompositeScenario(
            name="composite1",
            scenario_a=scenario_a,
            scenario_b=scenario_b,
            dependency=CompositeDependency.NONE,
        )
        composite2 = CompositeScenario(
            name="composite2",
            scenario_a=scenario_a,
            scenario_b=scenario_b,
            dependency=CompositeDependency.A_ON_B,
        )
        composite3 = CompositeScenario(
            name="composite1",
            scenario_a=scenario_b,
            scenario_b=scenario_a,
            dependency=CompositeDependency.NONE,
        )

        # Test equality
        assert composite1 == composite1
        assert composite1 != "not-a-composite"

        # Different dependency changes the execution graph, so identity must differ (#380)
        assert hash(composite1) != hash(composite2)
        # Different scenario order should have different hash
        assert hash(composite1) != hash(composite3)

        # Test string representation (used in logging)
        assert str(composite1) == "composite1"
