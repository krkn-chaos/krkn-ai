"""
Scenario classes tests (PodScenario, ContainerScenario, etc.)
"""

import pytest
from unittest.mock import patch
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.scenario.scenario_pod import PodScenario
from krkn_ai.models.scenario.scenario_container import ContainerScenario
from krkn_ai.models.scenario.scenario_cpu_hog import NodeCPUHogScenario
from krkn_ai.models.scenario.scenario_app_outage import AppOutageScenario
from krkn_ai.models.scenario.scenario_memory_hog import NodeMemoryHogScenario
from krkn_ai.models.scenario.scenario_io_hog import NodeIOHogScenario
from krkn_ai.models.scenario.scenario_time import TimeScenario
from krkn_ai.models.scenario.scenario_network import NetworkScenario
from krkn_ai.models.scenario.scenario_dns_outage import DnsOutageScenario
from krkn_ai.models.scenario.scenario_syn_flood import SynFloodScenario
from krkn_ai.models.scenario.scenario_pvc import PVCScenario
from krkn_ai.models.scenario.scenario_storage_throttle import StorageThrottleScenario
from krkn_ai.models.cluster_components import (
    ClusterComponents,
    Namespace,
    Pod,
    Container,
    Node,
    Service,
    ServicePort,
    PVC,
)
from krkn_ai.models.custom_errors import ScenarioParameterInitError


class TestDummyScenario:
    """Test DummyScenario class"""

    def test_dummy_scenario_initialization(self):
        """Test that DummyScenario initializes with default parameters"""
        cluster = ClusterComponents(namespaces=[], nodes=[])
        scenario = DummyScenario(cluster_components=cluster)
        assert scenario.name == "dummy-scenario"
        assert scenario.krknctl_name == "dummy-scenario"
        assert len(scenario.parameters) == 2
        assert scenario.end.value == 10
        assert scenario.exit_status.value == 0


class TestPodScenario:
    """Test PodScenario class"""

    def test_pod_scenario_initialization_with_valid_pods(self):
        """Test that PodScenario initializes when pods with labels exist"""
        pod = Pod(
            name="test-pod",
            labels={"app": "web", "version": "1.0"},
            containers=[Container(name="container1")],
        )
        namespace = Namespace(name="test-ns", pods=[pod])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        scenario = PodScenario(cluster_components=cluster)
        assert scenario.name == "pod-scenarios"
        assert scenario.namespace.value == "test-ns"
        assert (
            "app=" in scenario.pod_label.value or "version=" in scenario.pod_label.value
        )

    def test_pod_scenario_raises_error_when_no_pods_with_labels(self):
        """Test that PodScenario raises ScenarioParameterInitError when no pods have labels"""
        pod = Pod(name="test-pod", labels={}, containers=[])
        namespace = Namespace(name="test-ns", pods=[pod])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        with pytest.raises(
            ScenarioParameterInitError, match="No pods found with labels"
        ):
            PodScenario(cluster_components=cluster)


class TestContainerScenario:
    """Test ContainerScenario class"""

    def test_container_scenario_initialization_with_valid_pods(self):
        """Test that ContainerScenario initializes when pods with labels exist"""
        pod = Pod(
            name="test-pod",
            labels={"app": "web"},
            containers=[Container(name="container1"), Container(name="container2")],
        )
        namespace = Namespace(name="test-ns", pods=[pod])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        scenario = ContainerScenario(cluster_components=cluster)
        assert scenario.name == "container-scenarios"
        assert scenario.namespace.value == "test-ns"
        assert scenario.disruption_count.value >= 1
        assert scenario.disruption_count.value <= len(pod.containers)

    def test_container_scenario_raises_error_when_no_pods_with_labels(self):
        """Test that ContainerScenario raises error when no pods have labels"""
        pod = Pod(name="test-pod", labels={}, containers=[])
        namespace = Namespace(name="test-ns", pods=[pod])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        with pytest.raises(
            ScenarioParameterInitError, match="No pods found with labels"
        ):
            ContainerScenario(cluster_components=cluster)


