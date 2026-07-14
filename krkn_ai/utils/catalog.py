"""Catalog of PromQL fitness queries and a recommender that adapts them per cluster."""

from enum import Enum
from typing import Dict, List, Optional, Union

from pydantic import BaseModel, field_validator

from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.config import FitnessFunctionItem, FitnessFunctionType
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


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
    category: FitnessCategory
    name: str
    query_template: str
    type: FitnessFunctionType = FitnessFunctionType.range
    requires: List[str]
    scope: Scope = Scope.namespace
    default_weight: float = 1.0

    @field_validator("default_weight")
    @classmethod
    def _weight_range(cls, value: float) -> float:
        # Match FitnessFunctionItem's [0.0, 1.0] constraint.
        if value < 0 or value > 1:
            raise ValueError(f"{value} is outside the range [0.0, 1.0]")
        return value

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


# High-impact signals: restarts, downtime, OOM, CPU throttling, node and API health.
BASE_CATALOG: List[CatalogEntry] = [
    CatalogEntry(
        key="pod-restarts",
        category=FitnessCategory.availability,
        name="Pod container restarts",
        query_template=(
            'sum(increase(kube_pod_container_status_restarts_total'
            '{namespace="$ns"}[$range$]))'
        ),
        requires=["kube_pod_container_status_restarts_total"],
        scope=Scope.namespace,
    ),
    CatalogEntry(
        key="pod-unavailable",
        category=FitnessCategory.availability,
        name="Non-running pods (Pending/Failed/Unknown)",
        query_template=(
            'sum(kube_pod_status_phase'
            '{namespace="$ns", phase=~"Pending|Failed|Unknown"})'
        ),
        requires=["kube_pod_status_phase"],
        scope=Scope.namespace,
    ),
    CatalogEntry(
        # 0 series until a container was last killed by OOM.
        key="oom-kills",
        category=FitnessCategory.resource,
        name="Containers last terminated by OOMKilled",
        query_template=(
            'sum(kube_pod_container_status_last_terminated_reason'
            '{namespace="$ns", reason="OOMKilled"})'
        ),
        requires=["kube_pod_container_status_last_terminated_reason"],
        scope=Scope.namespace,
    ),
    CatalogEntry(
        key="cpu-throttle",
        category=FitnessCategory.resource,
        name="Worst-container CPU throttling ratio",
        query_template=(
            "max("
            "rate(container_cpu_cfs_throttled_periods_total"
            '{namespace="$ns", container!=""}[$range$])'
            " / "
            "rate(container_cpu_cfs_periods_total"
            '{namespace="$ns", container!=""}[$range$])'
            ")"
        ),
        requires=[
            "container_cpu_cfs_throttled_periods_total",
            "container_cpu_cfs_periods_total",
        ],
        scope=Scope.namespace,
    ),
    CatalogEntry(
        key="node-pressure",
        category=FitnessCategory.node,
        name="Nodes reporting a pressure condition",
        query_template=(
            "sum(kube_node_status_condition"
            '{condition=~"MemoryPressure|DiskPressure|PIDPressure", status="true"})'
        ),
        requires=["kube_node_status_condition"],
        scope=Scope.cluster,
    ),
    CatalogEntry(
        key="apiserver-errors",
        category=FitnessCategory.control_plane,
        name="API server 5xx error fraction",
        query_template=(
            'sum(rate(apiserver_request_total{code=~"5.."}[$range$]))'
            " / sum(rate(apiserver_request_total[$range$]))"
        ),
        requires=["apiserver_request_total"],
        scope=Scope.cluster,
    ),
]


def get_base_catalog() -> List[CatalogEntry]:
    """Return the base fitness-function catalog."""
    return BASE_CATALOG


# Dynamic layer: adapt the catalog to a live cluster

_VALIDATION_RANGE = "5m"


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


def recommend_fitness_queries(
    components: ClusterComponents, prom_client
) -> List[Dict[str, Union[str, bool, float]]]:
    """Suggest fitness queries for the cluster, gated on which metrics exist."""
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
                    "weight": entry.default_weight,
                    "enabled": enabled,
                    "reason": reason,
                }
            )

    # split weight evenly across enabled items
    enabled_count = sum(1 for r in results if r["enabled"])
    if enabled_count:
        share = round(1.0 / enabled_count, 4)
        for r in results:
            if r["enabled"]:
                r["weight"] = share

    return results
