import pytest
from unittest.mock import patch
from krkn_ai.models.scenario.base import is_system_namespace
from krkn_ai.utils.node_selector import is_control_plane_node, select_nodes
from krkn_ai.models.scenario.scenario_pod import PodScenario
from krkn_ai.models.scenario.scenario_container import ContainerScenario
from krkn_ai.models.scenario.scenario_app_outage import AppOutageScenario
from krkn_ai.models.scenario.scenario_pvc import PVCScenario
from krkn_ai.models.scenario.scenario_dns_outage import DnsOutageScenario
from krkn_ai.models.scenario.scenario_syn_flood import SynFloodScenario
from krkn_ai.models.scenario.scenario_network import NetworkScenario
from krkn_ai.models.scenario.scenario_time import TimeScenario
from krkn_ai.models.scenario.scenario_kubevirt import KubevirtDisruptionScenario
from krkn_ai.models.custom_errors import ScenarioParameterInitError
from krkn_ai.models.cluster_components import VMI
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


def test_is_system_namespace():
    assert is_system_namespace("kube-system")
    assert is_system_namespace("kube-public")
    assert is_system_namespace("openshift-apiserver")
    assert is_system_namespace("openshift")
    assert is_system_namespace("kubernetes-dashboard")
    assert not is_system_namespace("default")
    assert not is_system_namespace("my-app")


def test_is_control_plane_node():
    master_node = Node(
        name="master-node-0",
        labels={"node-role.kubernetes.io/master": "true"},
        taints=["node-role.kubernetes.io/master:NoSchedule"],
    )
    control_plane_node = Node(
        name="k8s-control-plane",
        labels={"node-role.kubernetes.io/control-plane": ""},
        taints=[],
    )
    worker_node = Node(
        name="worker-node-1",
        labels={"node-role.kubernetes.io/worker": "true"},
        taints=[],
    )

    assert is_control_plane_node(master_node)
    assert is_control_plane_node(control_plane_node)
    assert not is_control_plane_node(worker_node)


def test_select_nodes_filters_control_plane():
    master = Node(name="master-1", labels={"node-role.kubernetes.io/master": "true"})
    worker = Node(name="worker-1", labels={"node-role.kubernetes.io/worker": "true"})

    # When both exist, it selects only the worker
    result = select_nodes([master, worker])
    assert len(result.matching_nodes) == 1
    assert result.matching_nodes[0].name == "worker-1"

    # When only master exists, it raises ValueError
    with pytest.raises(
        ValueError, match="No non-control-plane nodes available for selection"
    ):
        select_nodes([master])


def test_pod_scenario_excludes_system_namespaces():
    user_pod = Pod(name="user-pod", labels={"app": "user"})
    system_pod = Pod(name="system-pod", labels={"app": "system"})
    user_ns = Namespace(name="user-ns", pods=[user_pod])
    system_ns = Namespace(name="kube-system", pods=[system_pod])

    cluster = ClusterComponents(namespaces=[user_ns, system_ns], nodes=[])
    scenario = PodScenario(cluster_components=cluster)
    assert scenario.namespace.value == "user-ns"

    cluster_fallback = ClusterComponents(namespaces=[system_ns], nodes=[])
    with pytest.raises(ScenarioParameterInitError):
        PodScenario(cluster_components=cluster_fallback)


def test_container_scenario_excludes_system_namespaces():
    user_pod = Pod(
        name="user-pod", labels={"app": "user"}, containers=[Container(name="c1")]
    )
    system_pod = Pod(
        name="system-pod", labels={"app": "system"}, containers=[Container(name="c2")]
    )
    user_ns = Namespace(name="user-ns", pods=[user_pod])
    system_ns = Namespace(name="kube-system", pods=[system_pod])

    cluster = ClusterComponents(namespaces=[user_ns, system_ns], nodes=[])
    scenario = ContainerScenario(cluster_components=cluster)
    assert scenario.namespace.value == "user-ns"

    cluster_fallback = ClusterComponents(namespaces=[system_ns], nodes=[])
    with pytest.raises(ScenarioParameterInitError):
        ContainerScenario(cluster_components=cluster_fallback)


def test_app_outage_scenario_excludes_system_namespaces():
    user_pod = Pod(name="user-pod", labels={"app": "user"})
    system_pod = Pod(name="system-pod", labels={"app": "system"})
    user_ns = Namespace(name="user-ns", pods=[user_pod])
    system_ns = Namespace(name="kube-system", pods=[system_pod])

    cluster = ClusterComponents(namespaces=[user_ns, system_ns], nodes=[])
    scenario = AppOutageScenario(cluster_components=cluster)
    assert scenario.namespace.value == "user-ns"

    cluster_fallback = ClusterComponents(namespaces=[system_ns], nodes=[])
    with pytest.raises(ScenarioParameterInitError):
        AppOutageScenario(cluster_components=cluster_fallback)


