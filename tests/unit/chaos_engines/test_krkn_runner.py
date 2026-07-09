"""
KrknRunner core functionality tests
"""

import json
import os
import datetime
import pytest
from unittest.mock import Mock, patch

from krkn_ai.chaos_engines.krkn_runner import KrknRunner
from krkn_ai.models.app import KrknRunnerType
from krkn_ai.models.config import (
    ElasticConfig,
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


class TestElasticsearchConfiguration:
    """Test Elasticsearch settings reach both single and composite scenario runs"""

    def _build_runner(self, config, output_dir):
        with patch("krkn_ai.chaos_engines.krkn_runner.create_prometheus_client"):
            return KrknRunner(
                config=config,
                output_dir=output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )

    def _composite_scenario(self):
        return CompositeScenario(
            scenario_a=DummyScenario(cluster_components=ClusterComponents()),
            scenario_b=DummyScenario(cluster_components=ClusterComponents()),
            dependency=CompositeDependency.NONE,
        )

    def _load_graph_json(self, output_dir):
        graph_dir = os.path.join(output_dir, "graphs")
        json_files = [f for f in os.listdir(graph_dir) if f.endswith(".json")]
        assert len(json_files) == 1
        with open(os.path.join(graph_dir, json_files[0]), encoding="utf-8") as f:
            return json.load(f)

    def test_es_flags_injected_into_single_scenario_command(
        self, minimal_config, temp_output_dir
    ):
        """A single-scenario command carries the {es_env_list} placeholder, so the
        ES flags are substituted into it."""
        minimal_config.elastic = ElasticConfig(
            enable=True, server="https://es.example.com"
        )
        runner = self._build_runner(minimal_config, temp_output_dir)

        command = "krknctl run test --kubeconfig /tmp/kubeconfig {es_env_list}"
        result = runner.process_es_env_string(command, True)

        assert "{es_env_list}" not in result
        # Prove the ES flags were actually injected, not blanked with an empty string
        assert "--enable-es True" in result
        assert '--es-server "https://es.example.com"' in result

    def test_graph_json_includes_es_env_when_elastic_enabled(
        self, minimal_config, temp_output_dir
    ):
        """krknctl graph run accepts no ES flags, so every scenario node in the
        graph JSON must carry the ES settings as krknhub env vars."""
        minimal_config.kubeconfig_file_path = "/tmp/kubeconfig"
        minimal_config.elastic = ElasticConfig(
            enable=True,
            server="https://es.example.com",
            port=9200,
            username="elastic",
            password="secret",
            verify_certs=False,
        )
        runner = self._build_runner(minimal_config, temp_output_dir)

        runner.graph_command(self._composite_scenario())

        graph = self._load_graph_json(temp_output_dir)
        assert graph
        for node in graph.values():
            env = node["env"]
            assert env["ENABLE_ES"] == "True"
            assert env["ES_SERVER"] == "https://es.example.com"
            assert env["ES_PORT"] == "9200"
            assert env["ES_USERNAME"] == "elastic"
            assert env["ES_PASSWORD"] == "secret"
            assert env["ES_VERIFY_CERTS"] == "False"

    def test_graph_json_omits_es_env_when_elastic_disabled(
        self, minimal_config, temp_output_dir
    ):
        """No ES settings should leak into the graph JSON when ES is disabled."""
        minimal_config.kubeconfig_file_path = "/tmp/kubeconfig"
        minimal_config.elastic = ElasticConfig(enable=False)
        runner = self._build_runner(minimal_config, temp_output_dir)

        runner.graph_command(self._composite_scenario())

        graph = self._load_graph_json(temp_output_dir)
        assert graph
        for node in graph.values():
            assert "ENABLE_ES" not in node["env"]
            assert "ES_SERVER" not in node["env"]
