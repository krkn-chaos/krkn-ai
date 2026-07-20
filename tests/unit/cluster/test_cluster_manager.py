"""
ClusterManager unit tests
"""

import pytest
from unittest.mock import Mock, patch

from krkn_ai.cluster import ClusterManager
from krkn_ai.models.cluster_components import ClusterComponents, Namespace


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
            "krkn_ai.cluster.cluster_manager.KrknKubernetes", return_value=mock_krkn_k8s
        ):
            return ClusterManager(kubeconfig="/tmp/test-kubeconfig")

    def test_initialization_creates_cluster_manager_with_kubeconfig(
        self, mock_krkn_k8s
    ):
        """Test that ClusterManager initializes correctly with kubeconfig"""
        with patch(
            "krkn_ai.cluster.cluster_manager.KrknKubernetes", return_value=mock_krkn_k8s
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
            "krkn_ai.cluster.cluster_manager.run_shell",
            return_value=("eth0\nens5\n", 0),
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

        # Test lowercase SI units (case-insensitive fallback)
        assert ClusterManager.parse_memory("1000k") == 1000 * 1000
        assert ClusterManager.parse_memory("512m") == 512 * 1000**2
        assert ClusterManager.parse_memory("2g") == 2 * 1000**3

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
            "krkn_ai.cluster.cluster_manager.run_shell",
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
        with patch("krkn_ai.cluster.cluster_manager.run_shell", return_value=("", 1)):
            nodes = cluster_manager.list_nodes()

        assert len(nodes) == 1
        assert nodes[0].name == "test-node"
        assert nodes[0].free_cpu == -1  # Error indicator
        assert nodes[0].free_mem == -1  # Error indicator
        assert nodes[0].interfaces == []  # Empty on failure

    def test_list_node_interfaces_filters_network_interfaces(self, cluster_manager):
        """Test list_node_interfaces filters and returns only ens/eth interfaces"""
        with patch(
            "krkn_ai.cluster.cluster_manager.run_shell",
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
        with patch("krkn_ai.cluster.cluster_manager.run_shell", return_value=("", 1)):
            interfaces = cluster_manager.list_node_interfaces("test-node")

        assert interfaces == []

    def test_list_nodes_fetches_interfaces_for_all_nodes(self, cluster_manager):
        """All nodes get interfaces populated even when fetched concurrently"""

        def make_node(name):
            node = Mock()
            node.metadata.name = name
            node.metadata.labels = {"kubernetes.io/hostname": name}
            node.spec.taints = None
            node.spec.unschedulable = False
            ready = Mock()
            ready.type = "Ready"
            ready.status = "True"
            node.status.conditions = [ready]
            node.status.allocatable = {"cpu": "2", "memory": "4Gi"}
            return node

        cluster_manager.core_api.list_node.return_value.items = [
            make_node("node-a"),
            make_node("node-b"),
            make_node("node-c"),
        ]
        cluster_manager.custom_obj_api.list_cluster_custom_object.side_effect = (
            Exception("no metrics")
        )

        with patch(
            "krkn_ai.cluster.cluster_manager.run_shell",
            return_value=("eth0\n", 0),
        ):
            nodes = cluster_manager.list_nodes()

        assert len(nodes) == 3
        assert all(n.interfaces == ["eth0"] for n in nodes)

    def test_list_nodes_one_interface_timeout_does_not_block_others(
        self, cluster_manager
    ):
        """A failed interface lookup on one node leaves others unaffected"""
        from krkn_ai.models.custom_errors import ShellCommandTimeoutError

        def make_node(name):
            node = Mock()
            node.metadata.name = name
            node.metadata.labels = {"kubernetes.io/hostname": name}
            node.spec.taints = None
            node.spec.unschedulable = False
            ready = Mock()
            ready.type = "Ready"
            ready.status = "True"
            node.status.conditions = [ready]
            node.status.allocatable = {"cpu": "2", "memory": "4Gi"}
            return node

        cluster_manager.core_api.list_node.return_value.items = [
            make_node("good-node"),
            make_node("bad-node"),
        ]
        cluster_manager.custom_obj_api.list_cluster_custom_object.side_effect = (
            Exception("no metrics")
        )

        def fake_run_shell(cmd, **kwargs):
            if "bad-node" in cmd:
                raise ShellCommandTimeoutError("timed out")
            return ("eth0\n", 0)

        with patch(
            "krkn_ai.cluster.cluster_manager.run_shell", side_effect=fake_run_shell
        ):
            nodes = cluster_manager.list_nodes()

        assert len(nodes) == 2
        by_name = {n.name: n for n in nodes}
        assert by_name["good-node"].interfaces == ["eth0"]
        assert by_name["bad-node"].interfaces == []


def _http_get(path, port, scheme="HTTP"):
    hg = Mock()
    hg.path = path
    hg.port = port
    hg.scheme = scheme
    return hg


def _probe(http_get):
    probe = Mock()
    probe.http_get = http_get
    return probe


def _container(readiness=None, liveness=None, ports=None):
    container = Mock()
    container.readiness_probe = readiness
    container.liveness_probe = liveness
    container.ports = ports or []
    return container


def _container_port(name, container_port):
    cp = Mock()
    cp.name = name
    cp.container_port = container_port
    return cp


def _pod(labels, containers):
    pod = Mock()
    pod.metadata.labels = labels
    pod.spec.containers = containers
    return pod


def _svc_port(port, target_port=None):
    sp = Mock()
    sp.port = port
    sp.target_port = target_port
    return sp


def _svc(
    name,
    svc_type="LoadBalancer",
    ip="1.2.3.4",
    hostname=None,
    selector=None,
    ports=None,
):
    svc = Mock()
    svc.metadata.name = name
    svc.spec.type = svc_type
    svc.spec.selector = selector
    svc.spec.ports = ports or []
    if ip or hostname:
        ingress = Mock(ip=ip, hostname=hostname)
        svc.status.load_balancer.ingress = [ingress]
    else:
        svc.status.load_balancer.ingress = []
    return svc


class TestRecommendHealthChecks:
    """Health-check endpoint discovery for LoadBalancer services."""

    @pytest.fixture
    def mock_krkn_k8s(self):
        mock_k8s = Mock()
        mock_k8s.cli = Mock()
        return mock_k8s

    @pytest.fixture
    def cluster_manager(self, mock_krkn_k8s):
        with patch(
            "krkn_ai.cluster.cluster_manager.KrknKubernetes",
            return_value=mock_krkn_k8s,
        ):
            return ClusterManager(kubeconfig="/tmp/test-kubeconfig")

    def _components(self):
        return ClusterComponents(namespaces=[Namespace(name="shop")])

    def _set(self, cluster_manager, services, pods):
        cluster_manager.core_api.list_namespaced_service.return_value.items = services
        cluster_manager.core_api.list_namespaced_pod.return_value.items = pods

    @patch.object(ClusterManager, "_check_reachable", return_value=True)
    def test_stitches_service_port_and_probe_path(self, _mock_reach, cluster_manager):
        """URL uses the service port that maps to the probe's container port."""
        svc = _svc("cart", selector={"app": "cart"}, ports=[_svc_port(80, 8080)])
        pod = _pod(
            {"app": "cart"},
            [_container(readiness=_probe(_http_get("/health", 8080)))],
        )
        self._set(cluster_manager, [svc], [pod])

        result = cluster_manager.recommend_health_checks(self._components())

        assert result == [
            {
                "name": "cart",
                "url": "http://1.2.3.4:80/health",
                "probe": True,
                "active": True,
            }
        ]

    @patch.object(ClusterManager, "_check_reachable", return_value=True)
    def test_falls_back_to_liveness_probe(self, _mock_reach, cluster_manager):
        """Liveness probe is used when there is no readiness probe."""
        svc = _svc("cart", selector={"app": "cart"}, ports=[_svc_port(80, 8080)])
        pod = _pod(
            {"app": "cart"},
            [_container(liveness=_probe(_http_get("/live", 8080)))],
        )
        self._set(cluster_manager, [svc], [pod])

        result = cluster_manager.recommend_health_checks(self._components())

        assert result[0]["url"] == "http://1.2.3.4:80/live"

    @patch.object(ClusterManager, "_check_reachable", return_value=True)
    def test_unmapped_probe_port_falls_back_to_root(self, _mock_reach, cluster_manager):
        """A probe port that no service port targets yields the root path."""
        svc = _svc("cart", selector={"app": "cart"}, ports=[_svc_port(80, 8080)])
        pod = _pod(
            {"app": "cart"},
            [_container(readiness=_probe(_http_get("/health", 9090)))],
        )
        self._set(cluster_manager, [svc], [pod])

        result = cluster_manager.recommend_health_checks(self._components())

        assert result[0]["url"] == "http://1.2.3.4:80/"

    @patch.object(ClusterManager, "_check_reachable", return_value=True)
    def test_named_probe_port_resolved_via_container(
        self, _mock_reach, cluster_manager
    ):
        """A named probe port is resolved through the container's ports."""
        svc = _svc("cart", selector={"app": "cart"}, ports=[_svc_port(80, 8080)])
        pod = _pod(
            {"app": "cart"},
            [
                _container(
                    readiness=_probe(_http_get("/health", "web")),
                    ports=[_container_port("web", 8080)],
                )
            ],
        )
        self._set(cluster_manager, [svc], [pod])

        result = cluster_manager.recommend_health_checks(self._components())

        assert result[0]["url"] == "http://1.2.3.4:80/health"

    @patch.object(ClusterManager, "_check_reachable", return_value=True)
    def test_scheme_taken_from_probe(self, _mock_reach, cluster_manager):
        """Scheme comes from the probe, even on a non-standard port."""
        svc = _svc("cart", selector={"app": "cart"}, ports=[_svc_port(9443, 8080)])
        pod = _pod(
            {"app": "cart"},
            [_container(readiness=_probe(_http_get("/health", 8080, scheme="HTTPS")))],
        )
        self._set(cluster_manager, [svc], [pod])

        result = cluster_manager.recommend_health_checks(self._components())

        assert result[0]["url"] == "https://1.2.3.4:9443/health"

    @patch.object(ClusterManager, "_check_reachable", return_value=True)
    def test_no_probe_sets_probe_false(self, _mock_reach, cluster_manager):
        """A service with no selector has probe=False."""
        svc = _svc("cart", selector=None, ports=[_svc_port(80, 8080)])
        self._set(cluster_manager, [svc], [])

        result = cluster_manager.recommend_health_checks(self._components())

        assert result[0]["probe"] is False
        assert result[0]["active"] is True

    @patch.object(ClusterManager, "_check_reachable", return_value=False)
    def test_unreachable_sets_active_false(self, _mock_reach, cluster_manager):
        """An unreachable endpoint has active=False."""
        svc = _svc("cart", selector={"app": "cart"}, ports=[_svc_port(80, 8080)])
        pod = _pod(
            {"app": "cart"},
            [_container(readiness=_probe(_http_get("/health", 8080)))],
        )
        self._set(cluster_manager, [svc], [pod])

        result = cluster_manager.recommend_health_checks(self._components())

        assert result[0]["probe"] is True
        assert result[0]["active"] is False

    @patch.object(ClusterManager, "_check_reachable", return_value=True)
    def test_probe_and_reachable_sets_both_true(self, _mock_reach, cluster_manager):
        """A service with probe and reachable endpoint has both flags True."""
        svc = _svc("cart", selector={"app": "cart"}, ports=[_svc_port(80, 8080)])
        pod = _pod(
            {"app": "cart"},
            [_container(readiness=_probe(_http_get("/health", 8080)))],
        )
        self._set(cluster_manager, [svc], [pod])

        result = cluster_manager.recommend_health_checks(self._components())

        assert result[0]["probe"] is True
        assert result[0]["active"] is True

    @patch.object(ClusterManager, "_check_reachable", return_value=False)
    def test_no_probe_unreachable_sets_both_false(self, _mock_reach, cluster_manager):
        """A probe-less unreachable service has both flags False."""
        svc = _svc("web", selector={"app": "web"}, ports=[_svc_port(8080, 8080)])
        pod = _pod({"app": "web"}, [_container()])
        self._set(cluster_manager, [svc], [pod])

        result = cluster_manager.recommend_health_checks(self._components())

        assert result[0]["probe"] is False
        assert result[0]["active"] is False

    @patch.object(ClusterManager, "_check_reachable", return_value=True)
    def test_ipv6_address_is_bracketed(self, _mock_reach, cluster_manager):
        """An IPv6 external address is wrapped in brackets in the URL."""
        svc = _svc(
            "cart",
            ip="2001:db8::1",
            selector={"app": "cart"},
            ports=[_svc_port(80, 8080)],
        )
        pod = _pod(
            {"app": "cart"},
            [_container(readiness=_probe(_http_get("/health", 8080)))],
        )
        self._set(cluster_manager, [svc], [pod])

        result = cluster_manager.recommend_health_checks(self._components())

        assert result[0]["url"] == "http://[2001:db8::1]:80/health"

    @patch.object(ClusterManager, "_check_reachable", return_value=True)
    def test_pending_load_balancer_is_skipped(self, _mock_reach, cluster_manager):
        """A LoadBalancer without an external address is skipped."""
        svc = _svc("cart", ip=None, hostname=None, ports=[_svc_port(80, 8080)])
        self._set(cluster_manager, [svc], [])

        assert cluster_manager.recommend_health_checks(self._components()) == []

    @patch.object(ClusterManager, "_check_reachable", return_value=True)
    def test_non_load_balancer_services_ignored(self, _mock_reach, cluster_manager):
        """ClusterIP services are not health-check candidates."""
        svc = _svc("cart", svc_type="ClusterIP", ports=[_svc_port(80, 8080)])
        self._set(cluster_manager, [svc], [])

        assert cluster_manager.recommend_health_checks(self._components()) == []

    def test_failure_returns_empty_list(self, cluster_manager):
        """A cluster read error never breaks discovery."""
        cluster_manager.core_api.list_namespaced_service.side_effect = RuntimeError(
            "boom"
        )

        assert cluster_manager.recommend_health_checks(self._components()) == []

    @patch.object(ClusterManager, "_check_reachable", return_value=True)
    def test_same_name_across_namespaces_all_kept(self, _mock_reach, cluster_manager):
        """Distinct services sharing a name across namespaces are all kept."""
        components = ClusterComponents(
            namespaces=[Namespace(name="shop"), Namespace(name="store")]
        )
        svc = _svc("cart", selector={"app": "cart"}, ports=[_svc_port(80, 8080)])
        pod = _pod(
            {"app": "cart"},
            [_container(readiness=_probe(_http_get("/health", 8080)))],
        )
        cluster_manager.core_api.list_namespaced_service.return_value.items = [svc]
        cluster_manager.core_api.list_namespaced_pod.return_value.items = [pod]

        result = cluster_manager.recommend_health_checks(components)

        assert len(result) == 2

    def test_check_reachable_returns_true_on_200(self):
        """_check_reachable returns True for a 200 response."""
        with patch("krkn_ai.cluster.cluster_manager.requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            assert ClusterManager._check_reachable("http://example.com") is True

    def test_check_reachable_returns_false_on_500(self):
        """_check_reachable returns False for a 500 response."""
        with patch("krkn_ai.cluster.cluster_manager.requests.get") as mock_get:
            mock_get.return_value.status_code = 500
            assert ClusterManager._check_reachable("http://example.com") is False

    def test_check_reachable_returns_false_on_connection_error(self):
        """_check_reachable returns False on connection failure."""
        with patch("krkn_ai.cluster.cluster_manager.requests.get") as mock_get:
            mock_get.side_effect = ConnectionError("refused")
            assert ClusterManager._check_reachable("http://example.com") is False
