import time
from datetime import datetime
from typing import Any, Dict, Optional
from krkn_ai.fitness.base import BaseFitnessEvaluator
from krkn_ai.models.config import FitnessFunctionType
from krkn_ai.models.custom_errors import FitnessFunctionCalculationError
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


class PrometheusEvaluator(BaseFitnessEvaluator):
    """
    Evaluates fitness using PromQL queries against a Prometheus instance.
    """

    def __init__(
        self,
        prom_client: Any,
        query: str,
        fitness_type: FitnessFunctionType = FitnessFunctionType.point,
        retries: int = 3,
        retry_delay: int = 10,
    ):
        self.prom_client = prom_client
        self.query = query
        self.fitness_type = fitness_type
        self.retries = retries
        self.retry_delay = retry_delay

    @property
    def name(self) -> str:
        return "prometheus"

    def evaluate(
        self,
        start_time: datetime,
        end_time: datetime,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        for retry in range(self.retries):
            try:
                if self.fitness_type == FitnessFunctionType.point:
                    return self._calculate_point_fitness(start_time, end_time)
                elif self.fitness_type == FitnessFunctionType.range:
                    return self._calculate_range_fitness(start_time, end_time)
            except Exception as error:
                logger.error(f"Prometheus evaluation failed: {error}")
                if retry < self.retries - 1:
                    logger.info(f"Retrying... (retry {retry + 1} of {self.retries})")
                    time.sleep(self.retry_delay)
                else:
                    raise FitnessFunctionCalculationError(
                        f"Prometheus evaluation failed after {self.retries} retries"
                    )
        return 0.0

    def _calculate_point_fitness(self, start: datetime, end: datetime) -> float:
        val_start = self._query_single_point(self.query, start, "start")
        val_end = self._query_single_point(self.query, end, "end")
        return float(val_end) - float(val_start)

    def _calculate_range_fitness(self, start: datetime, end: datetime) -> float:
        query = self.query
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
            raise FitnessFunctionCalculationError(f"No data for range query: {query}")

        for series in result:
            if series.get("values"):
                return float(series["values"][-1][1])

        raise FitnessFunctionCalculationError(
            f"No values found for range query: {query}"
        )

    def _query_single_point(self, query: str, timestamp: datetime, label: str) -> str:
        result = self.prom_client.process_prom_query_in_range(
            query,
            start_time=timestamp,
            end_time=timestamp,
            granularity=100,
        )
        if not result:
            raise FitnessFunctionCalculationError(f"No data for {label} query: {query}")

        for series in result:
            if series.get("values"):
                return series["values"][-1][1]

        raise FitnessFunctionCalculationError(
            f"No values found for {label} query: {query}"
        )
