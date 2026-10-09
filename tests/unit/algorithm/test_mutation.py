"""
Mutation operation tests
"""

from typing import ClassVar, List

from krkn_ai.models.scenario.base import (
    CompositeScenario,
    CompositeDependency,
    ScenarioOrigin,
)
from krkn_ai.models.scenario.parameters import DummyEndParameter
from krkn_ai.models.scenario.scenario_dns_outage import DnsOutageScenario
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.scenario.scenario_storage_throttle import (
    StorageThrottleScenario,
)
from krkn_ai.models.cluster_components import (
    ClusterComponents,
    Namespace,
    Node,
    OwnerReference,
    Pod,
)
from krkn_ai.utils.rng import rng
from krkn_ai.algorithm.genetic import GeneticAlgorithm


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


class RerandomizingScenario(DummyScenario):
    """DummyScenario whose mutate() re-draws values, like real scenarios."""

    name: str = "rerandomizing-scenario"
    krknctl_name: str = "rerandomizing-scenario"
    krknhub_image: str = "rerandomizing-scenario"

    def mutate(self):
        self.end.value = rng.randint(0, 100)


class TestMutation:
    """Test mutation functionality"""

    def test_mutate_simple_scenario(self, genetic_algorithm):
        """Test mutation of a simple scenario"""
        scenario = DummyScenario(cluster_components=ClusterComponents())

        # Avoid type mutation (requires valid scenarios); force parameter mutation
        genetic_algorithm.current_scenario_mutation_rate = 0.0
        genetic_algorithm.algo_config.mutation_rate = 1.0

        mutated = genetic_algorithm.mutate(scenario)

        # Should return the same scenario (DummyScenario.mutate() does nothing)
        # Parameter mutation runs, tagging the scenario as PARAMETER_MUTATION
        assert mutated is scenario
        assert isinstance(mutated, DummyScenario)
        assert mutated.origin is ScenarioOrigin.PARAMETER_MUTATION

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

        # Avoid type mutation (requires valid scenarios); force parameter mutation
        genetic_algorithm.current_scenario_mutation_rate = 0.0
        genetic_algorithm.algo_config.mutation_rate = 1.0

        mutated = genetic_algorithm.mutate(composite)

        # Should return the same composite scenario
        assert isinstance(mutated, CompositeScenario)
        assert mutated is composite
        # Sub-scenarios should be mutated recursively (though DummyScenario.mutate() does nothing)
        # Verify both sub-scenarios exist and were parameter-mutated
        assert mutated.scenario_a is not None
        assert mutated.scenario_b is not None
        assert mutated.scenario_a.origin is ScenarioOrigin.PARAMETER_MUTATION
        assert mutated.scenario_b.origin is ScenarioOrigin.PARAMETER_MUTATION

    def test_mutate_skipped_keeps_crossover_origin(self, genetic_algorithm):
        """A child that skips parameter mutation keeps its crossover origin and values.

        Regression test for #482: before the fix, scenario.mutate() ran
        unconditionally, so a crossover child was re-randomized and re-tagged
        PARAMETER_MUTATION even when both mutation rates were 0.
        """
        scenario = RerandomizingScenario(cluster_components=ClusterComponents())
        scenario.end.value = 42
        GeneticAlgorithm._tag_lineage(scenario, ["parent-1"], ScenarioOrigin.CROSSOVER)

        genetic_algorithm.current_scenario_mutation_rate = 0.0
        genetic_algorithm.algo_config.mutation_rate = 0.0

        mutated = genetic_algorithm.mutate(scenario)

        assert mutated is scenario
        assert mutated.end.value == 42
        assert mutated.origin is ScenarioOrigin.CROSSOVER

    def test_mutate_applied_retags_as_parameter_mutation(self, genetic_algorithm):
        """When parameter mutation is applied, the child is re-tagged."""
        scenario = RerandomizingScenario(cluster_components=ClusterComponents())
        scenario.end.value = 42
        GeneticAlgorithm._tag_lineage(scenario, ["parent-1"], ScenarioOrigin.CROSSOVER)

        genetic_algorithm.current_scenario_mutation_rate = 0.0
        genetic_algorithm.algo_config.mutation_rate = 1.0

        mutated = genetic_algorithm.mutate(scenario)

        assert mutated is scenario
        assert mutated.origin is ScenarioOrigin.PARAMETER_MUTATION

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


class TestScenarioMutationParameterState:
    """Scenario mutation must transfer full parameter state, not just .value"""

    def test_scenario_mutation_carries_pod_name_metadata(self, genetic_algorithm):
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
        # The source targets billing; mutation builds the new scenario from a
        # cluster that only has shipping, then copies the source's parameters.
        source = DnsOutageScenario(
            cluster_components=ClusterComponents(namespaces=[billing])
        )
        genetic_algorithm.config.cluster_components = ClusterComponents(
            namespaces=[shipping]
        )
        genetic_algorithm.valid_scenarios = [
            ("storage_throttle", StorageThrottleScenario)
        ]

        success, mutated = genetic_algorithm.scenario_mutation(source)

        assert success
        assert isinstance(mutated, StorageThrottleScenario)
        assert mutated.pod_name.value == "api-abc"
        assert mutated.pod_name._namespace == "billing"
        assert mutated.pod_name._owner_kind == "ReplicaSet"
        assert mutated.pod_name._owner_name == "api-rs"
