import math
import datetime
import time

from krkn_ai.models.app import FitnessResult, FitnessScoreResult
from krkn_ai.models.config import FitnessFunctionType
from krkn_ai.models.custom_errors import (
    FitnessFunctionCalculationError,
    FitnessFunctionConfigurationError,
)
from krkn_ai.utils.fs import env_is_truthy
from krkn_ai.utils.logger import get_logger
from krkn_ai.utils.rng import rng

logger = get_logger(__name__)


class FitnessCalculator:
    def __init__(self, prom_client, fitness_function):
        self.prom_client = prom_client
        self.fitness_function = fitness_function

    def calculate_fitness_value(self, start, end, query, fitness_type):
        """Calculate fitness score for scenario run"""
        if env_is_truthy("MOCK_FITNESS"):
            return rng.random()

        retries = 3
        retry_delay = 10
        for retry in range(retries):
            try:
                if fitness_type == FitnessFunctionType.point:
                    return self.calculate_point_fitness(start, end, query)
                elif fitness_type == FitnessFunctionType.range:
                    return self.calculate_range_fitness(start, end, query)
            except FitnessFunctionConfigurationError:
                raise
            except Exception as error:
                logger.error(f"Fitness function calculation failed: {error}")
                logger.info(
                    f"Retrying fitness function calculation... (retry {retry + 1} of {retries})"
                )
                time.sleep(retry_delay)
        raise FitnessFunctionCalculationError(
            f"Fitness function calculation failed after {retries} retries"
        )

    def calculate_fitness_score_for_items(self, start, end):
        """Compute fitness scores when multiple SLOs are defined."""
        results = []
        overall_score = 0
        for fitness_item in self.fitness_function.items:
            raw_score = self.calculate_fitness_value(
                start=start,
                end=end,
                query=fitness_item.query,
                fitness_type=fitness_item.type,
            )
            fitness_value = fitness_item.weight * raw_score
            overall_score += fitness_value

            results.append(
                FitnessScoreResult(
                    id=fitness_item.id,
                    fitness_score=raw_score,
                    weighted_score=fitness_value,
                )
            )

        return FitnessResult(fitness_score=overall_score, scores=results)

    def calculate_point_fitness(self, start, end, query):
        """Takes difference between fitness function at start/end intervals of test.
        Helpful to measure values for counter based metric like restarts.
        """
        logger.debug("Calculating Point Fitness")
        result_at_beginning = self._query_prometheus_single_point(
            query, start, "point fitness (start)"
        )
        result_at_end = self._query_prometheus_single_point(
            query, end, "point fitness (end)"
        )

        return float(result_at_end) - float(result_at_beginning)

    def _query_prometheus_single_point(
        self, query: str, timestamp: datetime.datetime, context: str
    ) -> str:
        result = self.prom_client.process_prom_query_in_range(
            query,
            start_time=timestamp,
            end_time=timestamp,
            granularity=100,
        )
        no_data_error = (
            f"Prometheus returned no data for query '{query}' at {timestamp} "
            f"during {context}. This may indicate the metric does not exist "
            f"in the requested time range or Prometheus has not yet scraped data."
        )
        return self._extract_single_prometheus_value(
            result,
            query,
            context,
            no_data_error,
        )

    def _extract_single_prometheus_value(
        self, result, query: str, context: str, no_data_error: str
    ) -> str:
        series_list = result or []
        if len(series_list) > 1:
            raise FitnessFunctionConfigurationError(
                f"Prometheus returned {len(series_list)} series for query "
                f"'{query}' during {context}. Fitness queries must return exactly "
                "one series. Use sum(), max(), avg(), or another PromQL aggregate "
                "before using this query as a fitness function."
            )

        if not series_list or not series_list[0].get("values"):
            raise FitnessFunctionCalculationError(no_data_error)
        return series_list[0]["values"][-1][1]

    def calculate_range_fitness(self, start, end, query):
        """Measure fitness function for the range of test."""
        logger.debug("Calculating Range Fitness")

        if "$range$" in query:
            time_dt_mins = math.ceil((end - start).total_seconds() / 60)
            if time_dt_mins == 0:
                time_dt_mins = 1
            query = query.replace("$range$", f"{time_dt_mins}m")
        else:
            logger.warning(
                "You are missing $range$ in config.fitness_function.query to specify dynamic range. Fitness function will use specified range"
            )

        result = self.prom_client.process_prom_query_in_range(
            query,
            start_time=start,
            end_time=end,
            granularity=100,
        )
        no_data_error = (
            f"Prometheus returned no data for query '{query}' in range "
            f"[{start}, {end}]. This may indicate the metric does not exist "
            f"in the requested time range or Prometheus has not yet scraped data."
        )

        return float(
            self._extract_single_prometheus_value(
                result,
                query,
                f"range fitness [{start}, {end}]",
                no_data_error,
            )
        )
