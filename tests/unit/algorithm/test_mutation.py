"""
Mutation operation tests
"""

from typing import ClassVar, List

from krkn_ai.models.scenario.base import CompositeScenario, CompositeDependency
from krkn_ai.models.scenario.parameters import DummyEndParameter
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.cluster_components import ClusterComponents, Namespace, Node


class SourceScenario(DummyScenario):
    name: str = "source-scenario"
    krknctl_name: str = "source-scenario"
    krknhub_image: str = "source-scenario"


class RecordingScenario(DummyScenario):
    name: str = "recording-scenario"
    krknctl_name: str = "recording-scenario"
    krknhub_image: str = "recording-scenario"

    received_components: ClassVar[List[ClusterComponents]] = []

    def __init__(self, **data):
        super().__init__(**data)
        self.received_components.append(self._cluster_components)


class TestMutation:
    """Test mutation functionality"""

    def test_mutate_simple_scenario(self, genetic_algorithm):
        """Test mutation of a simple scenario"""
        scenario = DummyScenario(cluster_components=ClusterComponents())

        # Set mutation rate to 0 to test parameter mutation path
        genetic_algorithm.current_scenario_mutation_rate = 0.0

        mutated = genetic_algorithm.mutate(scenario)

        # Should return the same scenario (DummyScenario.mutate() does nothing)
        # The mutate method is called internally, but since it's empty, the scenario remains unchanged
        assert mutated is scenario
        assert isinstance(mutated, DummyScenario)
        # Verify the scenario has mutate method (which will be called)
        assert hasattr(mutated, "mutate")

    def test_mutate_composite_scenario(self, genetic_algorithm):
        """Test mutation of a composite scenario recursively mutates sub-scenarios"""
        scenario_a = DummyScenario(cluster_components=ClusterComponents())
        scenario_b = DummyScenario(cluster_components=ClusterComponents())

        composite = CompositeScenario(
            name="composite",
            scenario_a=scenario_a,
            scenario_b=scenario_b,
            dependency=CompositeDependency.NONE,
        )

        # Set mutation rates to 0 to avoid scenario_mutation which requires valid scenarios
        genetic_algorithm.current_scenario_mutation_rate = 0.0

        mutated = genetic_algorithm.mutate(composite)

        # Should return the same composite scenario
        assert isinstance(mutated, CompositeScenario)
        assert mutated is composite
        # Sub-scenarios should be mutated recursively (though DummyScenario.mutate() does nothing)
        # Verify both sub-scenarios exist and have mutate methods
        assert mutated.scenario_a is not None
        assert mutated.scenario_b is not None
        assert hasattr(mutated.scenario_a, "mutate")
        assert hasattr(mutated.scenario_b, "mutate")

    def test_scenario_mutation_uses_active_cluster_components(self, genetic_algorithm):
        """Disabled components should stay out of scenario mutation."""
        cluster_components = ClusterComponents(
            namespaces=[
                Namespace(name="active-namespace"),
                Namespace(name="disabled-namespace", disabled=True),
            ],
            nodes=[
                Node(name="active-node"),
                Node(name="disabled-node", disabled=True),
            ],
        )
        genetic_algorithm.config.cluster_components = cluster_components
        genetic_algorithm.valid_scenarios = [("recording_scenario", RecordingScenario)]
        RecordingScenario.received_components = []

        source = SourceScenario(cluster_components=cluster_components)
        source.end = DummyEndParameter(value=42)

        success, mutated = genetic_algorithm.scenario_mutation(source)

        assert success
        assert isinstance(mutated, RecordingScenario)
        assert mutated.end.value == 42
        assert RecordingScenario.received_components

        received_components = RecordingScenario.received_components[-1]
        assert [ns.name for ns in received_components.namespaces] == [
            "active-namespace"
        ]
        assert [node.name for node in received_components.nodes] == ["active-node"]
        assert mutated._cluster_components == received_components
