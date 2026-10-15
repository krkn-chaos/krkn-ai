"""
Mutation operation tests
"""

from typing import ClassVar, List

import pytest

from krkn_ai.models.scenario.base import (
    CompositeScenario,
    CompositeDependency,
    ScenarioOrigin,
)
from krkn_ai.models.scenario.parameters import DummyEndParameter
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.scenario.scenario_app_outage import AppOutageScenario
from krkn_ai.models.scenario.scenario_container import ContainerScenario
from krkn_ai.models.scenario.scenario_cpu_hog import NodeCPUHogScenario
from krkn_ai.models.scenario.scenario_memory_hog import NodeMemoryHogScenario
from krkn_ai.models.scenario.scenario_pod import PodScenario
from krkn_ai.models.scenario.scenario_pvc import PVCScenario
from krkn_ai.models.scenario.scenario_time import TimeScenario
from krkn_ai.models.cluster_components import ClusterComponents, Namespace, Node
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

    @pytest.mark.parametrize(
        "target_cls", [PodScenario, PVCScenario, AppOutageScenario, ContainerScenario]
    )
    def test_type_mutation_keeps_valid_target_from_incompatible_source(
        self, genetic_algorithm, target_cls
    ):
        source = TimeScenario.model_construct()
        source.object_type.value = "node"
        source.namespace.value = ""
        source.label_selector.value = "kubernetes.io/hostname=test-node"
        genetic_algorithm.valid_scenarios = [("target", target_cls)]

        success, child = genetic_algorithm.scenario_mutation(source)

        assert success
        assert child.namespace.value == "test-namespace"
        assert source.namespace.value == ""
        if isinstance(child, PodScenario):
            assert child.pod_label.value == "app=test"
        elif isinstance(child, PVCScenario):
            assert child.pod_name.value == "test-pod"
            assert child.pod_name._namespace == "test-namespace"
        elif isinstance(child, AppOutageScenario):
            assert child.pod_selector.value == "{app: test}"
        else:
            assert child.label_selector.value == "app=test"
            assert child.container_name.value in ("test-container", ".*")

    def test_type_mutation_inherits_compatible_group_without_aliasing(
        self, genetic_algorithm
    ):
        source = NodeCPUHogScenario.model_construct()
        source.node_selector.value = "kubernetes.io/hostname=test-node"
        source.number_of_nodes.value = 1
        source.taint.value = '["source-taint"]'
        source.chaos_duration.value = 75
        genetic_algorithm.valid_scenarios = [("memory", NodeMemoryHogScenario)]

        success, child = genetic_algorithm.scenario_mutation(source)

        assert success
        assert child.node_selector.value == source.node_selector.value
        assert child.number_of_nodes.value == 1
        assert child.taint.value == '["source-taint"]'
        assert child.chaos_duration.value == 75
        child.number_of_nodes.value = 2
        assert source.number_of_nodes.value == 1
