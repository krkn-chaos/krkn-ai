from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from krkn_ai.fitness.base import BaseFitnessEvaluator
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)

class WeightedAggregator(BaseFitnessEvaluator):
    """
    Aggregates results from multiple evaluators using weights.
    """

    def __init__(self, evaluators: List[Tuple[BaseFitnessEvaluator, float]]):
        """
        Args:
            evaluators: List of (evaluator, weight) tuples.
        """
        self.evaluators = evaluators

    @property
    def name(self) -> str:
        return "weighted_aggregator"

    def evaluate(
        self, 
        start_time: datetime, 
        end_time: datetime, 
        context: Optional[Dict[str, Any]] = None
    ) -> float:
        total_score = 0.0
        
        for evaluator, weight in self.evaluators:
            try:
                score = evaluator.evaluate(start_time, end_time, context)
                weighted_score = score * weight
                logger.debug(f"Evaluator '{evaluator.name}' score: {score}, weighted: {weighted_score}")
                total_score += weighted_score
            except Exception as e:
                logger.error(f"Error in evaluator '{evaluator.name}': {e}")
                
        return total_score
