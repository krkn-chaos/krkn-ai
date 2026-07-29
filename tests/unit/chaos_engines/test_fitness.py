"""
FitnessCalculator tests — extracted from test_krkn_runner.py
"""

import datetime
import pytest
from unittest.mock import Mock, patch

from krkn_ai.chaos_engines.fitness import FitnessCalculator
from krkn_ai.models.config import (
    FitnessFunction,
    FitnessFunctionType,
)
from krkn_ai.models.custom_errors import (
    FitnessFunctionCalculationError,
    FitnessFunctionConfigurationError,
)


@pytest.fixture
def mock_prom_client():
    return Mock()


@pytest.fixture
def calculator(mock_prom_client):
    fitness_function = FitnessFunction(
        query="sum(kube_pod_container_status_restarts_total)",
        type=FitnessFunctionType.point,
    )
    return FitnessCalculator(mock_prom_client, fitness_function)


class TestCalculatePointFitness:
    """Test calculate_point_fitness and _query_prometheus_single_point"""

    def test_calculate_point_fitness_success(self, mock_prom_client):
        fitness_function = FitnessFunction(
            query="sum(kube_pod_container_status_restarts_total)",
            type=FitnessFunctionType.point,
        )
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.side_effect = [
            [{"values": [[1000, "5"]]}],  # start query
            [{"values": [[2000, "10"]]}],  # end query
        ]

        start = datetime.datetime(2024, 1, 1, 12, 0, 0)
        end = datetime.datetime(2024, 1, 1, 12, 5, 0)

        score = calc.calculate_point_fitness(
            start, end, "sum(kube_pod_container_status_restarts_total)"
        )

        assert score == 5.0  # 10 - 5
        assert mock_prom_client.process_prom_query_in_range.call_count == 2

    def test_calculate_point_fitness_empty_values_raises_error(self, mock_prom_client):
        fitness_function = FitnessFunction(
            query="sum(kube_pod_container_status_restarts_total)",
            type=FitnessFunctionType.point,
        )
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.return_value = [{"values": []}]

        start = datetime.datetime(2024, 1, 1, 12, 0, 0)
        end = datetime.datetime(2024, 1, 1, 12, 5, 0)

        with pytest.raises(FitnessFunctionCalculationError) as exc_info:
            calc.calculate_point_fitness(
                start, end, "sum(kube_pod_container_status_restarts_total)"
            )

        assert "Prometheus returned no data" in str(exc_info.value)
        assert "point fitness (start)" in str(exc_info.value)

    def test_calculate_point_fitness_none_result_raises_error(self, mock_prom_client):
        fitness_function = FitnessFunction(
            query="sum(kube_pod_container_status_restarts_total)",
            type=FitnessFunctionType.point,
        )
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.return_value = None

        start = datetime.datetime(2024, 1, 1, 12, 0, 0)
        end = datetime.datetime(2024, 1, 1, 12, 5, 0)

        with pytest.raises(FitnessFunctionCalculationError) as exc_info:
            calc.calculate_point_fitness(
                start, end, "sum(kube_pod_container_status_restarts_total)"
            )

        assert "Prometheus returned no data" in str(exc_info.value)

    def test_calculate_point_fitness_empty_list_result_raises_error(
        self, mock_prom_client
    ):
        fitness_function = FitnessFunction(
            query="sum(kube_pod_container_status_restarts_total)",
            type=FitnessFunctionType.point,
        )
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.return_value = []

        start = datetime.datetime(2024, 1, 1, 12, 0, 0)
        end = datetime.datetime(2024, 1, 1, 12, 5, 0)

        with pytest.raises(FitnessFunctionCalculationError) as exc_info:
            calc.calculate_point_fitness(
                start, end, "sum(kube_pod_container_status_restarts_total)"
            )

        assert "Prometheus returned no data" in str(exc_info.value)

    def test_query_prometheus_single_point_context_in_error(self, mock_prom_client):
        fitness_function = FitnessFunction(query="up", type=FitnessFunctionType.point)
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.return_value = [{"values": []}]

        ts = datetime.datetime(2024, 1, 1, 12, 0, 0)

        with pytest.raises(FitnessFunctionCalculationError) as exc_info:
            calc._query_prometheus_single_point("up", ts, "my custom context")

        assert "my custom context" in str(exc_info.value)
        assert "up" in str(exc_info.value)
        assert "2024-01-01 12:00:00" in str(exc_info.value)

    def test_query_prometheus_single_point_multiple_series_raises_error(
        self, mock_prom_client
    ):
        fitness_function = FitnessFunction(
            query="kube_pod_container_status_restarts_total",
            type=FitnessFunctionType.point,
        )
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.return_value = [
            {"metric": {"container": "cart"}, "values": [[1000, "5"]]},
            {"metric": {"container": "payment"}, "values": [[1000, "3"]]},
        ]

        ts = datetime.datetime(2024, 1, 1, 12, 0, 0)

        with pytest.raises(FitnessFunctionConfigurationError) as exc_info:
            calc._query_prometheus_single_point(
                "kube_pod_container_status_restarts_total",
                ts,
                "point fitness (start)",
            )

        assert "Prometheus returned 2 series" in str(exc_info.value)
        assert "Fitness queries must return exactly one series" in str(exc_info.value)
        assert "sum()" in str(exc_info.value)

    def test_query_prometheus_single_point_counts_empty_series(self, mock_prom_client):
        fitness_function = FitnessFunction(
            query="kube_pod_container_status_restarts_total",
            type=FitnessFunctionType.point,
        )
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.return_value = [
            {"metric": {"container": "cart"}, "values": [[1000, "5"]]},
            {"metric": {"container": "payment"}, "values": []},
        ]

        ts = datetime.datetime(2024, 1, 1, 12, 0, 0)

        with pytest.raises(FitnessFunctionConfigurationError) as exc_info:
            calc._query_prometheus_single_point(
                "kube_pod_container_status_restarts_total",
                ts,
                "point fitness (start)",
            )

        assert "Prometheus returned 2 series" in str(exc_info.value)


