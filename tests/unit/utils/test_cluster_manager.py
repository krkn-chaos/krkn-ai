"""
ClusterManager unit tests
"""

import pytest
from unittest.mock import Mock, patch

from krkn_ai.utils.cluster_manager import ClusterManager
from krkn_ai.models.cluster_components import Namespace


class TestClusterManager:
    """Test ClusterManager core functionality"""

    @pytest.fixture
    def mock_krkn_k8s(self):
        """Create mock KrknKubernetes client"""
        mock_k8s = Mock()
        mock_k8s.apps_api = Mock()
        mock_k8s.api_client = Mock()
        mock_k8s.cli = Mock()
        mock_k8s.custom_object_client = Mock()
        mock_k8s.list_namespaces = Mock(return_value=["default", "kube-system"])
        return mock_k8s

    @pytest.fixture
    def cluster_manager(self, mock_krkn_k8s):
        """Create ClusterManager instance with mocked dependencies"""
        with patch(
            "krkn_ai.utils.cluster_manager.KrknKubernetes", return_value=mock_krkn_k8s
        ):
            return ClusterManager(kubeconfig="/tmp/test-kubeconfig")

    def test_initialization_creates_cluster_manager_with_kubeconfig(
        self, mock_krkn_k8s
    ):
        """Test that ClusterManager initializes correctly with kubeconfig"""
        with patch(
            "krkn_ai.utils.cluster_manager.KrknKubernetes", return_value=mock_krkn_k8s
        ):
            manager = ClusterManager(kubeconfig="/tmp/test-kubeconfig")
            assert manager.kubeconfig == "/tmp/test-kubeconfig"
            assert manager.krkn_k8s == mock_krkn_k8s
            assert manager.core_api == mock_krkn_k8s.cli

    def test_discover_components_returns_cluster_components_with_namespaces_and_nodes(
        self, cluster_manager, mock_krkn_k8s
    ):
        """Test discover_components returns ClusterComponents with namespaces and nodes"""
        # Mock namespace listing - need to provide pattern that matches
        mock_krkn_k8s.list_namespaces.return_value = ["default"]

        # Mock pod listing
        mock_pod = Mock()
        mock_pod.metadata.name = "test-pod"
        mock_pod.metadata.labels = {"app": "test"}
        mock_owner_ref = Mock()
        mock_owner_ref.kind = "ReplicaSet"
        mock_owner_ref.name = "test-pod-abc123"
        mock_pod.metadata.owner_references = [mock_owner_ref]
        mock_container = Mock()
        mock_container.name = "test-container"
        mock_pod.spec = Mock()
        mock_pod.spec.containers = [mock_container]
        cluster_manager.core_api.list_namespaced_pod.return_value.items = [mock_pod]

        # Mock service listing
        mock_service = Mock()
        mock_service.metadata.name = "test-service"
        mock_service.metadata.labels = {}
        mock_service.spec.ports = [Mock(port=80, target_port=8080, protocol="TCP")]
        cluster_manager.core_api.list_namespaced_service.return_value.items = [
            mock_service
        ]

        # Mock PVC listing
        mock_pvc = Mock()
        mock_pvc.metadata.name = "test-pvc"
        mock_pvc.metadata.labels = {}
        cluster_manager.core_api.list_namespaced_persistent_volume_claim.return_value.items = [
            mock_pvc
        ]

        # Mock node listing
        mock_node = Mock()
        mock_node.metadata.name = "test-node"
        mock_node.metadata.labels = {"kubernetes.io/hostname": "test-node"}
        mock_node.spec.taints = None
        mock_node.spec.unschedulable = False
        mock_ready_condition = Mock()
        mock_ready_condition.type = "Ready"
        mock_ready_condition.status = "True"
        mock_node.status.conditions = [mock_ready_condition]
        mock_node.status.allocatable = {"cpu": "2", "memory": "4Gi"}
        cluster_manager.core_api.list_node.return_value.items = [mock_node]

        # Mock node metrics
        cluster_manager.custom_obj_api.list_cluster_custom_object.return_value = {
            "items": [
                {
                    "metadata": {"name": "test-node"},
                    "usage": {"cpu": "1", "memory": "2Gi"},
                }
            ]
        }

        # Mock node interfaces
        with patch(
            "krkn_ai.utils.cluster_manager.run_shell", return_value=("eth0\nens5\n", 0)
        ):
            # Provide pattern that matches "default" namespace
            components = cluster_manager.discover_components(
                namespace_pattern="default"
            )

        assert len(components.namespaces) == 1
        assert components.namespaces[0].name == "default"
        assert len(components.namespaces[0].pods) == 1
        assert components.namespaces[0].pods[0].name == "test-pod"
        assert components.namespaces[0].pods[0].owner is not None
        assert components.namespaces[0].pods[0].owner.kind == "ReplicaSet"
        assert components.namespaces[0].pods[0].owner.name == "test-pod-abc123"
        assert len(components.nodes) == 1
        assert components.nodes[0].name == "test-node"

    def test_parse_cpu_handles_various_cpu_formats_correctly(self):
        """Test parse_cpu handles nanocores, microcores, millicores, and cores"""
        # Test nanocores
        assert ClusterManager.parse_cpu("1000000n") == 1.0

        # Test microcores
        assert ClusterManager.parse_cpu("1000u") == 1.0

        # Test millicores
        assert ClusterManager.parse_cpu("500m") == 500.0

        # Test cores
        assert ClusterManager.parse_cpu("2") == 2000.0
        assert ClusterManager.parse_cpu("0.5") == 500.0

        # Test None
        assert ClusterManager.parse_cpu(None) == 0.0

        # Test invalid format raises ValueError
        with pytest.raises(ValueError, match="Unrecognized CPU format"):
            ClusterManager.parse_cpu("invalid")

    def test_parse_memory_handles_binary_and_si_units_correctly(self):
        """Test parse_memory handles binary (Ki/Mi/Gi) and SI (K/M/G) units"""
        # Test binary units
        assert ClusterManager.parse_memory("1024Ki") == 1024 * 1024
        assert ClusterManager.parse_memory("1Mi") == 1024**2
        assert ClusterManager.parse_memory("1Gi") == 1024**3

        # Test SI units
        assert ClusterManager.parse_memory("1000K") == 1000 * 1000
        assert ClusterManager.parse_memory("1M") == 1000**2

        # Test plain bytes
        assert ClusterManager.parse_memory("1024") == 1024
        assert ClusterManager.parse_memory("512.5") == 512

        # Test None
        assert ClusterManager.parse_memory(None) == 0

        # Test invalid format raises ValueError
        with pytest.raises(ValueError, match="Unable to parse memory string"):
            ClusterManager.parse_memory("invalid")

        with pytest.raises(ValueError, match="Unknown memory unit"):
            ClusterManager.parse_memory("100X")

    def test_list_namespaces_filters_by_pattern_when_provided(
        self, cluster_manager, mock_krkn_k8s
    ):
        """Test list_namespaces filters namespaces by pattern"""
        mock_krkn_k8s.list_namespaces.return_value = [
            "default",
            "kube-system",
            "test-ns",
        ]

        # Test with pattern - use regex that matches multiple namespaces
        namespaces = cluster_manager.list_namespaces("default|test-ns")
        assert len(namespaces) == 2
        assert {ns.name for ns in namespaces} == {"default", "test-ns"}

        # Test with pattern matching all (.* matches everything as regex)
        namespaces = cluster_manager.list_namespaces(".*")
        assert len(namespaces) == 3
        assert {ns.name for ns in namespaces} == {"default", "kube-system", "test-ns"}

    def test_list_namespaces_handles_none_empty_and_wildcard(
        self, cluster_manager, mock_krkn_k8s
    ):
        """Test list_namespaces handles None/empty as 'none', '*' as 'all'"""
        mock_krkn_k8s.list_namespaces.return_value = [
            "default",
            "kube-system",
            "test-ns",
        ]

        # None should match none (explicit selection required)
        namespaces = cluster_manager.list_namespaces(None)
        assert len(namespaces) == 0

        # Empty string should match none
        namespaces = cluster_manager.list_namespaces("  ")
        assert len(namespaces) == 0

        # '*' wildcard should now match ALL namespaces
        namespaces = cluster_manager.list_namespaces("*")
        assert len(namespaces) == 3
        assert {ns.name for ns in namespaces} == {"default", "kube-system", "test-ns"}

    def test_list_namespaces_with_multiple_patterns(
        self, cluster_manager, mock_krkn_k8s
    ):
        """Test list_namespaces works with comma-separated patterns"""
        mock_krkn_k8s.list_namespaces.return_value = [
            "default",
            "kube-system",
            "test-ns",
            "prod-app",
        ]

        namespaces = cluster_manager.list_namespaces("default, prod-.*")
        assert len(namespaces) == 2
        assert {ns.name for ns in namespaces} == {"default", "prod-app"}

    def test_list_namespaces_with_exclusion_pattern(
        self, cluster_manager, mock_krkn_k8s
    ):
        """Test list_namespaces works with exclusion patterns"""
        mock_krkn_k8s.list_namespaces.return_value = [
            "default",
            "kube-system",
            "kube-public",
            "test-ns",
        ]

        # Exclude kube-system only (implicit match all)
        namespaces = cluster_manager.list_namespaces("!kube-system")
        assert len(namespaces) == 3
        assert {ns.name for ns in namespaces} == {"default", "kube-public", "test-ns"}

    def test_list_namespaces_with_wildcard_and_exclusion(
        self, cluster_manager, mock_krkn_k8s
    ):
        """Test list_namespaces with '*' wildcard and exclusion pattern"""
        mock_krkn_k8s.list_namespaces.return_value = [
            "default",
            "kube-system",
            "kube-public",
            "test-ns",
        ]

        # Match all except kube-.*
        namespaces = cluster_manager.list_namespaces("*,!kube-.*")
        assert len(namespaces) == 2
        assert {ns.name for ns in namespaces} == {"default", "test-ns"}

    def test_list_namespaces_with_include_and_exclude(
        self, cluster_manager, mock_krkn_k8s
    ):
        """Test list_namespaces with both include and exclude patterns"""
        mock_krkn_k8s.list_namespaces.return_value = [
            "openshift-monitoring",
            "openshift-console",
            "openshift-operators",
            "default",
        ]

        # Include openshift-.* but exclude openshift-operators
        namespaces = cluster_manager.list_namespaces(
            "openshift-.*,!openshift-operators"
        )
        assert len(namespaces) == 2
        assert {ns.name for ns in namespaces} == {
            "openshift-monitoring",
            "openshift-console",
        }

    def test_list_pvcs_handles_exceptions_gracefully(self, cluster_manager):
        """Test list_pvcs returns empty list when exception occurs"""
        namespace = Namespace(name="test-ns")
        cluster_manager.core_api.list_namespaced_persistent_volume_claim.side_effect = (
            Exception("API error")
        )

        pvcs = cluster_manager.list_pvcs(namespace)
        assert pvcs == []

    def test_list_pods_filters_by_labels_and_skips_pods_by_name(self, cluster_manager):
        """Test list_pods filters pods by label patterns and skips pods by name patterns"""
        namespace = Namespace(name="test-ns")

        # Create mock pods
        mock_pod1 = Mock()
        mock_pod1.metadata.name = "app-pod"
        mock_pod1.metadata.labels = {"app": "myapp", "env": "prod"}
        mock_pod1.metadata.owner_references = None
        mock_container1 = Mock()
        mock_container1.name = "container1"
        mock_pod1.spec = Mock()
        mock_pod1.spec.containers = [mock_container1]

        mock_pod2 = Mock()
        mock_pod2.metadata.name = "skip-me"
        mock_pod2.metadata.labels = {"app": "myapp"}
        mock_pod2.metadata.owner_references = None
        mock_container2 = Mock()
        mock_container2.name = "container2"
        mock_pod2.spec = Mock()
        mock_pod2.spec.containers = [mock_container2]

        cluster_manager.core_api.list_namespaced_pod.return_value.items = [
            mock_pod1,
            mock_pod2,
        ]

        # Test filtering by label pattern and skipping by name pattern
        # Note: skip_pod_name_patterns now accepts string patterns
        pods = cluster_manager.list_pods(
            namespace, pod_labels_patterns="app", skip_pod_name_patterns="skip-me"
        )

        assert len(pods) == 1
        assert pods[0].name == "app-pod"
        assert pods[0].labels == {"app": "myapp"}

    def test_list_services_handles_ports_correctly(self, cluster_manager):
        """Test list_services processes service ports and handles None port values"""
        namespace = Namespace(name="test-ns")

        mock_service1 = Mock()
        mock_service1.metadata.name = "test-service"
        mock_service1.metadata.labels = {"app": "test"}
        mock_port1 = Mock(port=80, target_port=8080, protocol="TCP")
        mock_port2 = Mock(
            port=None, target_port=9090, protocol="UDP"
        )  # None port should be skipped
        mock_port3 = Mock(
            port=443, target_port=None, protocol=None
        )  # None protocol should default to TCP
        mock_service1.spec.ports = [mock_port1, mock_port2, mock_port3]

        cluster_manager.core_api.list_namespaced_service.return_value.items = [
            mock_service1
        ]

        services = cluster_manager.list_services(namespace)

        assert len(services) == 1
        assert services[0].name == "test-service"
        assert len(services[0].ports) == 2  # Only ports with non-None port values
        assert services[0].ports[0].port == 80
        assert services[0].ports[0].protocol == "TCP"
        assert services[0].ports[1].port == 443
        assert services[0].ports[1].protocol == "TCP"  # Default protocol

    def test_list_containers_extracts_container_names_from_pod_spec(
        self, cluster_manager
    ):
        """Test list_containers extracts container names from pod spec"""
        mock_container1 = Mock()
        mock_container1.name = "container1"
        mock_container2 = Mock()
        mock_container2.name = "container2"

        mock_pod_spec = Mock()
        mock_pod_spec.containers = [mock_container1, mock_container2]

        containers = cluster_manager.list_containers(mock_pod_spec)

        assert len(containers) == 2
        assert containers[0].name == "container1"
        assert containers[1].name == "container2"

    def test_list_nodes_filters_labels_and_handles_taints_and_metrics(
        self, cluster_manager
    ):
        """Test list_nodes filters node labels, formats taints, and calculates free resources"""
        # Mock node
        mock_node = Mock()
        mock_node.metadata.name = "test-node"
        mock_node.metadata.labels = {
            "kubernetes.io/hostname": "test-node",
            "node-role.kubernetes.io/worker": "",
            "custom-label": "value",
        }
        mock_taint = Mock()
        mock_taint.key = "NoSchedule"
        mock_taint.value = None
        mock_taint.effect = "NoSchedule"
        mock_node.spec.taints = [mock_taint]
        mock_node.spec.unschedulable = False
        mock_ready_condition = Mock()
        mock_ready_condition.type = "Ready"
        mock_ready_condition.status = "True"
        mock_node.status.conditions = [mock_ready_condition]
        mock_node.status.allocatable = {"cpu": "2", "memory": "4Gi"}
        cluster_manager.core_api.list_node.return_value.items = [mock_node]

        # Mock node metrics
        cluster_manager.custom_obj_api.list_cluster_custom_object.return_value = {
            "items": [
                {
                    "metadata": {"name": "test-node"},
                    "usage": {"cpu": "500m", "memory": "2Gi"},
                }
            ]
        }

        # Mock node interfaces
        with patch(
            "krkn_ai.utils.cluster_manager.run_shell",
            return_value=("eth0\nens5\nlo\n", 0),
        ):
            nodes = cluster_manager.list_nodes(
                node_label_pattern="kubernetes.io/hostname|custom-label"
            )

        assert len(nodes) == 1
        assert nodes[0].name == "test-node"
        assert "kubernetes.io/hostname" in nodes[0].labels
        assert "custom-label" in nodes[0].labels
        assert len(nodes[0].taints) == 1
        assert nodes[0].taints[0] == "NoSchedule:NoSchedule"
        assert nodes[0].free_cpu == 1500.0  # 2000m - 500m
        assert len(nodes[0].interfaces) == 2  # eth0 and ens5, lo is filtered out

    def test_list_nodes_handles_metrics_and_interfaces_exceptions(
        self, cluster_manager
    ):
        """Test list_nodes handles exceptions when fetching metrics or interfaces"""
        mock_node = Mock()
        mock_node.metadata.name = "test-node"
        mock_node.metadata.labels = {"kubernetes.io/hostname": "test-node"}
        mock_node.spec.taints = None
        mock_node.spec.unschedulable = False
        mock_ready_condition = Mock()
        mock_ready_condition.type = "Ready"
        mock_ready_condition.status = "True"
        mock_node.status.conditions = [mock_ready_condition]
        mock_node.status.allocatable = {"cpu": "2", "memory": "4Gi"}
        cluster_manager.core_api.list_node.return_value.items = [mock_node]

        # Mock metrics API failure
        cluster_manager.custom_obj_api.list_cluster_custom_object.side_effect = (
            Exception("Metrics API error")
        )

        # Mock interfaces failure
        with patch("krkn_ai.utils.cluster_manager.run_shell", return_value=("", 1)):
            nodes = cluster_manager.list_nodes()

        assert len(nodes) == 1
        assert nodes[0].name == "test-node"
        assert nodes[0].free_cpu == -1  # Error indicator
        assert nodes[0].free_mem == -1  # Error indicator
        assert nodes[0].interfaces == []  # Empty on failure

    def test_list_node_interfaces_filters_network_interfaces(self, cluster_manager):
        """Test list_node_interfaces filters and returns only ens/eth interfaces"""
        with patch(
            "krkn_ai.utils.cluster_manager.run_shell",
            return_value=("eth0\nens5\nlo\novs-system\nbr-ex\n", 0),
        ):
            interfaces = cluster_manager.list_node_interfaces("test-node")

        assert len(interfaces) == 2
        assert "eth0" in interfaces
        assert "ens5" in interfaces
        assert "lo" not in interfaces
        assert "ovs-system" not in interfaces

    def test_list_node_interfaces_returns_empty_list_on_shell_error(
        self, cluster_manager
    ):
        """Test list_node_interfaces returns empty list when shell command fails"""
        with patch("krkn_ai.utils.cluster_manager.run_shell", return_value=("", 1)):
            interfaces = cluster_manager.list_node_interfaces("test-node")

        assert interfaces == []
