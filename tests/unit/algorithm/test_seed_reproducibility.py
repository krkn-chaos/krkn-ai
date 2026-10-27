"""
Seeded runs must make the same random choices in every process (#498)
"""

import json
import os
import subprocess
import sys
import textwrap

import pytest

from krkn_ai.models.scenario.scenario_cpu_hog import NodeCPUHogScenario

SEEDED_WORKLOAD = textwrap.dedent(
    """
    import json
    import logging
    import tempfile
    from unittest.mock import patch

    logging.disable(logging.CRITICAL)

    from krkn_ai.algorithm.genetic import GeneticAlgorithm
    from krkn_ai.models.cluster_components import (
        ClusterComponents, Container, Namespace, Node, Pod,
    )
    from krkn_ai.models.config import (
        ConfigFile, FitnessFunction, GeneticAlgorithmConfig, PodScenarioConfig,
        ScenarioConfig,
    )
    from krkn_ai.models.scenario.scenario_cpu_hog import NodeCPUHogScenario
    from krkn_ai.models.scenario.scenario_time import TimeScenario
    from krkn_ai.utils.rng import rng

    pods = [
        Pod(name=f"pod-{i}", labels={f"app-{i}": f"v{i}"}, containers=[Container(name="c")])
        for i in range(8)
    ]
    nodes = [
        Node(name=f"node-{i}", labels={f"zone-{i}": f"z{i}"}, free_cpu=4.0,
             free_mem=8.0, interfaces=["eth0"], taints=[])
        for i in range(8)
    ]
    cluster = ClusterComponents(
        namespaces=[Namespace(name="ns", pods=pods, services=[])], nodes=nodes
    )
    config = ConfigFile(
        kubeconfig_file_path="/tmp/kubeconfig",
        fitness_function=FitnessFunction(query="up"),
        scenario=ScenarioConfig(pod_scenarios=PodScenarioConfig(enable=True)),
        cluster_components=cluster,
        genetic=GeneticAlgorithmConfig(generations=2, population_size=4),
    )
    with patch("krkn_ai.algorithm.base.KrknRunner"), patch(
        "krkn_ai.algorithm.base.ScenarioFactory.generate_valid_scenarios",
        return_value=[],
    ):
        ga = GeneticAlgorithm(config=config, output_dir=tempfile.mkdtemp(), format="yaml")

    rng.set_seed(42)
    parent_a = NodeCPUHogScenario(cluster_components=cluster)
    parent_b = NodeCPUHogScenario(cluster_components=cluster)
    offspring = []
    for _ in range(20):
        parent_a, parent_b = ga.crossover(parent_a, parent_b)
        offspring.append(str(parent_a) + str(parent_b))

    rng.set_seed(42)
    time_labels = [
        TimeScenario(cluster_components=cluster).label_selector.value for _ in range(20)
    ]

    rng.set_seed(42)
    ga.seen_population = {TimeScenario(cluster_components=cluster): None for _ in range(6)}
    with patch(
        "krkn_ai.algorithm.genetic.engine.ScenarioFactory.generate_random_scenario",
        return_value=None,
    ):
        duplicated = [str(s) for s in ga.create_population(10)]

    print(json.dumps({
        "crossover": offspring,
        "time_scenario_labels": time_labels,
        "duplicate_fallback": duplicated,
    }))
    """
)


def _run_seeded_workload(hash_seed: str) -> dict:
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    completed = subprocess.run(
        [sys.executable, "-c", SEEDED_WORKLOAD],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def runs_with_different_hash_seeds():
    return _run_seeded_workload("1"), _run_seeded_workload("2")


@pytest.mark.parametrize(
    "choice_site", ["crossover", "time_scenario_labels", "duplicate_fallback"]
)
def test_same_seed_repeats_across_processes(
    runs_with_different_hash_seeds, choice_site
):
    """Same rng seed gives the same choices regardless of PYTHONHASHSEED"""
    first_run, second_run = runs_with_different_hash_seeds

    assert first_run[choice_site] == second_run[choice_site]


def test_ungrouped_crossover_parameters_follow_parameter_order(
    genetic_algorithm, mock_cluster_components
):
    """One rng draw per group, so ungrouped groups must not depend on set order"""
    scenario_a = NodeCPUHogScenario(cluster_components=mock_cluster_components)
    scenario_b = NodeCPUHogScenario(cluster_components=mock_cluster_components)

    _, _, groups = genetic_algorithm._shared_parameter_groups(scenario_a, scenario_b)

    grouped = {
        param_type
        for group in NodeCPUHogScenario.crossover_parameter_groups
        for param_type in group
    }
    expected = [
        {type(parameter)}
        for parameter in scenario_a.parameters
        if type(parameter) not in grouped
    ]
    assert groups[len(NodeCPUHogScenario.crossover_parameter_groups) :] == expected
