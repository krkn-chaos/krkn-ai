from datetime import datetime
from typing import Any, Dict, List, Optional
from krkn_ai.fitness.base import BaseFitnessEvaluator
from krkn_ai.models.config import HealthCheckResult
from krkn_ai.utils.logger import get_logger
import numpy as np

logger = get_logger(__name__)


class HealthCheckEvaluator(BaseFitnessEvaluator):
    """
    Evaluates fitness based on application health check results collected during the run.
    """

    def __init__(self, mode: str = "success_rate"):
        """
        Args:
            mode: Either 'success_rate' (failure frequency) or 'response_time' (outliers).
        """
        self.mode = mode

    @property
    def name(self) -> str:
        # Map success_rate to failure to match legacy flag naming
        mode_name = "failure" if self.mode == "success_rate" else self.mode
        return f"health_check_{mode_name}"

    def evaluate(
        self,
        start_time: datetime,
        end_time: datetime,
        context: Optional[Dict[str, Any]] = None,
    ) -> float:
        if not context or "health_check_results" not in context:
            logger.warning("No health check results found in context")
            return 0.0

        results: Dict[str, List[HealthCheckResult]] = context["health_check_results"]

        if self.mode == "success_rate":
            return self._summarize_success_rate(results)
        elif self.mode == "response_time":
            return self._summarize_response_time(results)
        else:
            logger.error(f"Unknown health check mode: {self.mode}")
            return 0.0

    def _summarize_success_rate(
        self, results: Dict[str, List[HealthCheckResult]]
    ) -> float:
        all_results = []
        for result_list in results.values():
            all_results.extend(result_list)

        total = len(all_results)
        if total == 0:
            return 0.0
        failed = sum(1 for r in all_results if not r.success)
        score = (failed / total) * 10.0
        return float(score)

    def _summarize_response_time(
        self, results: Dict[str, List[HealthCheckResult]]
    ) -> float:
        score: float = 0.0
        total_checks = 0

        for _, res_list in results.items():
            response_times = [r.response_time for r in res_list if r.success]

            if len(response_times) < 4:
                continue

            q1 = np.percentile(response_times, 25)
            q3 = np.percentile(response_times, 75)
            iqr = q3 - q1
            upper_bound = q3 + (1.5 * iqr)

            outliers = [t for t in response_times if t > upper_bound]
            score += len(outliers)
            total_checks += len(res_list)

        if total_checks == 0:
            return 0.0

        return (score / total_checks) * 10.0
