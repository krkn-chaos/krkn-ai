"""
Crossover operation tests
"""

from unittest.mock import patch

from krkn_ai.models.scenario.base import CompositeScenario, CompositeDependency
from krkn_ai.models.scenario.scenario_dns_outage import DnsOutageScenario
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.cluster_components import (
    ClusterComponents,
    Namespace,
    OwnerReference,
    Pod,
)


class TestCrossover:
    """Test crossover functionality"""

    def test_crossover_simple_scenarios(self, genetic_algorithm):
        """Test crossover between two simple scenarios"""
        scenario_a = DummyScenario(cluster_components=ClusterComponents())
        scenario_b = DummyScenario(cluster_components=ClusterComponents())

        # Set crossover rate to 1.0 to ensure crossover happens
        genetic_algorithm.algo_config.crossover_rate = 1.0

        child1, child2 = genetic_algorithm.crossover(scenario_a, scenario_b)

        # Should return two scenarios (may be same objects if no common params)
        assert child1 is not None
        assert child2 is not None

    def test_crossover_composite_scenarios(self, genetic_algorithm):
        """Test crossover between two composite scenarios swaps branches"""
        scenario_a1 = DummyScenario(cluster_components=ClusterComponents())
        scenario_b1 = DummyScenario(cluster_components=ClusterComponents())
        scenario_a2 = DummyScenario(cluster_components=ClusterComponents())
        scenario_b2 = DummyScenario(cluster_components=ClusterComponents())

        composite_a = CompositeScenario(
            name="composite-a",
            scenario_a=scenario_a1,
            scenario_b=scenario_b1,
            dependency=CompositeDependency.NONE,
        )
        composite_b = CompositeScenario(
            name="composite-b",
            scenario_a=scenario_a2,
            scenario_b=scenario_b2,
            dependency=CompositeDependency.NONE,
        )

        # Store original scenario_b references
        original_a_b = composite_a.scenario_b
        original_b_b = composite_b.scenario_b

        child1, child2 = genetic_algorithm.crossover(composite_a, composite_b)

        # Should swap scenario_b branches (type check is implicit in branch access)
        assert child1.scenario_b == original_b_b
        assert child2.scenario_b == original_a_b

    def test_crossover_mixed_scenarios(self, genetic_algorithm):
        """Test crossover between composite and simple scenario replaces branch"""
        simple_scenario_a = DummyScenario(cluster_components=ClusterComponents())
        simple_scenario_b = DummyScenario(cluster_components=ClusterComponents())
        simple_scenario_c = DummyScenario(cluster_components=ClusterComponents())

        composite_scenario = CompositeScenario(
            name="composite",
            scenario_a=simple_scenario_a,
            scenario_b=simple_scenario_b,
            dependency=CompositeDependency.NONE,
        )

        # Store original scenario_b
        original_composite_b = composite_scenario.scenario_b

        child1, child2 = genetic_algorithm.crossover(
            composite_scenario, simple_scenario_c
        )

        # Composite scenario's scenario_b should be replaced with simple_scenario_c
        assert isinstance(child1, CompositeScenario)
        assert child1.scenario_b == simple_scenario_c
        # child2 should be the original scenario_b
        assert child2 == original_composite_b

    def test_crossover_carries_pod_name_metadata(self, genetic_algorithm):
        """Swapping a PodNameParameter must move its namespace and owner too"""
        billing = Namespace(
            name="billing",
            pods=[
                Pod(
                    name="api-abc",
                    owner=OwnerReference(kind="ReplicaSet", name="api-rs"),
                )
            ],
        )
        shipping = Namespace(
            name="shipping",
            pods=[
                Pod(
                    name="worker-xyz",
                    owner=OwnerReference(kind="StatefulSet", name="worker"),
                )
            ],
        )
        scenario_a = DnsOutageScenario(
            cluster_components=ClusterComponents(namespaces=[billing])
        )
        scenario_b = DnsOutageScenario(
            cluster_components=ClusterComponents(namespaces=[shipping])
        )
        genetic_algorithm.algo_config.crossover_rate = 1.0

        child_a, child_b = genetic_algorithm.crossover(scenario_a, scenario_b)

        assert child_a.pod_name.value == "worker-xyz"
        assert child_a.pod_name._namespace == "shipping"
        assert child_a.pod_name._owner_kind == "StatefulSet"
        assert child_a.pod_name._owner_name == "worker"

        assert child_b.pod_name.value == "api-abc"
        assert child_b.pod_name._namespace == "billing"
        assert child_b.pod_name._owner_kind == "ReplicaSet"
        assert child_b.pod_name._owner_name == "api-rs"

    def test_crossover_pod_name_resolves_in_swapped_namespace(self, genetic_algorithm):
        """After crossover the lazy resolution uses the swapped owner, not the stale one"""
        billing = Namespace(
            name="billing",
            pods=[
                Pod(name="api-abc", owner=OwnerReference(kind="Deployment", name="api"))
            ],
        )
        shipping = Namespace(
            name="shipping",
            pods=[
                Pod(
                    name="worker-xyz",
                    owner=OwnerReference(kind="Deployment", name="worker"),
                )
            ],
        )
        scenario_a = DnsOutageScenario(
            cluster_components=ClusterComponents(namespaces=[billing])
        )
        scenario_b = DnsOutageScenario(
            cluster_components=ClusterComponents(namespaces=[shipping])
        )
        genetic_algorithm.algo_config.crossover_rate = 1.0

        child_a, _ = genetic_algorithm.crossover(scenario_a, scenario_b)

        with patch("krkn_ai.cluster.resolve_pod_name") as mock_resolve:
            mock_resolve.return_value = "worker-new"
            assert child_a.pod_name.get_value() == "worker-new"
            mock_resolve.assert_called_once_with(
                "shipping", "worker-xyz", "Deployment", "worker"
            )
