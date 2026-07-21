"""Catalog of PromQL fitness queries and a recommender that adapts them per cluster."""

import os
from enum import Enum
from typing import Dict, List, Optional, Union

import yaml
from pydantic import BaseModel

from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.config import FitnessFunctionItem, FitnessFunctionType
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)

_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "catalog.yaml")
_VALIDATION_RANGE = "5m"


class FitnessCategory(str, Enum):
    availability = "availability"
    resource = "resource"
    node = "node"
    control_plane = "control_plane"


class Scope(str, Enum):
    namespace = "namespace"  # filtered by a discovered namespace ($ns)
    cluster = "cluster"  # cluster-wide


class CatalogEntry(BaseModel):
    """A fitness query template, where $ns is a namespace and $range$ the run window."""

    key: str
    query_template: str
    category: Optional[FitnessCategory] = None
    name: Optional[str] = None
    type: FitnessFunctionType = FitnessFunctionType.range
    requires: List[str] = []
    scope: Scope = Scope.namespace
    default_weight: float = 1.0  # seed used when there's no learned weight

    def resolved_query(self, namespace: Optional[str] = None) -> str:
        """Fill $ns; $range$ is left for the runtime executor."""
        if namespace:
            return self.query_template.replace("$ns", namespace)
        return self.query_template

    def to_fitness_item(self, namespace: Optional[str] = None) -> FitnessFunctionItem:
        return FitnessFunctionItem(
            query=self.resolved_query(namespace),
            type=self.type,
            weight=self.default_weight,
        )


def _load_catalog() -> List[CatalogEntry]:
    with open(_CATALOG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return [CatalogEntry.model_validate(e) for e in data]


BASE_CATALOG: List[CatalogEntry] = _load_catalog()


def get_base_catalog() -> List[CatalogEntry]:
    """Return the base fitness-function catalog."""
    return BASE_CATALOG


# Dynamic layer: adapt the catalog to a live cluster


def _safe_query(query: str) -> str:
    # `or vector(0)` returns 0 when nothing matches
    return f"({query}) or vector(0)"


def _validate_shape(prom_client, query: str) -> tuple:
    """Run the query and keep it if it returns 0 or 1 series. Returns (enabled, reason)."""
    runnable = query.replace("$range$", _VALIDATION_RANGE)
    try:
        result = prom_client.process_query(runnable) or []
    except Exception as error:
        return False, f"query failed to run: {error}"
    if len(result) > 1:
        return False, f"returns {len(result)} series, needs aggregation (sum/max/avg)"
    return True, ""


def _assign_weights(enabled: List[dict]) -> None:
    """Normalize seed weights across enabled items (equal when all are default)."""
    total = sum(r["weight"] for r in enabled)
    if total <= 0:
        return
    for r in enabled:
        r["weight"] = round(r["weight"] / total, 4)


def recommend_fitness_queries(
    components: ClusterComponents, prom_client, learned_weights: dict = None
) -> List[Dict[str, Union[str, bool, float]]]:
    """Suggest fitness queries the cluster can run, seeded by learned_weights if given."""
    learned_weights = learned_weights or {}
    try:
        available = set(prom_client.prom_cli.all_metrics())
    except Exception as error:
        logger.debug("Could not list Prometheus metrics: %s", error)
        return []

    active_namespaces = [
        ns.name for ns in components.get_active_components().namespaces
    ]

    results: List[Dict[str, Union[str, bool, float]]] = []
    for entry in get_base_catalog():
        missing = [m for m in entry.requires if m not in available]
        targets = active_namespaces if entry.scope is Scope.namespace else [None]

        for namespace in targets:
            query = _safe_query(entry.resolved_query(namespace))
            name = f"{entry.key}:{namespace}" if namespace else entry.key

            if missing:
                enabled, reason = False, "metric(s) not scraped: " + ", ".join(missing)
            else:
                enabled, reason = _validate_shape(prom_client, query)

            results.append(
                {
                    "name": name,
                    "query": query,
                    "type": entry.type.value,
                    "weight": learned_weights.get(query, entry.default_weight),
                    "enabled": enabled,
                    "reason": reason,
                }
            )

    _assign_weights([r for r in results if r["enabled"]])
    return results
