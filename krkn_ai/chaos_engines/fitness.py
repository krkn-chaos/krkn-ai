import math
import datetime
import time
from typing import Iterable, List

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


def normalize_weights(weights: Iterable[float]) -> List[float]:
    """Convert relative fitness coefficients into weights summing to one.

    Users can now choose readable coefficients such as ``8`` and ``2`` in YAML
    without changing the scale of the overall fitness score.  An all-zero set
    is treated as equal weighting so a disabled-looking configuration does not
    silently discard every fitness signal.
    """
    values = [float(weight) for weight in weights]
    if not values:
        return []
    if any(not math.isfinite(weight) or weight < 0 for weight in values):
        raise FitnessFunctionConfigurationError(
            "Fitness query weights must be finite non-negative numbers"
        )
    total = sum(values)
    if total == 0:
        return [1.0 / len(values)] * len(values)
    return [weight / total for weight in values]


class FitnessCalculator:
    def __init__(self, prom_client, fitness_function):
        self.prom_client = prom_client
        self.fitness_function = fitness_function

    def preflight_check(self) -> None:
        """Validate all fitness queries return data before the experiment starts."""
        if env_is_truthy("MOCK_FITNESS"):
            return

        now = datetime.datetime.now()
        start = now - datetime.timedelta(minutes=5)

        if getattr(self.fitness_function, "query", None) is not None:
            self._validate_query(
                self.fitness_function.query, "fitness_function.query", start, now
            )

        for item in getattr(self.fitness_function, "items", []):
            self._validate_query(
                item.query, f"fitness_function.items[{item.id}]", start, now
            )

    def _validate_query(
        self, query: str, context: str, start: datetime.datetime, end: datetime.datetime
    ):
        """Run a dry-run query and raise if Prometheus returns no data or multiple series."""
        test_query = query.replace("$range$", "5m") if "$range$" in query else query

        retries = 3
        retry_delay = 5

        for attempt in range(retries):
            try:
                result = self.prom_client.process_prom_query_in_range(
                    test_query,
                    start_time=start,
                    end_time=end,
                    granularity=100,
                )

                series_list = result or []
                if len(series_list) > 1:
                    raise FitnessFunctionConfigurationError(
                        f"Pre-flight check failed: query '{query}' ({context}) "
                        f"returned {len(series_list)} series. Fitness queries must return exactly "
                        f"one series. Use sum(), max(), avg(), or another PromQL aggregate."
                    )
                if not series_list or not series_list[0].get("values"):
                    if attempt < retries - 1:
                        logger.warning(
                            f"Pre-flight check: query '{query}' returned no data. Retrying... ({attempt + 1}/{retries})"
                        )
                        time.sleep(retry_delay)
                        continue
                    else:
                        raise FitnessFunctionConfigurationError(
                            f"Pre-flight check failed: query '{query}' ({context}) "
                            f"returned no data. This query will fail during the experiment. "
                            f"Verify the metric exists and the namespace selector is correct."
                        )
                # Success
                return
            except FitnessFunctionConfigurationError:
                raise
            except Exception as e:
                if attempt < retries - 1:
                    logger.warning(
                        f"Pre-flight check errored: {e}. Retrying... ({attempt + 1}/{retries})"
                    )
                    time.sleep(retry_delay)
                    continue
                else:
                    raise FitnessFunctionConfigurationError(
                        f"Pre-flight check failed: query '{query}' ({context}) "
                        f"errored: {e}. Fix this before starting the experiment."
                    )

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
        weights = normalize_weights(
            fitness_item.weight for fitness_item in self.fitness_function.items
        )
        for fitness_item, weight in zip(self.fitness_function.items, weights):
            raw_score = self.calculate_fitness_value(
                start=start,
                end=end,
                query=fitness_item.query,
                fitness_type=fitness_item.type,
            )
            fitness_value = weight * raw_score
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
