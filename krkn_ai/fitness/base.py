from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional

class BaseFitnessEvaluator(ABC):
    """
    Abstract base class for all fitness evaluators.
    Evaluators are responsible for calculating a score based on cluster state,
    metrics, or external health checks after a chaos scenario run.
    """

    @abstractmethod
    def evaluate(
        self, 
        start_time: datetime, 
        end_time: datetime, 
        context: Optional[Dict[str, Any]] = None
    ) -> float:
        """
        Calculate the fitness score for a given time range.
        
        Args:
            start_time: Start of the chaos scenario execution.
            end_time: End of the chaos scenario execution.
            context: Additional metadata or objects (e.g., cluster manager, logs).
            
        Returns:
            A float representing the fitness score.
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the unique name of the evaluator."""
        pass
