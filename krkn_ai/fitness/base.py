from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from krkn_ai.models.app import CommandRunResult

class BaseFitnessEvaluator(ABC):
    """
    Abstract base class for all fitness evaluators.
    """
    
    @abstractmethod
    def calculate(self, result: CommandRunResult) -> float:
        """
        Calculates a fitness score based on the run result.
        
        Args:
            result: The result of the chaos scenario execution.
            
        Returns:
            A float representing the fitness score (higher is usually more "effective" chaos).
        """
        pass
