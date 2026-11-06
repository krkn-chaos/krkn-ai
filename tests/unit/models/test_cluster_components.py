"""
ClusterComponents model tests
"""

from krkn_ai.models.cluster_components import (
    ClusterComponents,
    Namespace,
    OwnerReference,
    Pod,
    Container,
    Service,
    ServicePort,
    PVC,
    Node,
)


class TestClusterComponents:
    """Test ClusterComponents model"""

    def test_cluster_components_creation(self):
        """Test ClusterComponents with empty lists and with data"""
        # Test empty cluster
        cluster_empty = ClusterComponents()
        assert cluster_empty.namespaces == []
        assert cluster_empty.nodes == []

        # Test cluster with data
        namespace = Namespace(
            name="test-namespace",
            pods=[
                Pod(
                    name="test-pod",
                    labels={"app": "test"},
                    containers=[Container(name="test-container")],
                )
            ],
            services=[
                Service(
                    name="test-service",
                    labels={"app": "test"},
                    ports=[ServicePort(port=8080, target_port=8080)],
                )
            ],
            pvcs=[
                PVC(
                    name="test-pvc",
                    labels={"storage": "fast"},
                    current_usage_percentage=75.5,
                )
            ],
        )
        node = Node(
            name="test-node",
            labels={"kubernetes.io/os": "linux"},
            free_cpu=4.0,
            free_mem=8.0,
            interfaces=["eth0", "eth1"],
            taints=["node-role.kubernetes.io/master"],
        )
        cluster = ClusterComponents(namespaces=[namespace], nodes=[node])
        assert len(cluster.namespaces) == 1
        assert len(cluster.nodes) == 1
        assert cluster.namespaces[0].name == "test-namespace"
        assert cluster.nodes[0].name == "test-node"


class TestNamespace:
    """Test Namespace model"""

    def test_namespace_creation(self):
        """Test Namespace with minimal fields and with all fields"""
        # Test minimal fields
        namespace_min = Namespace(name="test-ns")
        assert namespace_min.name == "test-ns"
        assert namespace_min.pods == []
        assert namespace_min.services == []
        assert namespace_min.pvcs == []

        # Test with all fields
        namespace = Namespace(
            name="test-ns",
            pods=[Pod(name="pod1"), Pod(name="pod2")],
            services=[Service(name="svc1")],
            pvcs=[PVC(name="pvc1")],
        )
        assert len(namespace.pods) == 2
        assert len(namespace.services) == 1
        assert len(namespace.pvcs) == 1


class TestPod:
    """Test Pod model"""

    def test_pod_creation(self):
        """Test Pod with minimal fields and with labels and containers"""
        # Test minimal fields
        pod_min = Pod(name="test-pod")
        assert pod_min.name == "test-pod"
        assert pod_min.labels == {}
        assert pod_min.containers == []

        # Test with labels and containers
        pod = Pod(
            name="test-pod",
            labels={"app": "web", "version": "1.0"},
            containers=[Container(name="container1"), Container(name="container2")],
        )
        assert pod.labels["app"] == "web"
        assert len(pod.containers) == 2


class TestService:
    """Test Service model"""

    def test_service_creation(self):
        """Test Service with minimal fields and with ports"""
        # Test minimal fields
        service_min = Service(name="test-service")
        assert service_min.name == "test-service"
        assert service_min.labels == {}
        assert service_min.ports == []

        # Test with ports
        service = Service(
            name="test-service",
            ports=[
                ServicePort(port=80, target_port=8080, protocol="TCP"),
                ServicePort(port=443, target_port="8443", protocol="TCP"),
            ],
        )
        assert len(service.ports) == 2
        assert service.ports[0].port == 80
        assert service.ports[0].target_port == 8080
        assert service.ports[1].target_port == "8443"


class TestNode:
    """Test Node model"""

    def test_node_creation(self):
        """Test Node with minimal fields and with all fields"""
        # Test minimal fields
        node_min = Node(name="test-node")
        assert node_min.name == "test-node"
        assert node_min.labels == {}
        assert node_min.free_cpu == 0
        assert node_min.free_mem == 0
        assert node_min.interfaces == []
        assert node_min.taints == []

        # Test with all fields
        node = Node(
            name="test-node",
            labels={"kubernetes.io/os": "linux", "node-role": "worker"},
            free_cpu=4.0,
            free_mem=8.0,
            interfaces=["eth0", "eth1"],
            taints=["node-role.kubernetes.io/master:NoSchedule"],
        )
        assert node.free_cpu == 4.0
        assert node.free_mem == 8.0
        assert len(node.interfaces) == 2
        assert len(node.taints) == 1


class TestPVC:
    """Test PVC model"""

    def test_pvc_creation(self):
        """Test PVC with minimal fields and with usage percentage"""
        # Test minimal fields
        pvc_min = PVC(name="test-pvc")
        assert pvc_min.name == "test-pvc"
        assert pvc_min.labels == {}
        assert pvc_min.current_usage_percentage is None

        # Test with usage percentage
        pvc = PVC(name="test-pvc", current_usage_percentage=85.5)
        assert pvc.current_usage_percentage == 85.5


class TestActiveComponentsContainers:
    """get_active_components must drop containers marked ``disabled: true``."""

    def _cluster(self):
        pod = Pod(
            name="cart-1",
            labels={"service": "cart"},
            containers=[
                Container(name="cart"),
                Container(name="istio-proxy", disabled=True),
            ],
        )
        return ClusterComponents(namespaces=[Namespace(name="shop", pods=[pod])])

    def test_disabled_container_is_filtered_out(self):
        active = self._cluster().get_active_components()
        names = [c.name for c in active.namespaces[0].pods[0].containers]
        assert names == ["cart"]

    def test_filters_every_pod_and_namespace_and_keeps_other_fields(self):
        """All disabled containers go, in every pod and namespace. A pod with
        only disabled containers stays for pod-level scenarios, a disabled pod
        does not, and the rest of a filtered pod is kept."""
        owner = OwnerReference(kind="Deployment", name="cart")
        cluster = ClusterComponents(
            namespaces=[
                Namespace(
                    name="shop",
                    pods=[
                        Pod(name="plain", containers=[Container(name="app")]),
                        Pod(
                            name="sidecars",
                            labels={"service": "cart"},
                            owner=owner,
                            containers=[
                                Container(name="cart"),
                                Container(name="istio-proxy", disabled=True),
                                Container(name="fluentd", disabled=True),
                            ],
                        ),
                        Pod(
                            name="all-off",
                            containers=[Container(name="job", disabled=True)],
                        ),
                        Pod(name="off", disabled=True),
                    ],
                ),
                Namespace(
                    name="pay",
                    pods=[
                        Pod(
                            name="ledger",
                            containers=[
                                Container(name="db", disabled=True),
                                Container(name="api"),
                            ],
                        )
                    ],
                ),
            ]
        )

        active = cluster.get_active_components()

        result = {
            ns.name: {p.name: [c.name for c in p.containers] for p in ns.pods}
            for ns in active.namespaces
        }
        assert result == {
            "shop": {"plain": ["app"], "sidecars": ["cart"], "all-off": []},
            "pay": {"ledger": ["api"]},
        }
        sidecars = active.namespaces[0].pods[1]
        assert sidecars.owner == owner
        assert sidecars.labels == {"service": "cart"}

    def test_original_components_are_not_modified(self):
        cluster = self._cluster()
        cluster.get_active_components()
        names = [c.name for c in cluster.namespaces[0].pods[0].containers]
        assert names == ["cart", "istio-proxy"]
