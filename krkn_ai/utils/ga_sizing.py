from typing import Dict, Optional, Set, Tuple

from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.config import ConfigFile, FitnessFunction, ScenarioConfig
from krkn_ai.models.scenario.base import BaseScenario
from krkn_ai.models.scenario.factory import (
    ScenarioFactory,
    _suppressed_factory_warnings,
    scenario_specs,
)
from krkn_ai.utils.logger import get_logger
from krkn_ai.utils.rng import rng

logger = get_logger(__name__)

# Scenarios are sampled to see how many distinct targets a cluster can offer.

SAMPLE_COUNT = 800

# Sampling is seeded so the same cluster always sizes the same way
PROBE_SEED = 0

# Parameters that decide what is attacked
TARGET_PARAMS = frozenset(
    {
        "namespace",
        "pod-label",
        "node-selector",
        "pvc-name",
        "pod-name",
        "name-pattern",
        "label-selector",
        "service-name",
        "pod-selector",
    }
)


# Starting points, measured against test clusters.
SMALL_MAX_TARGETS = 100
MEDIUM_MAX_TARGETS = 250

# generations, population_size per tier.
TIER_PROFILES = {
    "small": (8, 4),
    "medium": (5, 8),
    "large": (3, 20),
}

# Stop once a run keeps turning up nothing new
EXPLORATION_SATURATION = 3
GENERATION_SATURATION = 5


def _target_key(scenario: BaseScenario) -> Tuple:
    parts = [scenario.name]
    for param in getattr(scenario, "parameters", []):
        if param.krknctl_name in TARGET_PARAMS:
            parts.append(f"{param.krknctl_name}={param.value}")
    return tuple(parts)


def _probe_config(components: ClusterComponents, kubeconfig: str) -> ConfigFile:
    names = [name for name, _ in scenario_specs]
    return ConfigFile(
        kubeconfig_file_path=kubeconfig,
        fitness_function=FitnessFunction(query="placeholder"),
        scenario=ScenarioConfig(**{name: {"enable": True} for name in names}),
        cluster_components=components,
        allow_dangerous_scenarios=False,
    )


def count_distinct_targets(
    components: ClusterComponents,
    kubeconfig: str,
    samples: int = SAMPLE_COUNT,
) -> Tuple[int, int]:
    """Sample scenarios and count distinct targets.

    This ranking compares clusters, not the full target space. Larger clusters
    will keep finding new targets past this sample count.
    """
    config = _probe_config(components, kubeconfig)

    seen: Set[Tuple] = set()
    caller_seed = rng.get_seed()
    rng.set_seed(PROBE_SEED)
    try:
        with _suppressed_factory_warnings():
            valid = ScenarioFactory.generate_valid_scenarios(config)
            for _ in range(samples):
                try:
                    scenario = ScenarioFactory.generate_random_scenario(config, valid)
                except Exception as error:
                    logger.debug("Scenario sampling failed: %s", error)
                    continue
                if scenario is not None:
                    seen.add(_target_key(scenario))
    finally:
        rng.set_seed(caller_seed)

    return len(seen), len(valid)


def _tier(targets: int) -> str:
    if targets <= SMALL_MAX_TARGETS:
        return "small"
    if targets <= MEDIUM_MAX_TARGETS:
        return "medium"
    return "large"


def recommend_genetic_params(
    components: ClusterComponents,
    kubeconfig: str,
    samples: int = SAMPLE_COUNT,
) -> Optional[Dict]:
    """Size the genetic algorithm from the variety the cluster can offer"""
    try:
        targets, valid_types = count_distinct_targets(components, kubeconfig, samples)
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
