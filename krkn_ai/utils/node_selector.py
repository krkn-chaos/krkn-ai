"""
Node selection utilities for chaos engineering scenarios.

This module provides reusable functions for selecting nodes by hostname or label,
collecting unique taints, and building node selector strings for Kubernetes.
"""

import json
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, List

from krkn_ai.models.custom_errors import ScenarioParameterInitError
from krkn_ai.utils.rng import rng

if TYPE_CHECKING:
    from krkn_ai.models.cluster_components import Node


@dataclass
class NodeSelectionResult:
    """Result of node selection containing selector, count, and taints."""

    node_selector: str
    number_of_nodes: int
    taints_json: str


def collect_unique_taints(nodes: List["Node"]) -> List[str]:
    """
    Collect unique taints from a list of nodes, preserving order.

    Args:
        nodes: List of Node objects to collect taints from.

    Returns:
        List of unique taint strings in order of first occurrence.
    """
    seen = set()
    unique_taints = []
    for node in nodes:
        if node.taints:
            for taint in node.taints:
                if taint not in seen:
                    seen.add(taint)
                    unique_taints.append(taint)
    return unique_taints


def build_label_counter(nodes: List["Node"]) -> Counter:
    """
    Build a Counter of all label=value pairs across nodes.

    Args:
        nodes: List of Node objects to analyze.

    Returns:
        Counter mapping "label=value" strings to their frequency.
    """
    all_labels: Counter = Counter()
    for node in nodes:
        for label, value in node.labels.items():
            all_labels[f"{label}={value}"] += 1
    return all_labels


def get_nodes_matching_label(nodes: List["Node"], label_selector: str) -> List["Node"]:
    """
    Get all nodes matching a label=value selector.

    Args:
        nodes: List of Node objects to filter.
        label_selector: String in "key=value" format.

    Returns:
        List of nodes where labels[key] == value.
    """
    key, value = label_selector.split("=", 1)
    return [n for n in nodes if n.labels.get(key) == value]


def select_nodes(nodes: List["Node"], scenario_name: str = "node-hog") -> NodeSelectionResult:
    """
    Randomly select nodes by hostname or by label.

    This function implements a random selection strategy:
    - 50% chance: Select a single node by its hostname
    - 50% chance: Select nodes by a random label (if labels exist)

    Args:
        nodes: List of available Node objects.
        scenario_name: Name of the scenario for error messages.

    Returns:
        NodeSelectionResult containing:
            - node_selector: Kubernetes node selector string
            - number_of_nodes: Count of nodes to target
            - taints_json: JSON string of deduplicated taints

    Raises:
        ScenarioParameterInitError: If the nodes list is empty.
    """
    if not nodes:
        raise ScenarioParameterInitError(
            f"No nodes found in cluster components for {scenario_name} scenario"
        )

    all_labels = build_label_counter(nodes)

    # Strategy: 50% single node by hostname, 50% by label (if labels available)
    select_by_hostname = rng.random() < 0.5 or len(all_labels) == 0

    if select_by_hostname:
        node = rng.choice(nodes)
        return NodeSelectionResult(
            node_selector=f"kubernetes.io/hostname={node.name}",
            number_of_nodes=1,
            taints_json=json.dumps(node.taints) if node.taints else "[]",
        )

    # Select by label
    label = rng.choice(list(all_labels.keys()))
    matching_nodes = get_nodes_matching_label(nodes, label)
    unique_taints = collect_unique_taints(matching_nodes)

    return NodeSelectionResult(
        node_selector=label,
        number_of_nodes=rng.randint(1, all_labels[label]),
        taints_json=json.dumps(unique_taints) if unique_taints else "[]",
    )
