from unittest.mock import MagicMock, patch

import pytest

from krkn_ai.chaos_engines.fitness import FitnessCalculator
from krkn_ai.models.config import FitnessFunction, FitnessFunctionItem
from krkn_ai.models.custom_errors import FitnessFunctionConfigurationError


class TestPreflightCheck:
    def setup_method(self):
        self.mock_sleep = patch("time.sleep").start()

        self.mock_prom_client = MagicMock()

    @patch("krkn_ai.chaos_engines.fitness.env_is_truthy")
    def test_mock_fitness_skips_preflight(self, mock_env_is_truthy):
        mock_env_is_truthy.return_value = True
        fitness_function = FitnessFunction(query="up")
        calculator = FitnessCalculator(self.mock_prom_client, fitness_function)

        calculator.preflight_check()

        self.mock_prom_client.process_prom_query_in_range.assert_not_called()

    @patch("krkn_ai.chaos_engines.fitness.env_is_truthy")
    def test_valid_query_passes_preflight(self, mock_env_is_truthy):
        mock_env_is_truthy.return_value = False
        self.mock_prom_client.process_prom_query_in_range.return_value = [
            {"metric": {}, "values": [[1620000000, "1"]]}
        ]

        fitness_function = FitnessFunction(query="up")
        calculator = FitnessCalculator(self.mock_prom_client, fitness_function)

        calculator.preflight_check()

        self.mock_prom_client.process_prom_query_in_range.assert_called_once()
        args, kwargs = self.mock_prom_client.process_prom_query_in_range.call_args
        assert args[0] == "up"
        assert kwargs["granularity"] == 100

    @patch("krkn_ai.chaos_engines.fitness.env_is_truthy")
    def test_range_variable_substituted(self, mock_env_is_truthy):
        mock_env_is_truthy.return_value = False
        self.mock_prom_client.process_prom_query_in_range.return_value = [
            {"metric": {}, "values": [[1620000000, "1"]]}
        ]

        fitness_function = FitnessFunction(query="sum(rate(up[$range$]))")
        calculator = FitnessCalculator(self.mock_prom_client, fitness_function)

        calculator.preflight_check()

        args, _ = self.mock_prom_client.process_prom_query_in_range.call_args
        assert args[0] == "sum(rate(up[5m]))"

    @patch("krkn_ai.chaos_engines.fitness.env_is_truthy")
    def test_empty_results_raises_error(self, mock_env_is_truthy):
        mock_env_is_truthy.return_value = False
        self.mock_prom_client.process_prom_query_in_range.return_value = []

        fitness_function = FitnessFunction(query="non_existent_metric")
        calculator = FitnessCalculator(self.mock_prom_client, fitness_function)

        with pytest.raises(FitnessFunctionConfigurationError, match="returned no data"):
            calculator.preflight_check()

        assert self.mock_prom_client.process_prom_query_in_range.call_count == 3

    @patch("krkn_ai.chaos_engines.fitness.env_is_truthy")
    def test_multiple_series_raises_error(self, mock_env_is_truthy):
        mock_env_is_truthy.return_value = False
        self.mock_prom_client.process_prom_query_in_range.return_value = [
            {"metric": {"instance": "a"}, "values": [[1620000000, "1"]]},
            {"metric": {"instance": "b"}, "values": [[1620000000, "1"]]},
        ]

        fitness_function = FitnessFunction(query="up")
        calculator = FitnessCalculator(self.mock_prom_client, fitness_function)

        with pytest.raises(
            FitnessFunctionConfigurationError, match="returned 2 series"
        ):
            calculator.preflight_check()

    @patch("krkn_ai.chaos_engines.fitness.env_is_truthy")
    def test_validates_multiple_items(self, mock_env_is_truthy):
        mock_env_is_truthy.return_value = False
        self.mock_prom_client.process_prom_query_in_range.return_value = [
            {"metric": {}, "values": [[1620000000, "1"]]}
        ]

        item1 = FitnessFunctionItem(query="up")
        item2 = FitnessFunctionItem(query="kube_pod_status_ready")
        fitness_function = FitnessFunction(items=[item1, item2])

        calculator = FitnessCalculator(self.mock_prom_client, fitness_function)

        calculator.preflight_check()

        assert self.mock_prom_client.process_prom_query_in_range.call_count == 2

    @patch("krkn_ai.chaos_engines.fitness.env_is_truthy")
    def test_empty_query_fails_preflight(self, mock_env_is_truthy):
        mock_env_is_truthy.return_value = False
        self.mock_prom_client.process_prom_query_in_range.return_value = []

        fitness_function = FitnessFunction(query="")
        calculator = FitnessCalculator(self.mock_prom_client, fitness_function)

        with pytest.raises(FitnessFunctionConfigurationError, match="returned no data"):
            calculator.preflight_check()
