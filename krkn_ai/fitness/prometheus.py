import datetime
from krkn_ai.fitness.base import BaseFitnessEvaluator
from krkn_ai.models.app import CommandRunResult
from krkn_ai.models.config import FitnessFunctionType
from krkn_ai.models.custom_errors import FitnessFunctionCalculationError
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


class PrometheusEvaluator(BaseFitnessEvaluator):
    def __init__(self, prom_client, query: str, fitness_type: FitnessFunctionType):
        self.prom_client = prom_client
        self.query = query
        self.fitness_type = fitness_type

    def calculate(self, result: CommandRunResult) -> float:
        start = result.start_time
        end = result.end_time
        query = self.query

        if self.fitness_type == FitnessFunctionType.point:
            return self.calculate_point_fitness(start, end, query)
        elif self.fitness_type == FitnessFunctionType.range:
            return self.calculate_range_fitness(start, end, query)

        raise FitnessFunctionCalculationError(
            f"Unsupported fitness type: {self.fitness_type}"
        )

    def calculate_point_fitness(self, start, end, query):
        result_at_beginning = self._query_prometheus_single_point(
            query, start, "point fitness (start)"
        )
        result_at_end = self._query_prometheus_single_point(
            query, end, "point fitness (end)"
        )
        return float(result_at_end) - float(result_at_beginning)

    def calculate_range_fitness(self, start, end, query):
        if "$range$" in query:
            time_dt_mins = int((end - start).total_seconds() / 60)
            if time_dt_mins == 0:
                time_dt_mins = 1
            query = query.replace("$range$", f"{time_dt_mins}m")

        result = self.prom_client.process_prom_query_in_range(
            query,
            start_time=start,
            end_time=end,
            granularity=100,
        )
        if not result:
            raise FitnessFunctionCalculationError(
                f"Prometheus returned no data for query '{query}' in range "
                f"[{start}, {end}]. This may indicate the metric does not exist "
                f"in the requested time range or Prometheus has not yet scraped data."
            )

        for series in result:
            if series.get("values"):
                return float(series["values"][-1][1])
        raise FitnessFunctionCalculationError(
            f"Prometheus returned no data for query '{query}' in range "
            f"[{start}, {end}]. This may indicate the metric does not exist "
            f"in the requested time range or Prometheus has not yet scraped data."
        )

    def _query_prometheus_single_point(
        self, query: str, timestamp: datetime.datetime, context: str
    ) -> str:
        result = self.prom_client.process_prom_query_in_range(
            query,
            start_time=timestamp,
            end_time=timestamp,
            granularity=100,
        )
        if not result:
            raise FitnessFunctionCalculationError(
                f"Prometheus returned no data for query '{query}' at {timestamp} "
                f"during {context}. This may indicate the metric does not exist "
                f"in the requested time range or Prometheus has not yet scraped data."
            )
        for series in result:
            if series.get("values"):
                return series["values"][-1][1]
        raise FitnessFunctionCalculationError(
            f"Prometheus returned no data for query '{query}' at {timestamp} "
            f"during {context}. This may indicate the metric does not exist "
            f"in the requested time range or Prometheus has not yet scraped data."
        )
