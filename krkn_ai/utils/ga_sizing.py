from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

from krkn_ai.models.cluster_components import ClusterComponents, Node
from krkn_ai.models.config import ConfigFile, FitnessFunction, ScenarioConfig
from krkn_ai.models.scenario.factory import ScenarioFactory, scenario_specs
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)

# Genetic profiles use per-scenario target counts derived from discovered
# components. Replicas sharing a serialized selector count once when the
# scenario cannot identify individual pods. No sampling or RNG is needed.


def _pod_label_targets(
    components: ClusterComponents, *, require_containers: bool = False
) -> set[Tuple[str, str, str]]:
    """Return distinct (namespace, label key, label value) pod selectors.

    These scenarios serialize selectors, not pod names, so replicas sharing a
    selector contribute one target. Container scenarios only use pods that
    have containers.
    """
    return {
        (namespace.name, key, value)
        for namespace in components.namespaces
        for pod in namespace.pods
        if pod.labels and (not require_containers or pod.containers)
        for key, value in pod.labels.items()
    }


def _all_pods(components: ClusterComponents) -> List[Tuple]:
    return [(ns, p) for ns in components.namespaces for p in ns.pods]


def _services_with_ports(components: ClusterComponents) -> List[Tuple]:
    return [(ns, s) for ns in components.namespaces for s in ns.services if s.ports]


def _vmis(components: ClusterComponents) -> List[Tuple]:
    return [(ns, v) for ns in components.namespaces for v in ns.vmis]


def _namespaces_with_services(components: ClusterComponents) -> List:
    return [ns for ns in components.namespaces if ns.services]


def _pvc_or_pod_targets(components: ClusterComponents) -> List[Tuple]:
    """Mirrors pvc-scenarios/storage-throttle: PVCs are preferred cluster-wide;
    pods are only reachable as a fallback when no namespace has any PVCs."""
    pvc_targets = [(ns, pvc) for ns in components.namespaces for pvc in ns.pvcs]
    if pvc_targets:
        return pvc_targets
    return [(ns, p) for ns in components.namespaces for p in ns.pods]


def _node_target_count(nodes: List[Node]) -> int:
    """Mirrors krkn_ai.cluster.node_selector.select_nodes(): a target is
    either one specific node (selected individually) or one label=value
    group spanning 2+ nodes (a fan-out target). A label that only ever
    matches a single node is not counted again -- it collapses onto the
    individual-node case and would otherwise double-count that node."""
    if not nodes:
        return 0
    groups: Dict[str, set] = defaultdict(set)
    for node in nodes:
        for key, value in node.labels.items():
            groups[f"{key}={value}"].add(node.name)
    fanout_groups = sum(1 for members in groups.values() if len(members) > 1)
    return len(nodes) + fanout_groups


def _time_scenario_target_count(components: ClusterComponents) -> int:
    """Count namespace-scoped pod selectors and cluster-wide node selectors."""
    node_branch = set()
    for node in components.nodes:
        for key, value in node.labels.items():
            node_branch.add(f"{key}={value}")

    return len(_pod_label_targets(components)) + len(node_branch)


def _network_scenario_target_count(components: ClusterComponents) -> int:
    return len([node for node in components.nodes if node.interfaces])


# scenario attr name (see scenario_specs) -> target count from active
# cluster_components, mirroring that scenario's target-selection semantics.
# Every entry in scenario_specs must have a counter here: an unregistered
# scenario type raises rather than silently sizing off an incomplete total.
TARGET_SPACE_COUNTERS: Dict[str, Callable[[ClusterComponents], int]] = {
    "pod_scenarios": lambda c: len(_pod_label_targets(c)),
    "application_outages": lambda c: len(_pod_label_targets(c)),
    "container_scenarios": lambda c: len(
        _pod_label_targets(c, require_containers=True)
    ),
    "node_cpu_hog": lambda c: _node_target_count(c.nodes),
    "node_memory_hog": lambda c: _node_target_count(c.nodes),
    "node_io_hog": lambda c: _node_target_count(c.nodes),
    "time_scenarios": _time_scenario_target_count,
    "network_scenarios": _network_scenario_target_count,
    "dns_outage": lambda c: len(_all_pods(c)),
    "syn_flood": lambda c: len(_services_with_ports(c)),
    "pvc_scenarios": lambda c: len(_pvc_or_pod_targets(c)),
    "kubevirt_scenarios": lambda c: len(_vmis(c)),
    "storage_throttle": lambda c: len(_pvc_or_pod_targets(c)),
    "service_disruption": lambda c: len(_namespaces_with_services(c)),
}

