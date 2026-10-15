"""
Crossover operation tests
"""

import copy
from unittest.mock import patch

import pytest

from krkn_ai.chaos_engines.commands import build_scenario_command
from krkn_ai.models.app import KrknRunnerType
from krkn_ai.models.scenario.base import CompositeScenario, CompositeDependency
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.cluster_components import (
    ClusterComponents,
    Namespace,
    OwnerReference,
    Pod,
    Service,
)
from krkn_ai.models.scenario.scenario_cpu_hog import NodeCPUHogScenario
from krkn_ai.models.scenario.scenario_pod import PodScenario
from krkn_ai.models.scenario.scenario_container import ContainerScenario
from krkn_ai.models.scenario.scenario_dns_outage import DnsOutageScenario
from krkn_ai.models.scenario.scenario_memory_hog import NodeMemoryHogScenario
from krkn_ai.models.scenario.scenario_io_hog import NodeIOHogScenario
from krkn_ai.models.scenario.scenario_network import NetworkScenario
from krkn_ai.models.scenario.scenario_pvc import PVCScenario
from krkn_ai.models.scenario.scenario_storage_throttle import StorageThrottleScenario
from krkn_ai.models.scenario.scenario_service_disruption import (
    ServiceDisruptionScenario,
)
from krkn_ai.models.scenario.parameters import (
    DummyEndParameter,
    DummyExitStatusParameter,
    NamespaceParameter,
)


class GroupedDummyScenario(DummyScenario):
    crossover_parameter_groups = ((DummyEndParameter, DummyExitStatusParameter),)


class OverlappingDummyScenario(GroupedDummyScenario):
    crossover_parameter_groups = ((DummyExitStatusParameter, NamespaceParameter),)
    namespace: NamespaceParameter = NamespaceParameter()

    @property
    def parameters(self):
        return super().parameters + [self.namespace]


