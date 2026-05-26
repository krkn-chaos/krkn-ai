"""
Crossover operation tests
"""

from krkn_ai.models.scenario.base import CompositeScenario, CompositeDependency
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.cluster_components import ClusterComponents


class TestCrossover:
    """Test crossover functionality"""

    def test_crossover_simple_scenarios(self, genetic_algorithm):
        """Test crossover between two simple scenarios"""
        scenario_a = DummyScenario(cluster_components=ClusterComponents())
        scenario_b = DummyScenario(cluster_components=ClusterComponents())

        # Set crossover rate to 1.0 to ensure crossover happens
        genetic_algorithm.config.crossover_rate = 1.0

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

    def test_crossover_pod_name_metadata(self, genetic_algorithm):
        """Test that crossover correctly swaps PodNameParameter private attributes along with value"""
        from krkn_ai.models.scenario.base import Scenario
        from krkn_ai.models.scenario.parameters import PodNameParameter

        class TestPodNameScenario(Scenario):
            name: str = "test-pod-name-scenario"
            krknctl_name: str = "test-pod-name"
            krknhub_image: str = "test"
            pod_name: PodNameParameter = PodNameParameter()

            @property
            def parameters(self):
                return [self.pod_name]

        scenario_a = TestPodNameScenario(cluster_components=ClusterComponents())
        scenario_b = TestPodNameScenario(cluster_components=ClusterComponents())

        # Set distinct values and private attributes on scenario_a
        scenario_a.pod_name.value = "pod-a"
        scenario_a.pod_name._namespace = "ns-a"
        scenario_a.pod_name._owner_kind = "ReplicaSet"
        scenario_a.pod_name._owner_name = "owner-a"

        # Set distinct values and private attributes on scenario_b
        scenario_b.pod_name.value = "pod-b"
        scenario_b.pod_name._namespace = "ns-b"
        scenario_b.pod_name._owner_kind = "StatefulSet"
        scenario_b.pod_name._owner_name = "owner-b"

        # Force crossover to happen
        genetic_algorithm.config.crossover_rate = 1.0

        child1, child2 = genetic_algorithm.crossover(scenario_a, scenario_b)

        # Assert states have been swapped correctly
        assert child1.pod_name.value == "pod-b"
        assert child1.pod_name._namespace == "ns-b"
        assert child1.pod_name._owner_kind == "StatefulSet"
        assert child1.pod_name._owner_name == "owner-b"

        assert child2.pod_name.value == "pod-a"
        assert child2.pod_name._namespace == "ns-a"
        assert child2.pod_name._owner_kind == "ReplicaSet"
        assert child2.pod_name._owner_name == "owner-a"

