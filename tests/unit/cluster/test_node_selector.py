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
