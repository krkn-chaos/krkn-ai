"""
Pytest configuration and shared fixtures
"""

import tempfile
import datetime
from unittest.mock import Mock, patch
import pytest

from krkn_ai.models.config import (
    ConfigFile,
    GeneticAlgorithmConfig,
    FitnessFunction,
    FitnessFunctionType,
    ScenarioConfig,
    PodScenarioConfig,
    ClusterComponents,
)
from krkn_ai.models.cluster_components import (
    Namespace,
    Pod,
    Container,
    Node,
)
from krkn_ai.models.app import CommandRunResult, FitnessResult
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.algorithm.genetic import GeneticAlgorithm


@pytest.fixture
def temp_output_dir():
    """Create a temporary output directory"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_cluster_components():
    """Create mock cluster components"""
    namespace = Namespace(
        name="test-namespace",
        pods=[
            Pod(
                name="test-pod",
                labels={"app": "test"},
                containers=[Container(name="test-container")],
            )
        ],
        services=[],
    )
    node = Node(
        name="test-node",
        labels={"kubernetes.io/os": "linux"},
        free_cpu=4.0,
        free_mem=8.0,
        interfaces=["eth0"],
        taints=[],
    )
    return ClusterComponents(namespaces=[namespace], nodes=[node])


@pytest.fixture
def minimal_config(mock_cluster_components):
    """Create minimal configuration"""
    return ConfigFile(
        kubeconfig_file_path="/tmp/test-kubeconfig",
        fitness_function=FitnessFunction(
            query="test_query", type=FitnessFunctionType.point
        ),
        scenario=ScenarioConfig(pod_scenarios=PodScenarioConfig(enable=True)),
        cluster_components=mock_cluster_components,
        genetic=GeneticAlgorithmConfig(generations=2, population_size=4),
    )


@pytest.fixture
def mock_krkn_runner():
    """Create mock KrknRunner"""
    mock_runner = Mock()
    mock_result = CommandRunResult(
        generation_id=0,
        scenario_id=1,
        scenario=DummyScenario(cluster_components=ClusterComponents()),
        cmd="test-command",
        log="test-log",
        returncode=0,
        start_time=datetime.datetime.now(),
        end_time=datetime.datetime.now(),
        fitness_result=FitnessResult(fitness_score=10.0),
        health_check_results={},
    )
    mock_runner.run = Mock(return_value=mock_result)
    return mock_runner


@pytest.fixture
def mock_scenario():
    """Create mock scenario object"""
    return DummyScenario(cluster_components=ClusterComponents())


@pytest.fixture
def mock_command_run_result(mock_scenario):
    """Create mock command run result"""
    return CommandRunResult(
        generation_id=0,
        scenario_id=1,
        scenario=mock_scenario,
        cmd="test-command",
        log="test-log",
        returncode=0,
        start_time=datetime.datetime.now(),
        end_time=datetime.datetime.now(),
        fitness_result=FitnessResult(fitness_score=10.0),
        health_check_results={},
    )


@pytest.fixture
def genetic_algorithm(minimal_config, temp_output_dir):
    """Create a GeneticAlgorithm instance for testing"""
    with patch("krkn_ai.algorithm.base.KrknRunner"):
        with patch(
            "krkn_ai.algorithm.base.ScenarioFactory.generate_valid_scenarios"
        ) as mock_gen:
            mock_gen.return_value = [("pod_scenarios", Mock)]
            ga = GeneticAlgorithm(
                config=minimal_config, output_dir=temp_output_dir, format="yaml"
            )
            return ga


@pytest.fixture
def genetic_algorithm_with_mock_runner(minimal_config, temp_output_dir):
    """Create a GeneticAlgorithm instance with mock runner for testing"""
    with patch("krkn_ai.algorithm.base.KrknRunner") as mock_runner_class:
        mock_runner = Mock()
        mock_runner_class.return_value = mock_runner

        with patch(
            "krkn_ai.algorithm.base.ScenarioFactory.generate_valid_scenarios"
        ) as mock_gen:
            mock_gen.return_value = [("pod_scenarios", Mock)]
            ga = GeneticAlgorithm(
                config=minimal_config, output_dir=temp_output_dir, format="yaml"
            )
            ga.krkn_client = mock_runner
            return ga
