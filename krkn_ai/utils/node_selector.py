"""
Node selection utilities for chaos scenarios.

Provides helper functions for selecting nodes based on labels and collecting
their metadata.
"""

import json
from collections import Counter
from dataclasses import dataclass
from typing import List, Set, Optional
from krkn_ai.models.cluster_components import Node
from krkn_ai.utils.rng import rng
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class NodeSelectionResult:
    """Result of node selection operation."""

    node_selector: str  # e.g., "kubernetes.io/hostname=node-1" or "disktype=ssd"
    number_of_nodes: int
    taints_json: str  # JSON string of taint list
    matching_nodes: List[Node]  # Actual nodes matching the selector


def select_nodes(nodes: List[Node]) -> NodeSelectionResult:
    """
    Select nodes for chaos injection using two strategies randomly.

    Randomly chooses between:
    1. Selecting a single random node (50% probability)
    2. Selecting a label/value combo and all matching nodes (50% probability)

    Args:
        nodes: List of available nodes in the cluster

    Returns:
        NodeSelectionResult with node selector, count, taints, and matched nodes

    Raises:
        ValueError: If nodes list is empty
    """
    if not nodes:
        raise ValueError("No nodes available for selection")

    all_labels: Counter[str] = Counter()
    for node in nodes:
        for label_key, label_value in node.labels.items():
            all_labels[f"{label_key}={label_value}"] += 1

    logger.debug(
        f"Found {len(all_labels)} unique label combinations across {len(nodes)} nodes"
    )

    # Strategy 1: Random node selection (50% probability, or if no labels available)
    if rng.random() < 0.5 or not all_labels:
        if not all_labels:
            logger.debug("No node labels found, using random node selection")

        selected_node = rng.choice(nodes)
        node_selector = f"kubernetes.io/hostname={selected_node.name}"
        number_of_nodes = 1
        taints_json = _serialize_taints(selected_node.taints)
        matching_nodes = [selected_node]

        logger.debug(f"Selected random node: {selected_node.name}")
    else:
        # Strategy 2: Label/value selection
        selected_label = rng.choice(list(all_labels.keys()))
        node_selector = selected_label
        label_key, label_value = selected_label.split("=", 1)

        all_matching_nodes = [
            n for n in nodes if n.labels.get(label_key) == label_value
        ]

        count = rng.randint(1, len(all_matching_nodes))
        selected_nodes = rng.sample(all_matching_nodes, k=count)

        taints_json = _collect_taints_from_nodes(selected_nodes)

        logger.debug(
            f"Selected label {selected_label}: "
            f"found {len(all_matching_nodes)} matching nodes, "
            f"selecting {count}"
        )

        matching_nodes = selected_nodes
        number_of_nodes = count

    return NodeSelectionResult(
        node_selector=node_selector,
        number_of_nodes=number_of_nodes,
        taints_json=taints_json,
        matching_nodes=matching_nodes,
    )


def _serialize_taints(taints: Optional[List[str]]) -> str:
    """Convert taints list to JSON string."""
    return json.dumps(taints if taints else [])


def _collect_taints_from_nodes(nodes: List[Node]) -> str:
    """
    Collect unique taints from multiple nodes.

    Args:
        nodes: List of nodes to collect taints from

    Returns:
        JSON string representation of deduplicated taints
    """
    seen_taints_json: Set[str] = set()
    all_taints: List = []

    for node in nodes:
        if node.taints:
            for taint in node.taints:
                taint_json = json.dumps(taint, sort_keys=True)
                if taint_json not in seen_taints_json:
                    seen_taints_json.add(taint_json)
                    all_taints.append(taint)

    return json.dumps(all_taints)
