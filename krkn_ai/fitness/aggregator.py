from typing import Any, Dict, List
from krkn_ai.fitness.factory import FitnessEvaluatorFactory, RetryEvaluator
from krkn_ai.models.app import CommandRunResult, FitnessResult, FitnessScoreResult
from krkn_ai.models.config import EvaluatorConfig
from krkn_ai.utils.logger import get_logger
from krkn_ai.utils.fs import env_is_truthy
from krkn_ai.utils.rng import rng

logger = get_logger(__name__)


class WeightedAggregator:
    def __init__(
        self, evaluator_configs: List[EvaluatorConfig], context: Dict[str, Any]
    ):
        self.evaluator_configs = evaluator_configs
        self.context = context

    def aggregate(self, result: CommandRunResult) -> FitnessResult:
        """
        Executes each evaluator, applies weights, and returns a FitnessResult.
        """
        if env_is_truthy("MOCK_FITNESS"):
            scores = []
            overall_score = 0.0
            for config in self.evaluator_configs:
                raw_score = rng.random()
                weighted = config.weight * raw_score
                overall_score += weighted
                evaluator_id = config.properties.get("id")
                if evaluator_id is None:
                    evaluator_id = hash(config.name) & 0xFFFFFFFF
                scores.append(
                    FitnessScoreResult(
                        id=evaluator_id,
                        fitness_score=raw_score,
                        weighted_score=weighted,
                    )
                )
            return FitnessResult(fitness_score=overall_score, scores=scores)

        overall_score = 0.0
        scores = []

        for config in self.evaluator_configs:
            try:
                # Instantiate evaluator using factory
                evaluator = FitnessEvaluatorFactory.create_evaluator(
                    config, self.context
                )

                # Wrap with RetryEvaluator if it is a Prometheus evaluator to handle scrape delays
                if config.name.lower() in ("prometheus", "promql", "prom"):
                    evaluator = RetryEvaluator(evaluator, retries=3, retry_delay=10.0)

                # Calculate raw score
                raw_score = evaluator.calculate(result)
                weighted_score = config.weight * raw_score
                overall_score += weighted_score

                # Get the evaluator ID from properties (default to a stable integer hash of config.name)
                evaluator_id = config.properties.get("id")
                if evaluator_id is None:
                    # Let's generate a stable integer id for the score result
                    evaluator_id = hash(config.name) & 0xFFFFFFFF

                scores.append(
                    FitnessScoreResult(
                        id=evaluator_id,
                        fitness_score=raw_score,
                        weighted_score=weighted_score,
                    )
                )
            except Exception as e:
                logger.error(f"Error during evaluator '{config.name}' execution: {e}")
                raise

        return FitnessResult(fitness_score=overall_score, scores=scores)