class TestNodeCPUHogScenario:
    """Test NodeCPUHogScenario class"""

    def test_node_cpu_hog_scenario_initialization_with_nodes(self):
        """Test that NodeCPUHogScenario initializes when nodes exist"""
        node = Node(
            name="test-node",
            labels={"kubernetes.io/os": "linux"},
            free_cpu=4.0,
            free_mem=8.0,
            interfaces=["eth0"],
            taints=[],
        )
        cluster = ClusterComponents(namespaces=[], nodes=[node])

        scenario = NodeCPUHogScenario(cluster_components=cluster)
        assert scenario.name == "node-cpu-hog"
        assert scenario.node_cpu_percentage.value >= 20
        assert scenario.node_cpu_percentage.value <= 100
        assert scenario.number_of_nodes.value >= 1


class TestAppOutageScenario:
    """Test AppOutageScenario class"""

    def test_app_outage_scenario_initialization_with_valid_pods(self):
        """Test that AppOutageScenario initializes when pods with labels exist"""
        pod = Pod(name="test-pod", labels={"app": "web"}, containers=[])
        namespace = Namespace(name="test-ns", pods=[pod])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        scenario = AppOutageScenario(cluster_components=cluster)
        assert scenario.name == "application-outages"
        assert scenario.namespace.value == "test-ns"
        assert "{" in scenario.pod_selector.value and "}" in scenario.pod_selector.value

    def test_app_outage_scenario_raises_error_when_no_pods_with_labels(self):
        """Test that AppOutageScenario raises error when no pods have labels"""
        pod = Pod(name="test-pod", labels={}, containers=[])
        namespace = Namespace(name="test-ns", pods=[pod])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        with pytest.raises(
            ScenarioParameterInitError, match="No pods found with labels"
        ):
            AppOutageScenario(cluster_components=cluster)


class TestNodeMemoryHogScenario:
    """Test NodeMemoryHogScenario class"""

    def test_node_memory_hog_scenario_initialization_with_nodes(self):
        """Test that NodeMemoryHogScenario initializes when nodes exist"""
        node = Node(name="test-node", free_cpu=4.0, free_mem=8.0)
        cluster = ClusterComponents(namespaces=[], nodes=[node])

        scenario = NodeMemoryHogScenario(cluster_components=cluster)
        assert scenario.name == "node-memory-hog"
        assert scenario.node_memory_percentage.value >= 20
        assert scenario.node_memory_percentage.value <= 100
        assert scenario.number_of_nodes.value >= 1

    def test_node_memory_hog_scenario_raises_error_when_no_nodes(self):
        """Test that NodeMemoryHogScenario raises error when no nodes exist"""
        cluster = ClusterComponents(namespaces=[], nodes=[])

        with pytest.raises(ScenarioParameterInitError, match="No nodes found"):
            NodeMemoryHogScenario(cluster_components=cluster)


class TestNodeIOHogScenario:
    """Test NodeIOHogScenario class"""

    def test_node_io_hog_scenario_initialization_with_nodes(self):
        """Test that NodeIOHogScenario initializes when nodes exist"""
        node = Node(name="test-node", free_cpu=4.0, free_mem=8.0)
        cluster = ClusterComponents(namespaces=[], nodes=[node])

        scenario = NodeIOHogScenario(cluster_components=cluster)
        assert scenario.name == "node-io-hog"
        assert scenario.io_workers.value >= 1
        assert scenario.io_write_bytes.value >= 1
        assert scenario.io_write_bytes.value <= 100

    def test_node_io_hog_scenario_raises_error_when_no_nodes(self):
        """Test that NodeIOHogScenario raises error when no nodes exist"""
        cluster = ClusterComponents(namespaces=[], nodes=[])

        with pytest.raises(ScenarioParameterInitError, match="No nodes found"):
            NodeIOHogScenario(cluster_components=cluster)


class TestTimeScenario:
    """Test TimeScenario class"""

    def test_time_scenario_initialization_with_pods(self):
        """Test that TimeScenario initializes when pods with labels exist"""
        pod = Pod(name="test-pod", labels={"app": "web"}, containers=[])
        namespace = Namespace(name="test-ns", pods=[pod])
        node = Node(name="test-node", labels={"os": "linux"})
        cluster = ClusterComponents(namespaces=[namespace], nodes=[node])

        scenario = TimeScenario(cluster_components=cluster)
        assert scenario.name == "time-scenarios"
        assert scenario.object_type.value in ["pod", "node"]
        assert scenario.label_selector.value != ""

    def test_time_scenario_raises_error_when_no_labels(self):
        """Test that TimeScenario raises error when no labels exist"""
        pod = Pod(name="test-pod", labels={}, containers=[])
        namespace = Namespace(name="test-ns", pods=[pod])
        node = Node(name="test-node", labels={})
        cluster = ClusterComponents(namespaces=[namespace], nodes=[node])

        with pytest.raises(ScenarioParameterInitError, match="No labels found"):
            TimeScenario(cluster_components=cluster)


