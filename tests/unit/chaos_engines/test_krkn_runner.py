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
    FitnessFunctionItem,
    FitnessFunctionType,
    HealthCheckConfig,
)
from krkn_ai.models.custom_errors import (
    FitnessFunctionCalculationError,
    FitnessFunctionValidationError,
)
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.scenario.base import CompositeScenario, CompositeDependency
from krkn_ai.models.cluster_components import ClusterComponents


def make_runner(minimal_config, temp_output_dir, mock_prom_client):
    with patch(
        "krkn_ai.chaos_engines.krkn_runner.create_prometheus_client",
        return_value=mock_prom_client,
    ):
        return KrknRunner(
            config=minimal_config,
            output_dir=temp_output_dir,
            runner_type=KrknRunnerType.CLI_RUNNER,
        )


MULTI_SERIES_RANGE_RESULT = [
    {"metric": {"pod": "cart"}, "values": [[1000, "5"]]},
    {"metric": {"pod": "catalogue"}, "values": [[1000, "8"]]},
]

MULTI_SERIES_INSTANT_RESULT = [
    {"metric": {"pod": "cart"}, "value": [1000, "5"]},
    {"metric": {"pod": "catalogue"}, "value": [1000, "8"]},
]


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


class TestKrknRunnerQueryValidation:
    """Test opt-in preflight fitness query validation (validate_fitness_queries)"""

    def test_validation_fails_with_multi_series(self, minimal_config, temp_output_dir):
        """Preflight rejects queries that return multiple time series"""
        minimal_config.fitness_function = FitnessFunction(
            query="kube_pod_container_status_restarts_total",
            type=FitnessFunctionType.point,
        )
        mock_prom_client = Mock()
        mock_prom_client.process_query.return_value = MULTI_SERIES_INSTANT_RESULT
        runner = make_runner(minimal_config, temp_output_dir, mock_prom_client)

        with pytest.raises(FitnessFunctionValidationError) as exc_info:
            runner.validate_fitness_queries()

        error = str(exc_info.value)
        assert "returned 2 time series during validation" in error
        assert "exactly one time series" in error

    def test_validation_fails_with_invalid_query_syntax(
        self, minimal_config, temp_output_dir
    ):
        """Preflight rejects invalid PromQL queries"""
        minimal_config.fitness_function = FitnessFunction(
            query="invalid_query(",
            type=FitnessFunctionType.point,
        )
        mock_prom_client = Mock()
        mock_prom_client.process_query.side_effect = RuntimeError(
            "bad query syntax with secret-token"
        )
        runner = make_runner(minimal_config, temp_output_dir, mock_prom_client)

        with pytest.raises(FitnessFunctionValidationError) as exc_info:
            runner.validate_fitness_queries()

        error = str(exc_info.value)
        assert "may be syntactically invalid" in error
        assert "Cause: RuntimeError" in error
        assert "secret-token" not in error

    def test_validation_rejects_range_parameter_in_point_query(
        self, minimal_config, temp_output_dir
    ):
        """Preflight rejects $range$ in point queries because runtime will not replace it"""
        minimal_config.fitness_function = FitnessFunction(
            query="rate(container_cpu_usage_seconds_total[$range$])",
            type=FitnessFunctionType.point,
        )
        mock_prom_client = Mock()
        runner = make_runner(minimal_config, temp_output_dir, mock_prom_client)

        with pytest.raises(FitnessFunctionValidationError) as exc_info:
            runner.validate_fitness_queries()

        error = str(exc_info.value)
        assert "$range$ is only supported for range fitness queries" in error
        mock_prom_client.process_query.assert_not_called()

    def test_validation_substitutes_range_parameter(
        self, minimal_config, temp_output_dir
    ):
        """Preflight substitutes $range$ with a sample range"""
        minimal_config.fitness_function = FitnessFunction(
            query="rate(container_cpu_usage_seconds_total[$range$])",
            type=FitnessFunctionType.range,
        )
        mock_prom_client = Mock()
        mock_prom_client.process_query.return_value = [{"value": [1000, "0.5"]}]
        runner = make_runner(minimal_config, temp_output_dir, mock_prom_client)

        runner.validate_fitness_queries()

        mock_prom_client.process_query.assert_called_once_with(
            "rate(container_cpu_usage_seconds_total[5m])"
        )

    def test_validation_skips_empty_result(self, minimal_config, temp_output_dir):
        """Preflight allows queries with no data before chaos runs (metric may appear later)"""
        minimal_config.fitness_function = FitnessFunction(
            query="sum(metric_that_has_no_samples_yet)",
            type=FitnessFunctionType.point,
        )
        mock_prom_client = Mock()
        mock_prom_client.process_query.return_value = []
        runner = make_runner(minimal_config, temp_output_dir, mock_prom_client)

        runner.validate_fitness_queries()

        mock_prom_client.process_query.assert_called_once()

    @patch("krkn_ai.chaos_engines.krkn_runner.env_is_truthy", return_value=True)
    def test_validation_skips_in_mock_fitness_mode(
        self, mock_env, minimal_config, temp_output_dir
    ):
        """Preflight is a no-op when MOCK_FITNESS is enabled"""
        minimal_config.fitness_function = FitnessFunction(
            query="kube_pod_container_status_restarts_total",
            type=FitnessFunctionType.point,
        )
        mock_prom_client = Mock()
        runner = make_runner(minimal_config, temp_output_dir, mock_prom_client)

        runner.validate_fitness_queries()

        mock_prom_client.process_query.assert_not_called()

    def test_validation_checks_fitness_items(self, minimal_config, temp_output_dir):
        """Preflight validates each weighted fitness item when query is unset"""
        minimal_config.fitness_function = FitnessFunction(
            items=[
                FitnessFunctionItem(
                    query="sum(kube_pod_container_status_restarts_total)",
                    type=FitnessFunctionType.point,
                )
            ]
        )
        mock_prom_client = Mock()
        mock_prom_client.process_query.return_value = [{"value": [1000, "1"]}]
        runner = make_runner(minimal_config, temp_output_dir, mock_prom_client)

        runner.validate_fitness_queries()

        mock_prom_client.process_query.assert_called_once_with(
            "sum(kube_pod_container_status_restarts_total)"
        )

    def test_init_does_not_auto_validate(self, minimal_config, temp_output_dir):
        """KrknRunner.__init__ must not call Prometheus; validation is opt-in via --validate-queries"""
        minimal_config.fitness_function = FitnessFunction(
            query="kube_pod_container_status_restarts_total",
            type=FitnessFunctionType.point,
        )
        mock_prom_client = Mock()
        mock_prom_client.process_query.return_value = [
            {"value": [1000, "5"]},
            {"value": [1000, "8"]},
        ]

        make_runner(minimal_config, temp_output_dir, mock_prom_client)

        mock_prom_client.process_query.assert_not_called()


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
            with patch.object(
                KrknRunner,
                "_KrknRunner__extract_returncode_from_run",
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


class TestCalculatePointFitness:
    """Test calculate_point_fitness and _query_prometheus_single_point"""

    def test_calculate_point_fitness_success(self, minimal_config, temp_output_dir):
        """Test point fitness calculation with valid Prometheus response"""
        minimal_config.fitness_function = FitnessFunction(
            query="sum(kube_pod_container_status_restarts_total)",
            type=FitnessFunctionType.point,
        )

        mock_prom_client = Mock()
        mock_prom_client.process_prom_query_in_range.side_effect = [
            [{"values": [[1000, "5"]]}],  # start query
            [{"values": [[2000, "10"]]}],  # end query
        ]

        with patch(
            "krkn_ai.chaos_engines.krkn_runner.create_prometheus_client",
            return_value=mock_prom_client,
        ):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            runner.prom_client = mock_prom_client

            start = datetime.datetime(2024, 1, 1, 12, 0, 0)
            end = datetime.datetime(2024, 1, 1, 12, 5, 0)

            score = runner.calculate_point_fitness(
                start, end, "sum(kube_pod_container_status_restarts_total)"
            )

            assert score == 5.0  # 10 - 5
            assert mock_prom_client.process_prom_query_in_range.call_count == 2

    def test_calculate_point_fitness_empty_values_raises_error(
        self, minimal_config, temp_output_dir
    ):
        """Test point fitness raises FitnessFunctionCalculationError when Prometheus returns empty values"""
        minimal_config.fitness_function = FitnessFunction(
            query="sum(kube_pod_container_status_restarts_total)",
            type=FitnessFunctionType.point,
        )

        mock_prom_client = Mock()
        mock_prom_client.process_prom_query_in_range.return_value = [
            {"values": []}
        ]  # Empty values

        with patch(
            "krkn_ai.chaos_engines.krkn_runner.create_prometheus_client",
            return_value=mock_prom_client,
        ):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            runner.prom_client = mock_prom_client

            start = datetime.datetime(2024, 1, 1, 12, 0, 0)
            end = datetime.datetime(2024, 1, 1, 12, 5, 0)

            with pytest.raises(FitnessFunctionCalculationError) as exc_info:
                runner.calculate_point_fitness(
                    start, end, "sum(kube_pod_container_status_restarts_total)"
                )

            assert "Prometheus returned no data" in str(exc_info.value)
            assert "point fitness (start)" in str(exc_info.value)

    def test_calculate_point_fitness_none_result_raises_error(
        self, minimal_config, temp_output_dir
    ):
        """Test point fitness raises error when Prometheus returns None result"""
        minimal_config.fitness_function = FitnessFunction(
            query="sum(kube_pod_container_status_restarts_total)",
            type=FitnessFunctionType.point,
        )

        mock_prom_client = Mock()
        mock_prom_client.process_prom_query_in_range.return_value = None

        with patch(
            "krkn_ai.chaos_engines.krkn_runner.create_prometheus_client",
            return_value=mock_prom_client,
        ):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            runner.prom_client = mock_prom_client

            start = datetime.datetime(2024, 1, 1, 12, 0, 0)
            end = datetime.datetime(2024, 1, 1, 12, 5, 0)

            with pytest.raises(FitnessFunctionCalculationError) as exc_info:
                runner.calculate_point_fitness(
                    start, end, "sum(kube_pod_container_status_restarts_total)"
                )

            assert "Prometheus returned no data" in str(exc_info.value)

    def test_calculate_point_fitness_empty_list_result_raises_error(
        self, minimal_config, temp_output_dir
    ):
        """Test point fitness raises error when Prometheus returns empty list"""
        minimal_config.fitness_function = FitnessFunction(
            query="sum(kube_pod_container_status_restarts_total)",
            type=FitnessFunctionType.point,
        )

        mock_prom_client = Mock()
        mock_prom_client.process_prom_query_in_range.return_value = []

        with patch(
            "krkn_ai.chaos_engines.krkn_runner.create_prometheus_client",
            return_value=mock_prom_client,
        ):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            runner.prom_client = mock_prom_client

            start = datetime.datetime(2024, 1, 1, 12, 0, 0)
            end = datetime.datetime(2024, 1, 1, 12, 5, 0)

            with pytest.raises(FitnessFunctionCalculationError) as exc_info:
                runner.calculate_point_fitness(
                    start, end, "sum(kube_pod_container_status_restarts_total)"
                )

            assert "Prometheus returned no data" in str(exc_info.value)

    def test_query_prometheus_single_point_context_in_error(
        self, minimal_config, temp_output_dir
    ):
        """Test that context string appears in error message"""
        minimal_config.fitness_function = FitnessFunction(
            query="up", type=FitnessFunctionType.point
        )

        mock_prom_client = Mock()
        mock_prom_client.process_prom_query_in_range.return_value = [{"values": []}]

        with patch(
            "krkn_ai.chaos_engines.krkn_runner.create_prometheus_client",
            return_value=mock_prom_client,
        ):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            runner.prom_client = mock_prom_client

            ts = datetime.datetime(2024, 1, 1, 12, 0, 0)

            with pytest.raises(FitnessFunctionCalculationError) as exc_info:
                runner._query_prometheus_single_point("up", ts, "my custom context")

            assert "my custom context" in str(exc_info.value)
            assert "up" in str(exc_info.value)
            assert "2024-01-01 12:00:00" in str(exc_info.value)

    @pytest.mark.parametrize(
        "result",
        [
            MULTI_SERIES_RANGE_RESULT,
            [
                {"metric": {"pod": "cart"}, "values": [[1000, "5"]]},
                {"metric": {"pod": "catalogue"}, "values": []},
            ],
        ],
    )
    def test_query_prometheus_single_point_multi_series_raises_error(
        self, result, minimal_config, temp_output_dir
    ):
        """Test point fitness rejects PromQL queries that return multiple time series"""
        minimal_config.fitness_function = FitnessFunction(
            query="kube_pod_container_status_restarts_total",
            type=FitnessFunctionType.point,
        )

        mock_prom_client = Mock()
        mock_prom_client.process_prom_query_in_range.return_value = result
        runner = make_runner(minimal_config, temp_output_dir, mock_prom_client)

        with pytest.raises(FitnessFunctionValidationError) as exc_info:
            runner._query_prometheus_single_point(
                "kube_pod_container_status_restarts_total",
                datetime.datetime(2024, 1, 1, 12, 0, 0),
                "point fitness (start)",
            )

        error = str(exc_info.value)
        assert "returned 2 time series" in error
        assert "exactly one time series" in error
        assert "sum(...)" in error

    def test_calculate_range_fitness_multi_series_raises_error(
        self, minimal_config, temp_output_dir
    ):
        """Test range fitness rejects PromQL queries that return multiple time series"""
        minimal_config.fitness_function = FitnessFunction(
            query="rate(container_cpu_usage_seconds_total[$range$])",
            type=FitnessFunctionType.range,
        )

        mock_prom_client = Mock()
        mock_prom_client.process_prom_query_in_range.return_value = (
            MULTI_SERIES_RANGE_RESULT
        )
        runner = make_runner(minimal_config, temp_output_dir, mock_prom_client)

        with pytest.raises(FitnessFunctionValidationError) as exc_info:
            runner.calculate_range_fitness(
                datetime.datetime(2024, 1, 1, 12, 0, 0),
                datetime.datetime(2024, 1, 1, 12, 10, 0),
                "rate(container_cpu_usage_seconds_total[$range$])",
            )

        error = str(exc_info.value)
        assert "returned 2 time series" in error
        assert "rate(container_cpu_usage_seconds_total[10m])" in error
        assert "exactly one time series" in error


class TestCalculateRangeFitness:
    """Test calculate_range_fitness"""

    def test_calculate_range_fitness_success(self, minimal_config, temp_output_dir):
        """Test range fitness calculation with valid Prometheus response"""
        minimal_config.fitness_function = FitnessFunction(
            query="max(kube_pod_container_status_restarts_total{$range$})",
            type=FitnessFunctionType.range,
        )

        mock_prom_client = Mock()
        mock_prom_client.process_prom_query_in_range.return_value = [
            {"values": [[1000, "15.5"]]}
        ]

        with patch(
            "krkn_ai.chaos_engines.krkn_runner.create_prometheus_client",
            return_value=mock_prom_client,
        ):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            runner.prom_client = mock_prom_client

            start = datetime.datetime(2024, 1, 1, 12, 0, 0)
            end = datetime.datetime(2024, 1, 1, 12, 10, 0)

            score = runner.calculate_range_fitness(
                start, end, "max(kube_pod_container_status_restarts_total{$range$})"
            )

            # Query should have $range$ replaced with "10m"
            call_str = str(mock_prom_client.process_prom_query_in_range.call_args)
            assert "10m" in call_str
            assert score == 15.5

    def test_calculate_range_fitness_empty_values_raises_error(
        self, minimal_config, temp_output_dir
    ):
        """Test range fitness raises FitnessFunctionCalculationError when Prometheus returns empty values"""
        minimal_config.fitness_function = FitnessFunction(
            query="max(kube_pod_container_status_restarts_total{$range$})",
            type=FitnessFunctionType.range,
        )

        mock_prom_client = Mock()
        mock_prom_client.process_prom_query_in_range.return_value = [{"values": []}]

        with patch(
            "krkn_ai.chaos_engines.krkn_runner.create_prometheus_client",
            return_value=mock_prom_client,
        ):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            runner.prom_client = mock_prom_client

            start = datetime.datetime(2024, 1, 1, 12, 0, 0)
            end = datetime.datetime(2024, 1, 1, 12, 5, 0)

            with pytest.raises(FitnessFunctionCalculationError) as exc_info:
                runner.calculate_range_fitness(
                    start, end, "max(kube_pod_container_status_restarts_total{$range$})"
                )

            assert "Prometheus returned no data" in str(exc_info.value)
            assert "range" in str(exc_info.value)
            assert "2024-01-01 12:00:00" in str(exc_info.value)
            assert "2024-01-01 12:05:00" in str(exc_info.value)

    def test_calculate_range_fitness_none_result_raises_error(
        self, minimal_config, temp_output_dir
    ):
        """Test range fitness raises error when Prometheus returns None result"""
        minimal_config.fitness_function = FitnessFunction(
            query="max(kube_pod_container_status_restarts_total{$range$})",
            type=FitnessFunctionType.range,
        )

        mock_prom_client = Mock()
        mock_prom_client.process_prom_query_in_range.return_value = None

        with patch(
            "krkn_ai.chaos_engines.krkn_runner.create_prometheus_client",
            return_value=mock_prom_client,
        ):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            runner.prom_client = mock_prom_client

            start = datetime.datetime(2024, 1, 1, 12, 0, 0)
            end = datetime.datetime(2024, 1, 1, 12, 5, 0)

            with pytest.raises(FitnessFunctionCalculationError) as exc_info:
                runner.calculate_range_fitness(
                    start, end, "max(kube_pod_container_status_restarts_total{$range$})"
                )

            assert "Prometheus returned no data" in str(exc_info.value)


class TestCalculateFitnessValueRetries:
    """Test calculate_fitness_value retry behavior with empty Prometheus data"""

    @patch("krkn_ai.chaos_engines.krkn_runner.time.sleep")
    @patch("krkn_ai.chaos_engines.krkn_runner.env_is_truthy", return_value=False)
    def test_calculate_fitness_value_rejects_unsupported_type(
        self, mock_env, mock_sleep, minimal_config, temp_output_dir
    ):
        """Test unsupported fitness types fail before entering the retry loop"""
        minimal_config.fitness_function = FitnessFunction(
            query="sum(kube_pod_container_status_restarts_total)",
            type=FitnessFunctionType.point,
        )

        mock_prom_client = Mock()
        runner = make_runner(minimal_config, temp_output_dir, mock_prom_client)

        with pytest.raises(FitnessFunctionCalculationError) as exc_info:
            runner.calculate_fitness_value(
                datetime.datetime(2024, 1, 1, 12, 0, 0),
                datetime.datetime(2024, 1, 1, 12, 5, 0),
                "sum(kube_pod_container_status_restarts_total)",
                "histogram",
            )

        assert "Unsupported fitness_type" in str(exc_info.value)
        mock_sleep.assert_not_called()
        mock_prom_client.process_prom_query_in_range.assert_not_called()

    @patch("krkn_ai.chaos_engines.krkn_runner.time.sleep")
    @patch("krkn_ai.chaos_engines.krkn_runner.env_is_truthy", return_value=False)
    def test_calculate_fitness_value_retries_on_empty_data(
        self, mock_env, mock_sleep, minimal_config, temp_output_dir
    ):
        """Test that calculate_fitness_value retries when Prometheus returns empty data"""
        minimal_config.fitness_function = FitnessFunction(
            query="sum(kube_pod_container_status_restarts_total)",
            type=FitnessFunctionType.point,
        )

        mock_prom_client = Mock()
        # First two calls return empty, third call succeeds
        mock_prom_client.process_prom_query_in_range.side_effect = [
            [{"values": []}],
            [{"values": []}],
            [{"values": [[1000, "5"]]}],
            [{"values": [[2000, "10"]]}],
        ]

        with patch(
            "krkn_ai.chaos_engines.krkn_runner.create_prometheus_client",
            return_value=mock_prom_client,
        ):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            runner.prom_client = mock_prom_client

            start = datetime.datetime(2024, 1, 1, 12, 0, 0)
            end = datetime.datetime(2024, 1, 1, 12, 5, 0)

            # Should not raise since eventually succeeds
            score = runner.calculate_fitness_value(
                start,
                end,
                "sum(kube_pod_container_status_restarts_total)",
                FitnessFunctionType.point,
            )
            assert score == 5.0
            assert mock_prom_client.process_prom_query_in_range.call_count == 4

    @patch("krkn_ai.chaos_engines.krkn_runner.time.sleep")
    @patch("krkn_ai.chaos_engines.krkn_runner.env_is_truthy", return_value=False)
    def test_calculate_fitness_value_raises_after_retries_exhausted(
        self, mock_env, mock_sleep, minimal_config, temp_output_dir
    ):
        """Test that calculate_fitness_value raises after 3 retries when Prometheus keeps returning empty data"""
        minimal_config.fitness_function = FitnessFunction(
            query="sum(kube_pod_container_status_restarts_total)",
            type=FitnessFunctionType.point,
        )

        mock_prom_client = Mock()
        # All calls return empty
        mock_prom_client.process_prom_query_in_range.return_value = [{"values": []}]

        with patch(
            "krkn_ai.chaos_engines.krkn_runner.create_prometheus_client",
            return_value=mock_prom_client,
        ):
            runner = KrknRunner(
                config=minimal_config,
                output_dir=temp_output_dir,
                runner_type=KrknRunnerType.CLI_RUNNER,
            )
            runner.prom_client = mock_prom_client

            start = datetime.datetime(2024, 1, 1, 12, 0, 0)
            end = datetime.datetime(2024, 1, 1, 12, 5, 0)

            with pytest.raises(FitnessFunctionCalculationError) as exc_info:
                runner.calculate_fitness_value(
                    start,
                    end,
                    "sum(kube_pod_container_status_restarts_total)",
                    FitnessFunctionType.point,
                )

            # After retries exhausted, calculate_fitness_value raises its own error
            assert "failed after 3 retries" in str(exc_info.value)
            # Each retry calls calculate_point_fitness which calls _query_prometheus_single_point
            # for the start point. The guard fails immediately, so 1 Prometheus call per retry = 3 total.
            assert mock_prom_client.process_prom_query_in_range.call_count == 3

    @patch("krkn_ai.chaos_engines.krkn_runner.time.sleep")
    @patch("krkn_ai.chaos_engines.krkn_runner.env_is_truthy", return_value=False)
    def test_calculate_fitness_value_does_not_retry_validation_error(
        self, mock_env, mock_sleep, minimal_config, temp_output_dir
    ):
        """Test that query validation errors are not retried as transient failures"""
        minimal_config.fitness_function = FitnessFunction(
            query="kube_pod_container_status_restarts_total",
            type=FitnessFunctionType.point,
        )

        mock_prom_client = Mock()
        mock_prom_client.process_prom_query_in_range.return_value = (
            MULTI_SERIES_RANGE_RESULT
        )
        runner = make_runner(minimal_config, temp_output_dir, mock_prom_client)

        with pytest.raises(FitnessFunctionValidationError):
            runner.calculate_fitness_value(
                datetime.datetime(2024, 1, 1, 12, 0, 0),
                datetime.datetime(2024, 1, 1, 12, 5, 0),
                "kube_pod_container_status_restarts_total",
                FitnessFunctionType.point,
            )

        mock_sleep.assert_not_called()
        assert mock_prom_client.process_prom_query_in_range.call_count == 1
