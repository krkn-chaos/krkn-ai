"""
Unit tests for the node_selector utility module.
"""

import json
import pytest

from krkn_ai.models.cluster_components import Node
from krkn_ai.models.custom_errors import ScenarioParameterInitError
from krkn_ai.utils.node_selector import (
    NodeSelectionResult,
    build_label_counter,
    collect_unique_taints,
    get_nodes_matching_label,
    select_nodes,
)


class TestCollectUniqueTaints:
    """Tests for collect_unique_taints function"""

    def test_collects_taints_from_single_node(self):
        """Test collecting taints from a single node"""
        nodes = [Node(name="node1", taints=["NoSchedule:key=val"])]
        result = collect_unique_taints(nodes)
        assert result == ["NoSchedule:key=val"]

    def test_deduplicates_taints_across_nodes(self):
        """Test that duplicate taints are removed"""
        nodes = [
            Node(name="node1", taints=["NoSchedule:key=val"]),
            Node(name="node2", taints=["NoSchedule:key=val", "NoExecute:other=val"]),
        ]
        result = collect_unique_taints(nodes)
        assert len(result) == 2
        assert "NoSchedule:key=val" in result
        assert "NoExecute:other=val" in result

    def test_preserves_order_of_first_occurrence(self):
        """Test that taints are returned in order of first occurrence"""
        nodes = [
            Node(name="node1", taints=["taint-a", "taint-b"]),
            Node(name="node2", taints=["taint-c", "taint-a"]),
        ]
        result = collect_unique_taints(nodes)
        assert result == ["taint-a", "taint-b", "taint-c"]

    def test_handles_empty_nodes_list(self):
        """Test with no nodes"""
        assert collect_unique_taints([]) == []

    def test_handles_nodes_without_taints(self):
        """Test with nodes that have no taints"""
        nodes = [Node(name="node1", taints=[]), Node(name="node2", taints=[])]
        assert collect_unique_taints(nodes) == []


class TestBuildLabelCounter:
    """Tests for build_label_counter function"""

    def test_counts_labels_correctly(self):
        """Test that labels are counted correctly"""
        nodes = [
            Node(name="node1", labels={"env": "prod", "zone": "us-west"}),
            Node(name="node2", labels={"env": "prod", "zone": "us-east"}),
            Node(name="node3", labels={"env": "dev"}),
        ]
        result = build_label_counter(nodes)
        assert result["env=prod"] == 2
        assert result["env=dev"] == 1
        assert result["zone=us-west"] == 1
        assert result["zone=us-east"] == 1

    def test_handles_empty_nodes_list(self):
        """Test with no nodes"""
        result = build_label_counter([])
        assert len(result) == 0

    def test_handles_nodes_without_labels(self):
        """Test with nodes that have no labels"""
        nodes = [Node(name="node1", labels={})]
        result = build_label_counter(nodes)
        assert len(result) == 0


class TestGetNodesMatchingLabel:
    """Tests for get_nodes_matching_label function"""

    def test_returns_matching_nodes(self):
        """Test that correct nodes are returned"""
        nodes = [
            Node(name="node1", labels={"env": "prod"}),
            Node(name="node2", labels={"env": "prod"}),
            Node(name="node3", labels={"env": "dev"}),
        ]
        result = get_nodes_matching_label(nodes, "env=prod")
        assert len(result) == 2
        assert all(n.labels["env"] == "prod" for n in result)

    def test_returns_empty_list_when_no_match(self):
        """Test with no matching nodes"""
        nodes = [Node(name="node1", labels={"env": "dev"})]
        result = get_nodes_matching_label(nodes, "env=prod")
        assert result == []

    def test_handles_label_with_equals_in_value(self):
        """Test labels where value contains equals sign"""
        nodes = [Node(name="node1", labels={"key": "val=ue"})]
        result = get_nodes_matching_label(nodes, "key=val=ue")
        assert len(result) == 1


class TestSelectNodes:
    """Tests for select_nodes function"""

    def test_raises_error_on_empty_nodes(self):
        """Test that ScenarioParameterInitError is raised for empty nodes"""
        with pytest.raises(ScenarioParameterInitError, match="No nodes found"):
            select_nodes([], scenario_name="test-scenario")

    def test_includes_scenario_name_in_error(self):
        """Test that error message includes the scenario name"""
        with pytest.raises(ScenarioParameterInitError, match="my-scenario"):
            select_nodes([], scenario_name="my-scenario")

    def test_returns_node_selection_result(self):
        """Test that result is a NodeSelectionResult"""
        nodes = [Node(name="node1", labels={"env": "prod"})]
        result = select_nodes(nodes)
        assert isinstance(result, NodeSelectionResult)

    def test_result_has_valid_node_selector(self):
        """Test that node_selector is a non-empty string"""
        nodes = [Node(name="node1", labels={"env": "prod"})]
        result = select_nodes(nodes)
        assert isinstance(result.node_selector, str)
        assert len(result.node_selector) > 0

    def test_result_has_valid_number_of_nodes(self):
        """Test that number_of_nodes is a positive integer"""
        nodes = [Node(name="node1", labels={"env": "prod"})]
        result = select_nodes(nodes)
        assert result.number_of_nodes >= 1

    def test_result_has_valid_json_taints(self):
        """Test that taints_json is valid JSON"""
        nodes = [Node(name="node1", labels={"env": "prod"}, taints=["taint1"])]
        result = select_nodes(nodes)
        parsed = json.loads(result.taints_json)
        assert isinstance(parsed, list)

    def test_single_node_selection_returns_hostname_selector(self):
        """Test that single node selection uses kubernetes.io/hostname"""
        nodes = [Node(name="my-node", labels={})]  # No labels forces hostname selection
        result = select_nodes(nodes)
        assert result.node_selector == "kubernetes.io/hostname=my-node"
        assert result.number_of_nodes == 1

    def test_single_node_selection_includes_node_taints(self):
        """Test that single node selection includes the node's taints"""
        nodes = [Node(name="node1", labels={}, taints=["NoSchedule:key=val"])]
        result = select_nodes(nodes)
        taints = json.loads(result.taints_json)
        assert "NoSchedule:key=val" in taints

    def test_empty_taints_returns_empty_json_array(self):
        """Test that empty taints returns '[]'"""
        nodes = [Node(name="node1", labels={}, taints=[])]
        result = select_nodes(nodes)
        assert result.taints_json == "[]"
