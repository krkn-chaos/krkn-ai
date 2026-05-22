import time
from typing import Any, Dict
from krkn_ai.fitness.base import BaseFitnessEvaluator
from krkn_ai.fitness.prometheus import PrometheusEvaluator
from krkn_ai.fitness.health_check import HealthCheckEvaluator
from krkn_ai.models.app import CommandRunResult
from krkn_ai.models.config import EvaluatorConfig, FitnessFunctionType
from krkn_ai.models.custom_errors import FitnessFunctionCalculationError
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)


class RetryEvaluator(BaseFitnessEvaluator):
    def __init__(
        self,
        base_evaluator: BaseFitnessEvaluator,
        retries: int = 3,
        retry_delay: float = 10.0,
    ):
        self.base_evaluator = base_evaluator
        self.retries = retries
        self.retry_delay = retry_delay

    def calculate(self, result: CommandRunResult) -> float:
        for retry in range(self.retries):
            try:
                return self.base_evaluator.calculate(result)
            except Exception as error:
                logger.error(f"Fitness calculation failed: {error}")
                if retry < self.retries - 1:
                    logger.info(f"Retrying... (retry {retry + 1})")
                    time.sleep(self.retry_delay)

        raise FitnessFunctionCalculationError(
            f"Fitness failed after {self.retries} retries"
        )


class FitnessEvaluatorFactory:
    @staticmethod
    def create_evaluator(
        config: EvaluatorConfig, context: Dict[str, Any]
    ) -> BaseFitnessEvaluator:
        """
        Dynamically instantiate an evaluator by name/type.

        Args:
            config: The EvaluatorConfig object.
            context: Dictionary containing dependencies (like 'prom_client').
        """
        name = config.name.lower()
        properties = config.properties or {}

        if name in ("prometheus", "promql", "prom"):
            prom_client = context.get("prom_client")
            raw_query = properties.get("query")
            query = str(raw_query) if raw_query is not None else ""
            fitness_type_str = properties.get("type", "point")

            # Map string/Enum to FitnessFunctionType
            if isinstance(fitness_type_str, str):
                fitness_type = FitnessFunctionType(fitness_type_str)
            else:
                fitness_type = fitness_type_str

            return PrometheusEvaluator(prom_client, query, fitness_type)

        elif name in ("health_check", "healthcheck"):
            metric = properties.get("metric", "success_rate")
            return HealthCheckEvaluator(metric=metric)

        else:
            raise ValueError(f"Unknown evaluator type: {config.name}")