@patch("krkn_ai.models.scenario.scenario_pvc.get_pvc_usage_percentage")
def test_pvc_scenario_excludes_system_namespaces(mock_get_usage):
    mock_get_usage.return_value = None
    user_pvc = PVC(name="user-pvc", labels={})
    system_pvc = PVC(name="system-pvc", labels={})
    user_ns = Namespace(name="user-ns", pvcs=[user_pvc])
    system_ns = Namespace(name="kube-system", pvcs=[system_pvc])

    cluster = ClusterComponents(namespaces=[user_ns, system_ns], nodes=[])
    scenario = PVCScenario(cluster_components=cluster)
    assert scenario.namespace.value == "user-ns"

    cluster_fallback = ClusterComponents(namespaces=[system_ns], nodes=[])
    with pytest.raises(ScenarioParameterInitError):
        PVCScenario(cluster_components=cluster_fallback)


def test_dns_outage_scenario_excludes_system_namespaces():
    user_pod = Pod(name="user-pod", labels={"app": "user"})
    system_pod = Pod(name="system-pod", labels={"app": "system"})
    user_ns = Namespace(name="user-ns", pods=[user_pod])
    system_ns = Namespace(name="kube-system", pods=[system_pod])

    cluster = ClusterComponents(namespaces=[user_ns, system_ns], nodes=[])
    scenario = DnsOutageScenario(cluster_components=cluster)
    assert scenario.namespace.value == "user-ns"

    cluster_fallback = ClusterComponents(namespaces=[system_ns], nodes=[])
    with pytest.raises(ScenarioParameterInitError):
        DnsOutageScenario(cluster_components=cluster_fallback)


def test_syn_flood_scenario_excludes_system_namespaces():
    user_service = Service(name="user-service", ports=[ServicePort(port=80)])
    system_service = Service(name="system-service", ports=[ServicePort(port=80)])
    user_ns = Namespace(name="user-ns", services=[user_service])
    system_ns = Namespace(name="kube-system", services=[system_service])

    cluster = ClusterComponents(namespaces=[user_ns, system_ns], nodes=[])
    scenario = SynFloodScenario(cluster_components=cluster)
    assert scenario.namespace.value == "user-ns"

    cluster_fallback = ClusterComponents(namespaces=[system_ns], nodes=[])
    with pytest.raises(ScenarioParameterInitError):
        SynFloodScenario(cluster_components=cluster_fallback)


def test_network_scenario_excludes_control_plane():
    master = Node(name="master-1", interfaces=["eth0"])
    # Mock is_control_plane_node to return True for master-1
    with patch("krkn_ai.utils.node_selector.is_control_plane_node") as mock_is_cp:
        mock_is_cp.side_effect = lambda n: n.name == "master-1"
        worker = Node(name="worker-1", interfaces=["eth0"])

        cluster = ClusterComponents(namespaces=[], nodes=[master, worker])
        scenario = NetworkScenario(cluster_components=cluster)
        assert scenario.node_name.value == "worker-1"

        cluster_fallback = ClusterComponents(namespaces=[], nodes=[master])
        with pytest.raises(ScenarioParameterInitError):
            NetworkScenario(cluster_components=cluster_fallback)


def test_time_scenario_excludes_control_plane_node_labels():
    master = Node(
        name="master-1",
        labels={"kubernetes.io/hostname": "master-1", "node-role": "master"},
    )
    worker = Node(
        name="worker-1",
        labels={"kubernetes.io/hostname": "worker-1", "node-role": "worker"},
    )

    with (
        patch("krkn_ai.utils.node_selector.is_control_plane_node") as mock_is_cp,
        patch(
            "krkn_ai.models.scenario.parameters.ObjectTypeParameter.mutate",
            lambda self: setattr(self, "value", "node"),
        ),
    ):
        mock_is_cp.side_effect = lambda n: n.name == "master-1"
        # Mock active component namespaces/pods
        user_pod = Pod(name="user-pod", labels={"app": "user"})
        user_ns = Namespace(name="user-ns", pods=[user_pod])
        cluster = ClusterComponents(namespaces=[user_ns], nodes=[master, worker])

        scenario = TimeScenario(cluster_components=cluster)
        # When both nodes exist, worker node labels are targeted (e.g. node-role=worker or hostname=worker-1)
        assert "worker" in scenario.label_selector.value

        # When only master exists, it cannot target master nodes, so it targets pods
        cluster_fallback = ClusterComponents(namespaces=[user_ns], nodes=[master])
        scenario_fallback = TimeScenario(cluster_components=cluster_fallback)
        assert scenario_fallback.object_type.value == "pod"
        assert scenario_fallback.label_selector.value == "app=user"

        # When only master exists and no pods are available, it raises ScenarioParameterInitError
        cluster_fallback_no_pods = ClusterComponents(namespaces=[], nodes=[master])
        with pytest.raises(ScenarioParameterInitError):
            TimeScenario(cluster_components=cluster_fallback_no_pods)


def test_kubevirt_scenario_excludes_system_namespaces():
    user_vmi = VMI(name="user-vm")
    system_vmi = VMI(name="system-vm")
    user_ns = Namespace(name="user-ns", vmis=[user_vmi])
    system_ns = Namespace(name="kube-system", vmis=[system_vmi])

    cluster = ClusterComponents(namespaces=[user_ns, system_ns], nodes=[])
    scenario = KubevirtDisruptionScenario(cluster_components=cluster)
    assert scenario.namespace.value == "user-ns"

    cluster_fallback = ClusterComponents(namespaces=[system_ns], nodes=[])
    with pytest.raises(ScenarioParameterInitError):
        KubevirtDisruptionScenario(cluster_components=cluster_fallback)
