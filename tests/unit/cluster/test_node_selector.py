import json
from unittest.mock import patch

import pytest

from krkn_ai.cluster import select_nodes
from krkn_ai.models.cluster_components import Node

CONTROL_PLANE_TAINT = "node-role.kubernetes.io/control-plane:NoSchedule"


@pytest.fixture
def nodes():
    common = {"kubernetes.io/os": "linux"}
    return [
        Node(
            name="control-plane",
            labels={**common, "kubernetes.io/hostname": "control-plane"},
            taints=[CONTROL_PLANE_TAINT],
        ),
        Node(name="worker-1", labels={**common, "kubernetes.io/hostname": "worker-1"}),
        Node(name="worker-2", labels={**common, "kubernetes.io/hostname": "worker-2"}),
    ]


def _select_by_label(nodes, label, count, sample):
    """Force the label strategy with a given label, count and sampled nodes."""
    with patch("krkn_ai.cluster.node_selector.rng") as rng:
        rng.random.return_value = 0.9
        rng.choice.return_value = label
        rng.randint.return_value = count
        rng.sample.return_value = sample
        return select_nodes(nodes)


class TestSelectNodesTaints:
    def test_label_subset_tolerates_taints_of_every_matching_node(self, nodes):
        """krkn picks its own subset of matching nodes, so a sampled subset
        without the tainted node must still pass that node's taint."""
        result = _select_by_label(nodes, "kubernetes.io/os=linux", 1, [nodes[1]])

        assert result.node_selector == "kubernetes.io/os=linux"
        assert result.number_of_nodes == 1
        assert json.loads(result.taints_json) == [CONTROL_PLANE_TAINT]

    def test_label_only_collects_taints_of_matching_nodes(self, nodes):
        nodes[1].labels["disktype"] = "ssd"
        nodes[2].labels["disktype"] = "ssd"

        result = _select_by_label(nodes, "disktype=ssd", 1, [nodes[1]])

        assert json.loads(result.taints_json) == []

    def test_single_node_uses_that_node_taints(self, nodes):
        with patch("krkn_ai.cluster.node_selector.rng") as rng:
            rng.random.return_value = 0.1
            rng.choice.return_value = nodes[0]
            result = select_nodes(nodes)

        assert result.node_selector == "kubernetes.io/hostname=control-plane"
        assert json.loads(result.taints_json) == [CONTROL_PLANE_TAINT]


class TestSelectNodesDisabled:
    def test_disabled_nodes_labels_are_excluded(self):
        worker1 = Node(
            name="w-0",
            labels={"kubernetes.io/os": "linux", "role": "worker"},
        )
        worker2 = Node(
            name="w-1",
            labels={"kubernetes.io/os": "linux", "role": "worker"},
        )
        disabled_cp = Node(
            name="cp-0",
            labels={"kubernetes.io/os": "linux", "role": "control-plane"},
            disabled=True,
        )

        with patch("krkn_ai.cluster.node_selector.rng") as rng:
            rng.random.return_value = 0.9  # Force label strategy
            rng.choice.side_effect = lambda seq: seq[0]
            rng.randint.return_value = 1
            rng.sample.return_value = [worker1]

            result = select_nodes([worker1, worker2], disabled_nodes=[disabled_cp])

        # "kubernetes.io/os=linux" is shared with disabled node, so it must be excluded
        assert result.node_selector == "role=worker"

    def test_all_labels_disabled_falls_back_to_hostname(self):
        worker1 = Node(
            name="w-0",
            labels={"kubernetes.io/os": "linux"},
        )
        worker2 = Node(
            name="w-1",
            labels={"kubernetes.io/os": "linux"},
        )
        disabled_cp = Node(
            name="cp-0",
            labels={"kubernetes.io/os": "linux"},
            disabled=True,
        )

        with patch("krkn_ai.cluster.node_selector.rng") as rng:
            rng.random.return_value = 0.9  # Try label strategy
            rng.choice.return_value = worker1

            result = select_nodes([worker1, worker2], disabled_nodes=[disabled_cp])

        # All labels match disabled node; must fall back to hostname
        assert result.node_selector == "kubernetes.io/hostname=w-0"

    def test_hostname_strategy_uses_hostname_label_if_different_from_name(self):
        worker = Node(
            name="worker-uuid-1234",
            labels={"kubernetes.io/hostname": "custom-worker-host"},
        )
        with patch("krkn_ai.cluster.node_selector.rng") as rng:
            rng.random.return_value = 0.1  # Strategy 1 (single node)
            rng.choice.return_value = worker
            result = select_nodes([worker])

        assert result.node_selector == "kubernetes.io/hostname=custom-worker-host"