class TestNetworkScenario:
    """Test NetworkScenario class"""

    def test_network_scenario_initialization_with_nodes_with_interfaces(self):
        """Test that NetworkScenario initializes when nodes with interfaces exist"""
        node = Node(name="test-node", interfaces=["eth0", "eth1"])
        cluster = ClusterComponents(namespaces=[], nodes=[node])

        scenario = NetworkScenario(cluster_components=cluster)
        assert scenario.name == "network-chaos"
        assert scenario.traffic_type.value == "egress"
        assert scenario.node_name.value == "test-node"
        assert scenario.interfaces.value != ""

    def test_network_scenario_raises_error_when_no_nodes_with_interfaces(self):
        """Test that NetworkScenario raises error when no nodes have interfaces"""
        node = Node(name="test-node", interfaces=[])
        cluster = ClusterComponents(namespaces=[], nodes=[node])

        with pytest.raises(
            ScenarioParameterInitError, match="No nodes found with interfaces"
        ):
            NetworkScenario(cluster_components=cluster)


class TestDnsOutageScenario:
    """Test DnsOutageScenario class"""

    def test_dns_outage_scenario_initialization_with_pods(self):
        """Test that DnsOutageScenario initializes when pods exist"""
        pod = Pod(name="test-pod", labels={}, containers=[])
        namespace = Namespace(name="test-ns", pods=[pod])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        scenario = DnsOutageScenario(cluster_components=cluster)
        assert scenario.name == "dns-outage"
        assert scenario.namespace.value == "test-ns"
        assert scenario.pod_name.value == "test-pod"
        assert scenario.egress.value == "true"

    def test_dns_outage_scenario_raises_error_when_no_pods(self):
        """Test that DnsOutageScenario raises error when no pods exist"""
        cluster = ClusterComponents(namespaces=[], nodes=[])

        with pytest.raises(ScenarioParameterInitError, match="No pods found"):
            DnsOutageScenario(cluster_components=cluster)


class TestSynFloodScenario:
    """Test SynFloodScenario class"""

    def test_syn_flood_scenario_initialization_with_services(self):
        """Test that SynFloodScenario initializes when services with ports exist"""
        service = Service(
            name="test-service", ports=[ServicePort(port=80, target_port=8080)]
        )
        namespace = Namespace(name="test-ns", services=[service])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        scenario = SynFloodScenario(cluster_components=cluster)
        assert scenario.name == "syn-flood"
        assert scenario.namespace.value == "test-ns"
        assert scenario.target_service.value == "test-service"
        assert scenario.target_port.value == 80

    def test_syn_flood_scenario_raises_error_when_no_services_with_ports(self):
        """Test that SynFloodScenario raises error when no services with ports exist"""
        namespace = Namespace(name="test-ns", services=[])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        with pytest.raises(
            ScenarioParameterInitError, match="No services with ports found"
        ):
            SynFloodScenario(cluster_components=cluster)


class TestPVCScenario:
    """Test PVCScenario class"""

    @patch("krkn_ai.models.scenario.scenario_pvc.get_pvc_usage_percentage")
    def test_pvc_scenario_initialization_with_pvcs(self, mock_get_usage):
        """Test that PVCScenario initializes when PVCs exist"""
        mock_get_usage.return_value = None
        pvc = PVC(name="test-pvc", labels={})
        namespace = Namespace(name="test-ns", pvcs=[pvc])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        scenario = PVCScenario(cluster_components=cluster)
        assert scenario.name == "pvc-scenarios"
        assert scenario.namespace.value == "test-ns"
        assert scenario.pvc_name.value == "test-pvc"
        assert scenario.fill_percentage.value >= 1
        assert scenario.fill_percentage.value <= 99

    def test_pvc_scenario_raises_error_when_no_pvcs_or_pods(self):
        """Test that PVCScenario raises error when no PVCs or pods exist"""
        cluster = ClusterComponents(namespaces=[], nodes=[])

        with pytest.raises(ScenarioParameterInitError, match="No namespaces found"):
            PVCScenario(cluster_components=cluster)


