"""
KrknRunner core functionality tests
"""

import os
import datetime
import pytest
from unittest.mock import Mock, patch

from krkn_ai.chaos_engines.krkn_runner import KrknRunner
from krkn_ai.models.app import KrknRunnerType
from krkn_ai.models.config import (
    FitnessFunction,
    FitnessFunctionType,
    HealthCheckConfig,
)
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.scenario.base import CompositeScenario, CompositeDependency
from krkn_ai.models.cluster_components import ClusterComponents


class TestKrknRunnerInitialization:
    """Test KrknRunner initialization and runner type detection"""

    def test_init_with_explicit_runner_type(self, minimal_config, temp_output_dir):
        """Test initialization with explicit runner type"""
        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            assert runner.config == minimal_config
            assert runner.output_dir == temp_output_dir
            assert runner.runner_type == KrknRunnerType.CLI_RUNNER

    @patch("krkn_ai.chaos_engines.krkn_runner.run_shell")
    def test_init_detects_cli_runner(
        self, mock_run_shell, minimal_config, temp_output_dir
    ):
        """Test automatic detection of CLI runner when krknctl is available"""
        mock_run_shell.side_effect = [
            ("krknctl version 1.0.0", 0),  # krknctl available
            ("podman version 1.0.0", 0),  # podman also available
        ]
        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            runner = KrknRunner(config=minimal_config, output_dir=temp_output_dir)
            assert runner.runner_type == KrknRunnerType.CLI_RUNNER

    @patch("krkn_ai.chaos_engines.krkn_runner.run_shell")
    def test_init_raises_when_no_runner_available(
        self, mock_run_shell, minimal_config, temp_output_dir
    ):
        """Test raises exception when neither krknctl nor podman is available"""
        mock_run_shell.side_effect = [
            ("", 1),  # krknctl not available
            ("", 1),  # podman not available
        ]
        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            with pytest.raises(Exception, match="krknctl and podman are not available"):
                KrknRunner(config=minimal_config, output_dir=temp_output_dir)


class TestKrknRunnerRun:
    """Test KrknRunner.run method core behavior"""

    @patch("krkn_ai.chaos_engines.krkn_runner.env_is_truthy", return_value=True)
    @patch("krkn_ai.chaos_engines.krkn_runner.run_shell")
    def test_run_scenario_with_mock_mode(
        self, mock_run_shell, mock_env, minimal_config, temp_output_dir
    ):
        """Test running scenario in mock mode returns successful result"""
        minimal_config.fitness_function = FitnessFunction(
            query="test_query", type=FitnessFunctionType.point
        )
        minimal_config.health_checks = HealthCheckConfig()

        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            scenario = DummyScenario(cluster_components=ClusterComponents())

            result = runner.run(scenario, generation_id=0)

            assert result.generation_id == 0
            assert result.scenario == scenario
            assert result.returncode == 0
            assert isinstance(result.start_time, datetime.datetime)
            assert isinstance(result.end_time, datetime.datetime)

    @patch("krkn_ai.chaos_engines.krkn_runner.env_is_truthy", return_value=False)
    @patch("krkn_ai.chaos_engines.krkn_runner.run_shell")
    def test_run_handles_misconfiguration_failure(
        self, mock_run_shell, mock_env, minimal_config, temp_output_dir
    ):
        """Test run handles misconfiguration failure (non-zero, non-2 return code)"""
        minimal_config.fitness_function = FitnessFunction(
            query="test_query",
            type=FitnessFunctionType.point,
            include_krkn_failure=True,
        )
        minimal_config.health_checks = HealthCheckConfig()

        # Simulate misconfiguration failure (return code 1)
        mock_run_shell.return_value = ("error log", 1)

        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            with patch(
                "krkn_ai.chaos_engines.krkn_runner.extract_telemetry_from_log",
                return_value=(1, None),
            ):
                runner = KrknRunner(
                    config=minimal_config,
                    output_dir=temp_output_dir,
                    runner_type=KrknRunnerType.CLI_RUNNER,
                )
                scenario = DummyScenario(cluster_components=ClusterComponents())

                result = runner.run(scenario, generation_id=0)

                assert result.returncode == 1
                assert result.fitness_result.fitness_score == -1.0
                assert result.fitness_result.krkn_failure_score == -1.0

    def test_run_raises_for_unsupported_scenario_type(
        self, minimal_config, temp_output_dir
    ):
        """Test run raises NotImplementedError for unsupported scenario type"""
        minimal_config.health_checks = HealthCheckConfig()

        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            unsupported_scenario = Mock()  # Not a Scenario or CompositeScenario

            with pytest.raises(NotImplementedError, match="Scenario unable to run"):
                runner.run(unsupported_scenario, generation_id=0)


class TestKrknRunnerCommandGeneration:
    """Test command generation methods"""

    def test_runner_command_for_cli_runner(self, minimal_config, temp_output_dir):
        """Test runner_command generates correct CLI command format"""
        minimal_config.wait_duration = 60
        minimal_config.kubeconfig_file_path = "/tmp/kubeconfig"

        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            scenario = DummyScenario(cluster_components=ClusterComponents())

            command = runner.runner_command(scenario)

            assert "krknctl run" in command
            assert "dummy-scenario" in command
            assert "--wait-duration 60" in command
            assert "/tmp/kubeconfig" in command

    def test_runner_command_for_hub_runner(self, minimal_config, temp_output_dir):
        """Test runner_command generates correct podman command format"""
        minimal_config.wait_duration = 60
        minimal_config.kubeconfig_file_path = "/tmp/kubeconfig"

        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.HUB_RUNNER,
            )
            scenario = DummyScenario(cluster_components=ClusterComponents())

            command = runner.runner_command(scenario)

            assert "podman run" in command
            assert "dummy-scenario" in command
            assert "--net=host" in command
            assert "/tmp/kubeconfig" in command

    def test_graph_command_creates_json_file(self, minimal_config, temp_output_dir):
        """Test graph_command creates JSON file for composite scenario"""
        minimal_config.kubeconfig_file_path = "/tmp/kubeconfig"

        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            scenario_a = DummyScenario(cluster_components=ClusterComponents())
            scenario_b = DummyScenario(cluster_components=ClusterComponents())
            composite = CompositeScenario(
                scenario_a=scenario_a,
                scenario_b=scenario_b,
                dependency=CompositeDependency.NONE,
            )

            command = runner.graph_command(composite)

            assert "krknctl graph run" in command
            assert "/tmp/kubeconfig" in command
            # Verify JSON file was created
            graph_dir = os.path.join(temp_output_dir, "graphs")
            assert os.path.exists(graph_dir)
            json_files = [f for f in os.listdir(graph_dir) if f.endswith(".json")]
            assert len(json_files) > 0
