"""
FitnessCalculator tests — extracted from test_krkn_runner.py
"""

import datetime
import pytest
from unittest.mock import Mock, patch

from krkn_ai.chaos_engines.fitness import (
    FitnessCalculator,
    normalize_generation_scores,
    normalize_weights,
)
from krkn_ai.models.app import CommandRunResult, FitnessResult, FitnessScoreResult
from krkn_ai.models.config import (
    FitnessFunction,
    FitnessFunctionItem,
    FitnessFunctionType,
)
from krkn_ai.models.custom_errors import (
    FitnessFunctionCalculationError,
    FitnessFunctionConfigurationError,
)
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.scenario.scenario_dummy import DummyScenario


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
    @patch("krkn_ai.chaos_engines.fitness.is_mock_enabled", return_value=False)
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
    @patch("krkn_ai.chaos_engines.fitness.is_mock_enabled", return_value=False)
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
    @patch("krkn_ai.chaos_engines.fitness.is_mock_enabled", return_value=False)
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


class TestFitnessWeightAllocation:
    def test_normalize_weights_preserves_relative_coefficients(self):
        assert normalize_weights([8, 2]) == [0.8, 0.2]

    def test_normalize_zero_weights_falls_back_to_equal_allocation(self):
        assert normalize_weights([0, 0]) == [0.5, 0.5]

    def test_normalize_weights_rejects_negative_values(self):
        with pytest.raises(FitnessFunctionConfigurationError, match="non-negative"):
            normalize_weights([1, -1])

    def test_item_scores_use_normalized_weights(self):
        fitness_function = FitnessFunction(
            items=[
                {"query": "first", "weight": 8},
                {"query": "second", "weight": 2},
            ]
        )
        calc = FitnessCalculator(Mock(), fitness_function)
        calc.calculate_fitness_value = Mock(side_effect=[10.0, 20.0])

        result = calc.calculate_fitness_score_for_items(
            datetime.datetime(2024, 1, 1), datetime.datetime(2024, 1, 1, 0, 5)
        )

        assert result.fitness_score == 12.0
        assert [score.weighted_score for score in result.scores] == [8.0, 4.0]


def _make_result(
    scores: list,
    hc_failure: float = 0.0,
    hc_response: float = 0.0,
    krkn: float = 0.0,
    fitness: float = 0.0,
) -> CommandRunResult:
    """Helper to build a CommandRunResult with given per-SLO scores."""
    fitness_result = FitnessResult(
        scores=[
            FitnessScoreResult(id=s[0], fitness_score=s[1], weighted_score=s[2])
            for s in scores
        ],
        health_check_failure_score=hc_failure,
        health_check_response_time_score=hc_response,
        krkn_failure_score=krkn,
        fitness_score=fitness,
    )
    return CommandRunResult(
        generation_id=0,
        scenario=DummyScenario(cluster_components=ClusterComponents()),
        cmd="",
        log="",
        returncode=0,
        start_time=datetime.datetime(2024, 1, 1),
        end_time=datetime.datetime(2024, 1, 1, 0, 5),
        fitness_result=fitness_result,
        health_check_results={},
    )