class TestCalculateRangeFitness:
    """Test calculate_range_fitness"""

    def test_calculate_range_fitness_success(self, mock_prom_client):
        fitness_function = FitnessFunction(
            query="max(kube_pod_container_status_restarts_total{$range$})",
            type=FitnessFunctionType.range,
        )
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.return_value = [
            {"values": [[1000, "15.5"]]}
        ]

        start = datetime.datetime(2024, 1, 1, 12, 0, 0)
        end = datetime.datetime(2024, 1, 1, 12, 10, 0)

        score = calc.calculate_range_fitness(
            start, end, "max(kube_pod_container_status_restarts_total{$range$})"
        )

        call_str = str(mock_prom_client.process_prom_query_in_range.call_args)
        assert "10m" in call_str
        assert score == 15.5

    def test_calculate_range_fitness_rounds_window_up_to_cover_full_run(
        self, mock_prom_client
    ):
        fitness_function = FitnessFunction(
            query="max_over_time(kube_pod_container_status_restarts_total{$range$})",
            type=FitnessFunctionType.range,
        )
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.return_value = [
            {"values": [[1000, "15.5"]]}
        ]

        start = datetime.datetime(2024, 1, 1, 12, 0, 0)
        end = datetime.datetime(2024, 1, 1, 12, 1, 59)

        calc.calculate_range_fitness(
            start,
            end,
            "max_over_time(kube_pod_container_status_restarts_total{$range$})",
        )

        call_str = str(mock_prom_client.process_prom_query_in_range.call_args)
        assert "2m" in call_str
        assert "1m" not in call_str

    def test_calculate_range_fitness_multiple_series_raises_error(
        self, mock_prom_client
    ):
        fitness_function = FitnessFunction(
            query="max_over_time(container_cpu_usage_seconds_total{$range$})",
            type=FitnessFunctionType.range,
        )
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.return_value = [
            {"metric": {"container": "cart"}, "values": [[1000, "15.5"]]},
            {"metric": {"container": "payment"}, "values": [[1000, "8.0"]]},
        ]

        start = datetime.datetime(2024, 1, 1, 12, 0, 0)
        end = datetime.datetime(2024, 1, 1, 12, 10, 0)

        with pytest.raises(FitnessFunctionConfigurationError) as exc_info:
            calc.calculate_range_fitness(
                start,
                end,
                "max_over_time(container_cpu_usage_seconds_total{$range$})",
            )

        assert "Prometheus returned 2 series" in str(exc_info.value)
        assert "range fitness" in str(exc_info.value)
        assert "sum()" in str(exc_info.value)

    def test_calculate_range_fitness_empty_values_raises_error(self, mock_prom_client):
        fitness_function = FitnessFunction(
            query="max(kube_pod_container_status_restarts_total{$range$})",
            type=FitnessFunctionType.range,
        )
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.return_value = [{"values": []}]

        start = datetime.datetime(2024, 1, 1, 12, 0, 0)
        end = datetime.datetime(2024, 1, 1, 12, 5, 0)

        with pytest.raises(FitnessFunctionCalculationError) as exc_info:
            calc.calculate_range_fitness(
                start, end, "max(kube_pod_container_status_restarts_total{$range$})"
            )

        assert "Prometheus returned no data" in str(exc_info.value)
        assert "range" in str(exc_info.value)
        assert "2024-01-01 12:00:00" in str(exc_info.value)
        assert "2024-01-01 12:05:00" in str(exc_info.value)

    def test_calculate_range_fitness_none_result_raises_error(self, mock_prom_client):
        fitness_function = FitnessFunction(
            query="max(kube_pod_container_status_restarts_total{$range$})",
            type=FitnessFunctionType.range,
        )
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.return_value = None

        start = datetime.datetime(2024, 1, 1, 12, 0, 0)
        end = datetime.datetime(2024, 1, 1, 12, 5, 0)

        with pytest.raises(FitnessFunctionCalculationError) as exc_info:
            calc.calculate_range_fitness(
                start, end, "max(kube_pod_container_status_restarts_total{$range$})"
            )

        assert "Prometheus returned no data" in str(exc_info.value)


