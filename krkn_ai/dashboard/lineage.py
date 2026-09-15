"""Pure helpers for evolutionary lineage and mutation-impact analytics."""

from collections import defaultdict
from typing import Any, Dict, List


def build_lineage_edges(records: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """Return deduplicated parent-to-child edges with resolvable UUIDs."""
    known = {record.get("scenario_uuid") for record in records}
    edges = set()
    for child in records:
        child_uuid = child.get("scenario_uuid")
        if not child_uuid:
            continue
        for parent_uuid in child.get("parent_uuids") or []:
            if parent_uuid in known:
                edges.add((parent_uuid, child_uuid))
    return [
        {"parent_uuid": parent, "child_uuid": child}
        for parent, child in sorted(edges)
    ]


def summarize_mutation_impact(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Compare each child with the mean score of its known parents."""
    by_uuid = {record.get("scenario_uuid"): record for record in records}
    grouped = defaultdict(list)
    for child in records:
        mutation_type = child.get("mutation_type")
        parents = [by_uuid.get(parent) for parent in child.get("parent_uuids") or []]
        parents = [parent for parent in parents if parent is not None]
        if not mutation_type or not parents:
            continue
        parent_score = sum(float(parent.get("fitness_score", 0)) for parent in parents)
        parent_score /= len(parents)
        grouped[mutation_type].append(
            float(child.get("fitness_score", 0)) - parent_score
        )

    return [
        {
            "mutation_type": mutation_type,
            "samples": len(deltas),
            "average_fitness_delta": sum(deltas) / len(deltas),
        }
        for mutation_type, deltas in sorted(grouped.items())
    ]