class TestNormalizeGenerationScores:
    """Tests for log + min-max normalization of Prometheus scores."""

    def test_equalizes_scales_across_items(self):
        """Weight 0.8 item should dominate weight 0.2 item regardless of raw scale."""
        items = [
            FitnessFunctionItem(id=1, query="q1", weight=8),
            FitnessFunctionItem(id=2, query="q2", weight=2),
        ]
        # Scenario A: item1=3 (small), item2=500_000_000 (huge)
        # Scenario B: item1=1 (smaller), item2=100_000_000 (less huge)
        r_a = _make_result([(1, 3.0, 0.0), (2, 500_000_000.0, 0.0)], fitness=0.0)
        r_b = _make_result([(1, 1.0, 0.0), (2, 100_000_000.0, 0.0)], fitness=0.0)

        normalize_generation_scores([r_a, r_b], items)

        # After normalization, item 1 (weight 0.8) should contribute most
        score_a = r_a.fitness_result.fitness_score
        score_b = r_b.fitness_result.fitness_score
        # r_a has higher item1 (weight 0.8) and higher item2 (weight 0.2)
        assert score_a > score_b

        # The 0.8-weighted item's contribution should exceed the 0.2-weighted
        item1_contribution_a = r_a.fitness_result.scores[0].weighted_score
        item2_contribution_a = r_a.fitness_result.scores[1].weighted_score
        assert item1_contribution_a > item2_contribution_a

    def test_preserves_raw_fitness_score(self):
        """Raw fitness_score on FitnessScoreResult should not be modified."""
        items = [FitnessFunctionItem(id=1, query="q1", weight=1)]
        r_a = _make_result([(1, 42.0, 42.0)], fitness=42.0)
        r_b = _make_result([(1, 10.0, 10.0)], fitness=10.0)

        normalize_generation_scores([r_a, r_b], items)

        assert r_a.fitness_result.scores[0].fitness_score == 42.0
        assert r_b.fitness_result.scores[0].fitness_score == 10.0

    def test_sets_normalized_score(self):
        """normalized_score should be set on each FitnessScoreResult."""
        items = [FitnessFunctionItem(id=1, query="q1", weight=1)]
        r_a = _make_result([(1, 100.0, 0.0)], fitness=0.0)
        r_b = _make_result([(1, 10.0, 0.0)], fitness=0.0)

        normalize_generation_scores([r_a, r_b], items)

        assert r_a.fitness_result.scores[0].normalized_score == 1.0
        assert r_b.fitness_result.scores[0].normalized_score == 0.0

    def test_skips_misconfiguration_results(self):
        """Results with fitness_score == -1.0 should be untouched."""
        items = [FitnessFunctionItem(id=1, query="q1", weight=1)]
        r_good = _make_result([(1, 50.0, 0.0)], fitness=50.0)
        r_bad = _make_result([(1, 99.0, 0.0)], fitness=-1.0)

        normalize_generation_scores([r_good, r_bad], items)

        assert r_bad.fitness_result.fitness_score == -1.0
        assert r_bad.fitness_result.scores[0].normalized_score is None

    def test_single_result_is_noop(self):
        """With only one valid result, normalization is skipped."""
        items = [FitnessFunctionItem(id=1, query="q1", weight=1)]
        r = _make_result([(1, 42.0, 42.0)], fitness=42.0)

        normalize_generation_scores([r], items)

        assert r.fitness_result.scores[0].normalized_score is None
        assert r.fitness_result.fitness_score == 42.0

    def test_identical_values_normalize_to_midpoint(self):
        """When all scenarios return the same raw score, normalize to 0.5."""
        items = [FitnessFunctionItem(id=1, query="q1", weight=1)]
        r_a = _make_result([(1, 7.0, 0.0)], fitness=0.0)
        r_b = _make_result([(1, 7.0, 0.0)], fitness=0.0)

        normalize_generation_scores([r_a, r_b], items)

        assert r_a.fitness_result.scores[0].normalized_score == 0.5
        assert r_b.fitness_result.scores[0].normalized_score == 0.5

    def test_recomputes_overall_fitness_with_other_scores(self):
        """Overall fitness_score should be normalized_prometheus + other sub-scores."""
        items = [FitnessFunctionItem(id=1, query="q1", weight=1)]
        r_a = _make_result(
            [(1, 100.0, 0.0)], hc_failure=0.3, hc_response=0.2, krkn=0.1, fitness=0.0
        )
        r_b = _make_result(
            [(1, 10.0, 0.0)], hc_failure=0.0, hc_response=0.0, krkn=0.0, fitness=0.0
        )

        normalize_generation_scores([r_a, r_b], items, num_components=4)

        # r_a: raw = 1.0 + 0.3 + 0.2 + 0.1 = 1.6 → pct = 1.6/4*100 = 40.0
        assert r_a.fitness_result.fitness_score == pytest.approx(40.0)
        # r_b: raw = 0.0 + 0 + 0 + 0 = 0.0 → pct = 0.0
        assert r_b.fitness_result.fitness_score == pytest.approx(0.0)