class TestCalculateFitnessValueRetries:
    """Test calculate_fitness_value retry behavior with empty Prometheus data"""

    @patch("krkn_ai.chaos_engines.fitness.time.sleep")
    @patch("krkn_ai.chaos_engines.fitness.env_is_truthy", return_value=False)
    def test_calculate_fitness_value_does_not_retry_multi_series_error(
        self, mock_env, mock_sleep, mock_prom_client
    ):
        fitness_function = FitnessFunction(
            query="kube_pod_container_status_restarts_total",
            type=FitnessFunctionType.point,
        )
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.return_value = [
            {"metric": {"container": "cart"}, "values": [[1000, "5"]]},
            {"metric": {"container": "payment"}, "values": [[1000, "3"]]},
        ]

        start = datetime.datetime(2024, 1, 1, 12, 0, 0)
        end = datetime.datetime(2024, 1, 1, 12, 5, 0)

        with pytest.raises(FitnessFunctionConfigurationError) as exc_info:
            calc.calculate_fitness_value(
                start,
                end,
                "kube_pod_container_status_restarts_total",
                FitnessFunctionType.point,
            )

        assert "Prometheus returned 2 series" in str(exc_info.value)
        assert "sum()" in str(exc_info.value)
        assert mock_prom_client.process_prom_query_in_range.call_count == 1
        mock_sleep.assert_not_called()

    @patch("krkn_ai.chaos_engines.fitness.time.sleep")
    @patch("krkn_ai.chaos_engines.fitness.env_is_truthy", return_value=False)
    def test_calculate_fitness_value_retries_on_empty_data(
        self, mock_env, mock_sleep, mock_prom_client
    ):
        fitness_function = FitnessFunction(
            query="sum(kube_pod_container_status_restarts_total)",
            type=FitnessFunctionType.point,
        )
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.side_effect = [
            [{"values": []}],
            [{"values": []}],
            [{"values": [[1000, "5"]]}],
            [{"values": [[2000, "10"]]}],
        ]

        start = datetime.datetime(2024, 1, 1, 12, 0, 0)
        end = datetime.datetime(2024, 1, 1, 12, 5, 0)

        score = calc.calculate_fitness_value(
            start,
            end,
            "sum(kube_pod_container_status_restarts_total)",
            FitnessFunctionType.point,
        )
        assert score == 5.0
        assert mock_prom_client.process_prom_query_in_range.call_count == 4

    @patch("krkn_ai.chaos_engines.fitness.time.sleep")
    @patch("krkn_ai.chaos_engines.fitness.env_is_truthy", return_value=False)
    def test_calculate_fitness_value_raises_after_retries_exhausted(
        self, mock_env, mock_sleep, mock_prom_client
    ):
        fitness_function = FitnessFunction(
            query="sum(kube_pod_container_status_restarts_total)",
            type=FitnessFunctionType.point,
        )
        calc = FitnessCalculator(mock_prom_client, fitness_function)

        mock_prom_client.process_prom_query_in_range.return_value = [{"values": []}]

        start = datetime.datetime(2024, 1, 1, 12, 0, 0)
        end = datetime.datetime(2024, 1, 1, 12, 5, 0)

        with pytest.raises(FitnessFunctionCalculationError) as exc_info:
            calc.calculate_fitness_value(
                start,
                end,
                "sum(kube_pod_container_status_restarts_total)",
                FitnessFunctionType.point,
            )

        assert "failed after 3 retries" in str(exc_info.value)
        assert mock_prom_client.process_prom_query_in_range.call_count == 3