class TestStorageThrottleScenario:
    """Test StorageThrottleScenario class"""

    def test_storage_throttle_scenario_initialization_with_pvcs(self):
        """Test that StorageThrottleScenario initializes when PVCs exist"""
        pvc = PVC(name="test-pvc", labels={})
        namespace = Namespace(name="test-ns", pvcs=[pvc])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        scenario = StorageThrottleScenario(cluster_components=cluster)
        assert scenario.name == "storage-throttle"
        assert scenario.namespace.value == "test-ns"
        assert scenario.pvc_name.value == "test-pvc"
        assert scenario.pod_name.value == ""
        assert scenario.throttle_type.value in ["iops", "bandwidth", "both"]

    def test_storage_throttle_scenario_initialization_with_pods_only(self):
        """Test that StorageThrottleScenario falls back to pods when no PVCs exist"""
        pod = Pod(
            name="test-pod",
            labels={"app": "web"},
            containers=[Container(name="c1")],
        )
        namespace = Namespace(name="test-ns", pods=[pod])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        scenario = StorageThrottleScenario(cluster_components=cluster)
        assert scenario.name == "storage-throttle"
        assert scenario.namespace.value == "test-ns"
        assert scenario.pod_name.value == "test-pod"
        assert scenario.pvc_name.value == ""

    def test_storage_throttle_scenario_raises_error_when_no_pvcs_or_pods(self):
        """Test that StorageThrottleScenario raises error when no PVCs or pods exist"""
        cluster = ClusterComponents(namespaces=[], nodes=[])

        with pytest.raises(ScenarioParameterInitError, match="No namespaces found"):
            StorageThrottleScenario(cluster_components=cluster)

    def test_storage_throttle_scenario_raises_error_empty_namespace(self):
        """Test that StorageThrottleScenario raises error when namespace has no PVCs or pods"""
        namespace = Namespace(name="test-ns")
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        with pytest.raises(ScenarioParameterInitError, match="No PVCs or pods found"):
            StorageThrottleScenario(cluster_components=cluster)

    def test_storage_throttle_scenario_conditional_parameters_iops(self):
        """Test that parameters list includes IOPS params when throttle_type is iops"""
        pvc = PVC(name="test-pvc", labels={})
        namespace = Namespace(name="test-ns", pvcs=[pvc])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        scenario = StorageThrottleScenario(cluster_components=cluster)
        scenario.throttle_type.value = "iops"
        param_names = [p.krknctl_name for p in scenario.parameters]
        assert "read-iops" in param_names
        assert "write-iops" in param_names
        assert "read-bps" not in param_names
        assert "write-bps" not in param_names

    def test_storage_throttle_scenario_conditional_parameters_bandwidth(self):
        """Test that parameters list includes BPS params when throttle_type is bandwidth"""
        pvc = PVC(name="test-pvc", labels={})
        namespace = Namespace(name="test-ns", pvcs=[pvc])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        scenario = StorageThrottleScenario(cluster_components=cluster)
        scenario.throttle_type.value = "bandwidth"
        param_names = [p.krknctl_name for p in scenario.parameters]
        assert "read-bps" in param_names
        assert "write-bps" in param_names
        assert "read-iops" not in param_names
        assert "write-iops" not in param_names

    def test_storage_throttle_scenario_conditional_parameters_both(self):
        """Test that parameters list includes all throttle params when type is both"""
        pvc = PVC(name="test-pvc", labels={})
        namespace = Namespace(name="test-ns", pvcs=[pvc])
        cluster = ClusterComponents(namespaces=[namespace], nodes=[])

        scenario = StorageThrottleScenario(cluster_components=cluster)
        scenario.throttle_type.value = "both"
        param_names = [p.krknctl_name for p in scenario.parameters]
        assert "read-iops" in param_names
        assert "write-iops" in param_names
        assert "read-bps" in param_names
        assert "write-bps" in param_names