# Initial cutoffs for aggregate target counts. Recalibrate against
# representative cluster profiles, not raw pod-replica totals.
SMALL_MAX_TARGETS = 150
MEDIUM_MAX_TARGETS = 500

# generations, population_size per tier.
TIER_PROFILES = {
    "small": (8, 4),
    "medium": (5, 8),
    "large": (3, 20),
}

# Stop once a run keeps turning up nothing new
EXPLORATION_SATURATION = 3
GENERATION_SATURATION = 5


def _probe_config(components: ClusterComponents, kubeconfig: str) -> ConfigFile:
    names = [name for name, _ in scenario_specs]
    return ConfigFile(
        kubeconfig_file_path=kubeconfig,
        fitness_function=FitnessFunction(query="placeholder"),
        scenario=ScenarioConfig(**{name: {"enable": True} for name in names}),
        cluster_components=components,
        allow_dangerous_scenarios=False,
    )


def count_target_space(
    components: ClusterComponents, kubeconfig: str
) -> Tuple[int, int]:
    """Sum target choices across every scenario type the cluster supports.

    Counters mirror each scenario's target-selection semantics; pod replicas
    sharing a serialized selector count as one target. The result is
    deterministic and does not touch the RNG.
    """
    config = _probe_config(components, kubeconfig)
    # No scenario instantiation needed here (unlike ScenarioFactory.
    # generate_valid_scenarios): list_scenarios only checks enable flags /
    # the dangerous-scenario gate, so this never touches the RNG.
    candidates = ScenarioFactory.list_scenarios(config)
    active = components.get_active_components()

    total = 0
    valid_types = 0
    for name, _cls in candidates:
        counter = TARGET_SPACE_COUNTERS.get(name)
        if counter is None:
            raise NotImplementedError(
                f"No target-space counter registered for scenario '{name}'. "
                "Add one to TARGET_SPACE_COUNTERS instead of leaving it "
                "out of the genetic sizing total."
            )
        count = counter(active)
        if count > 0:
            total += count
            valid_types += 1

    return total, valid_types


def _tier(targets: int) -> str:
    if targets <= SMALL_MAX_TARGETS:
        return "small"
    if targets <= MEDIUM_MAX_TARGETS:
        return "medium"
    return "large"


def recommend_genetic_params(
    components: ClusterComponents, kubeconfig: str
) -> Optional[Dict]:
    """Size the genetic algorithm from the variety the cluster can offer"""
    try:
        targets, valid_types = count_target_space(components, kubeconfig)
    except Exception as error:
        logger.debug("Genetic sizing probe failed: %s", error)
        return None

    if targets == 0:
        logger.debug("No scenario targets found, leaving genetic defaults")
        return None

    tier = _tier(targets)
    generations, population_size = TIER_PROFILES[tier]

    profile = {
        "generations": generations,
        "population_size": population_size,
        "tournament_size": max(2, min(6, population_size // 3)),
        "composition_rate": 0.0 if tier == "small" else 0.3,
        "population_injection_rate": 0.0 if tier == "small" else 0.1,
        "exploration_saturation": EXPLORATION_SATURATION,
        "generation_saturation": GENERATION_SATURATION,
    }

    logger.info(
        "Sized genetic config: %s cluster, %d scenario types, %d distinct targets "
        "-> %d generations x %d population",
        tier,
        valid_types,
        targets,
        generations,
        population_size,
    )
    return profile