class ExtendedGroupedDummyScenario(OverlappingDummyScenario):
    crossover_parameter_groups = GroupedDummyScenario.crossover_parameter_groups


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

    def test_pod_targeting_parameters_cross_over_together(self, genetic_algorithm):
        cluster = ClusterComponents(
            namespaces=[
                Namespace(name="ns-a", pods=[Pod(name="a", labels={"app": "a"})]),
                Namespace(name="ns-b", pods=[Pod(name="b", labels={"app": "b"})]),
            ]
        )
        parents = [PodScenario(cluster_components=cluster) for _ in range(2)]
        for parent, namespace, label in zip(
            parents, ["ns-a", "ns-b"], ["app=a", "app=b"]
        ):
            parent.namespace.value = namespace
            parent.pod_label.value = label
        genetic_algorithm.algo_config.crossover_rate = 0.6

        with patch(
            "krkn_ai.algorithm.genetic.engine.rng.random",
            side_effect=[0.1, 0.9, 0.9, 0.9, 0.9],
        ):
            children = genetic_algorithm.crossover(
                copy.deepcopy(parents[0]), copy.deepcopy(parents[1])
            )

        assert [
            (child.namespace.value, child.pod_label.value) for child in children
        ] == [("ns-b", "app=b"), ("ns-a", "app=a")]

    def test_pod_namespace_does_not_cross_without_label(
        self, genetic_algorithm, mock_cluster_components
    ):
        pod = PodScenario(cluster_components=mock_cluster_components)
        cpu = NodeCPUHogScenario(cluster_components=mock_cluster_components)
        original_target = (pod.namespace.value, pod.pod_label.value)
        genetic_algorithm.algo_config.crossover_rate = 1.0

        child, _ = genetic_algorithm.crossover(pod, cpu)

        assert (child.namespace.value, child.pod_label.value) == original_target

    @pytest.mark.parametrize(
        "hog_type", [NodeCPUHogScenario, NodeMemoryHogScenario, NodeIOHogScenario]
    )
    @pytest.mark.parametrize("service_first", [True, False])
    def test_service_disruption_does_not_inherit_hog_namespace(
        self, genetic_algorithm, mock_cluster_components, hog_type, service_first
    ):
        cluster = mock_cluster_components.model_copy(deep=True)
        cluster.namespaces[0].services = [Service(name="application-service")]
        service = ServiceDisruptionScenario(cluster_components=cluster)
        hog = hog_type(cluster_components=cluster)
        genetic_algorithm.algo_config.crossover_rate = 1.0

        parents = (service, hog) if service_first else (hog, service)
        genetic_algorithm.crossover(*parents)

        assert service.namespace.value == cluster.namespaces[0].name
        assert hog.namespace.value == "default"

    def test_service_disruption_target_crosses_between_compatible_parents(
        self, genetic_algorithm, mock_cluster_components
    ):
        cluster = mock_cluster_components.model_copy(deep=True)
        cluster.namespaces[0].services = [Service(name="application-service")]
        cluster.namespaces.append(
            Namespace(
                name="other-application", services=[Service(name="other-service")]
            )
        )
        first, second = [
            ServiceDisruptionScenario(cluster_components=cluster) for _ in range(2)
        ]
        first.namespace.value = cluster.namespaces[0].name
        second.namespace.value = cluster.namespaces[1].name
        first.runs.value, second.runs.value = 1, 3
        genetic_algorithm.algo_config.crossover_rate = 1.0

        genetic_algorithm.crossover(first, second)

        assert (first.namespace.value, second.namespace.value) == (
            cluster.namespaces[1].name,
            cluster.namespaces[0].name,
        )
        assert (first.runs.value, second.runs.value) == (3, 1)

    @pytest.mark.parametrize("group_roll", [0.1, 0.9])
    def test_declared_group_has_one_crossover_decision(
        self, genetic_algorithm, group_roll
    ):
        parents = [
            ExtendedGroupedDummyScenario(cluster_components=ClusterComponents())
            for _ in range(2)
        ]
        parents[0].end.value, parents[0].exit_status.value = 10, 0
        parents[1].end.value, parents[1].exit_status.value = 20, 1
        parents[0].namespace.value, parents[1].namespace.value = "a", "b"
        genetic_algorithm.algo_config.crossover_rate = 0.6

        with patch(
            "krkn_ai.algorithm.genetic.engine.rng.random",
            side_effect=[group_roll, 1 - group_roll],
        ):
            children = genetic_algorithm.crossover(*parents)

        expected = [(20, 1), (10, 0)] if group_roll < 0.6 else [(10, 0), (20, 1)]
        assert [
            (child.end.value, child.exit_status.value) for child in children
        ] == expected
        expected_namespaces = ["a", "b"] if group_roll < 0.6 else ["b", "a"]
        assert [child.namespace.value for child in children] == expected_namespaces

    def test_overlapping_groups_merge_into_one_exchange(self, genetic_algorithm):
        first = ExtendedGroupedDummyScenario(cluster_components=ClusterComponents())
        second = OverlappingDummyScenario(cluster_components=ClusterComponents())
        first.end.value, first.exit_status.value, first.namespace.value = 10, 0, "a"
        second.end.value, second.exit_status.value, second.namespace.value = 20, 1, "b"
        genetic_algorithm.algo_config.crossover_rate = 0.6

        with patch("krkn_ai.algorithm.genetic.engine.rng.random", side_effect=[0.1]):
            children = genetic_algorithm.crossover(first, second)

        assert [
            (child.end.value, child.exit_status.value, child.namespace.value)
            for child in children
        ] == [(20, 1, "b"), (10, 0, "a")]

    def test_incomplete_overlapping_group_is_not_partially_exchanged(
        self, genetic_algorithm
    ):
        first = GroupedDummyScenario(cluster_components=ClusterComponents())
        second = OverlappingDummyScenario(cluster_components=ClusterComponents())
        first.end.value, first.exit_status.value = 10, 0
        second.end.value, second.exit_status.value, second.namespace.value = 20, 1, "b"
        genetic_algorithm.algo_config.crossover_rate = 1.0

        child_a, child_b = genetic_algorithm.crossover(first, second)

        assert (child_a.end.value, child_a.exit_status.value) == (10, 0)
        assert (
            child_b.end.value,
            child_b.exit_status.value,
            child_b.namespace.value,
        ) == (20, 1, "b")

    def test_container_target_keeps_count_and_container(self, genetic_algorithm):
        first, second = [ContainerScenario.model_construct() for _ in range(2)]
        for scenario, ns, count in [(first, "a", 1), (second, "b", 2)]:
            scenario.namespace.value = ns
            scenario.label_selector.value = f"app={ns}"
            scenario.container_name.value = f"container-{ns}"
            scenario.disruption_count.value = count
        first.action.value, second.action.value = "1", "9"
        genetic_algorithm.algo_config.crossover_rate = 0.6

        with patch(
            "krkn_ai.algorithm.genetic.engine.rng.random",
            side_effect=[0.1, 0.9, 0.9],
        ):
            children = genetic_algorithm.crossover(first, second)

        assert [
            (
                c.namespace.value,
                c.label_selector.value,
                c.container_name.value,
                c.disruption_count.value,
            )
            for c in children
        ] == [("b", "app=b", "container-b", 2), ("a", "app=a", "container-a", 1)]
        assert [c.action.value for c in children] == ["1", "9"]

    def test_dns_crossover_preserves_lazy_pod_resolution(
        self, genetic_algorithm, minimal_config
    ):
        parents = [DnsOutageScenario.model_construct() for _ in range(2)]
        for scenario, ns in zip(parents, ["a", "b"]):
            scenario.namespace.value = ns
            scenario.pod_name.set_pod(
                ns,
                Pod(
                    name=f"old-{ns}",
                    owner=OwnerReference(kind="ReplicaSet", name=f"owner-{ns}"),
                ),
            )
        genetic_algorithm.algo_config.crossover_rate = 1.0
        children = genetic_algorithm.crossover(
            copy.deepcopy(parents[0]), copy.deepcopy(parents[1])
        )

        def resolve(namespace, old_name, kind, owner):
            assert kind == "ReplicaSet"
            assert old_name == f"old-{namespace}"
            assert owner == f"owner-{namespace}"
            return f"replacement-{namespace}"

        with patch("krkn_ai.cluster.resolve_pod_name", side_effect=resolve):
            commands = [
                build_scenario_command(child, minimal_config, KrknRunnerType.CLI_RUNNER)
                for child in children
            ]

        assert '--namespace "b"' in commands[0]
        assert '--pod-name "replacement-b"' in commands[0]
        assert '--namespace "a"' in commands[1]
        assert '--pod-name "replacement-a"' in commands[1]
        children[0].pod_name.value = "changed"
        assert parents[1].pod_name.value == "old-b"
        assert children[1].pod_name.value == "old-a"

    @pytest.mark.parametrize(
        "scenario_cls", [NodeCPUHogScenario, NodeMemoryHogScenario, NodeIOHogScenario]
    )
    def test_node_selector_count_and_taints_remain_consistent(
        self, genetic_algorithm, scenario_cls
    ):
        parents = [scenario_cls.model_construct() for _ in range(2)]
        for scenario, label, count in zip(parents, ["a", "b"], [1, 3]):
            scenario.node_selector.value = f"role={label}"
            scenario.number_of_nodes.value = count
            scenario.taint.value = f'["taint-{label}"]'
            if isinstance(scenario, NodeIOHogScenario):
                scenario.node_mount_path.value = f"/mnt/{label}"
        genetic_algorithm.algo_config.crossover_rate = 0.6

        with patch(
            "krkn_ai.algorithm.genetic.engine.rng.random",
            side_effect=[0.1] + [0.9] * 10,
        ):
            children = genetic_algorithm.crossover(*parents)

        assert [
            (c.node_selector.value, c.number_of_nodes.value, c.taint.value)
            for c in children
        ] == [("role=b", 3, '["taint-b"]'), ("role=a", 1, '["taint-a"]')]
        if scenario_cls is NodeIOHogScenario:
            assert [c.node_mount_path.value for c in children] == ["/mnt/b", "/mnt/a"]

    @pytest.mark.parametrize("scenario_cls", [PVCScenario, StorageThrottleScenario])
    def test_storage_target_variants_exchange_without_partial_state(
        self, genetic_algorithm, scenario_cls
    ):
        first, second = [scenario_cls.model_construct() for _ in range(2)]
        first.namespace.value, first.pvc_name.value = "a", "pvc-a"
        second.namespace.value = "b"
        second.pod_name.set_pod(
            "b",
            Pod(name="pod-b", owner=OwnerReference(kind="Deployment", name="app-b")),
        )
        if scenario_cls is PVCScenario:
            first.fill_percentage.value, second.fill_percentage.value = 90, 20
        else:
            first.mount_path.value, second.mount_path.value = "/mnt/a", "/mnt/b"
        genetic_algorithm.algo_config.crossover_rate = 1.0

        child_a, child_b = genetic_algorithm.crossover(first, second)

        assert (
            child_a.namespace.value,
            child_a.pvc_name.value,
            child_a.pod_name.value,
        ) == ("b", "", "pod-b")
        assert (
            child_b.namespace.value,
            child_b.pvc_name.value,
            child_b.pod_name.value,
        ) == ("a", "pvc-a", "")
        assert [p.get_name() for p in child_a.parameters].count("pod-name") == 1
        assert "pvc-name" not in [p.get_name() for p in child_a.parameters]
        assert "pod-name" not in [p.get_name() for p in child_b.parameters]
        assert child_a.pod_name._namespace == "b"
        assert child_a.pod_name._owner_name == "app-b"
        if scenario_cls is PVCScenario:
            assert child_a.fill_percentage.value == 20
            assert child_b.fill_percentage.value == 90
        else:
            assert child_a.mount_path.value == "/mnt/b"
            assert child_b.mount_path.value == "/mnt/a"

    def test_network_mode_exchanges_its_inactive_target_fields(
        self, genetic_algorithm, minimal_config
    ):
        first, second = [NetworkScenario.model_construct() for _ in range(2)]
        first.traffic_type.value = "ingress"
        first.target_node_interface.value = "{node-a: [eth-a]}"
        first.network_params.value.latency = 111
        second.traffic_type.value = "egress"
        second.node_name.value = "node-b"
        second.egress_params.value.latency = 222
        genetic_algorithm.algo_config.crossover_rate = 1.0

        child_a, child_b = genetic_algorithm.crossover(first, second)
        command_a = build_scenario_command(
            child_a, minimal_config, KrknRunnerType.CLI_RUNNER
        )
        command_b = build_scenario_command(
            child_b, minimal_config, KrknRunnerType.CLI_RUNNER
        )

        assert '--traffic-type "egress"' in command_a
        assert '--node-name "node-b"' in command_a
        assert "latency: 222ms" in command_a
        assert "--target-node-interface" not in command_a
        assert '--traffic-type "ingress"' in command_b
        assert '--target-node-interface "{node-a: [eth-a]}"' in command_b
        assert "latency: 111ms" in command_b
        assert "--node-name" not in command_b
