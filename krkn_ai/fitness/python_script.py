import importlib.util
import os
from datetime import datetime
from typing import Any, Dict, Optional
from krkn_ai.fitness.base import BaseFitnessEvaluator
from krkn_ai.utils.logger import get_logger

logger = get_logger(__name__)

class PythonScriptEvaluator(BaseFitnessEvaluator):
    """
    Evaluates fitness by executing a custom Python script.
    The script should define a function `evaluate(start_time, end_time, context)`.
    """

    def __init__(self, script_path: str):
        self.script_path = script_path
        self._module = None
        self._load_script()

    def _load_script(self):
        if not os.path.exists(self.script_path):
            logger.error(f"Python script not found: {self.script_path}")
            return

        try:
            spec = importlib.util.spec_from_file_location("custom_evaluator", self.script_path)
            if spec and spec.loader:
                self._module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(self._module)
                if not hasattr(self._module, "evaluate"):
                    logger.error(f"Script {self.script_path} does not define 'evaluate' function")
                    self._module = None
        except Exception as e:
            logger.error(f"Failed to load python script {self.script_path}: {e}")

    @property
    def name(self) -> str:
        return f"python_script_{os.path.basename(self.script_path)}"

    def evaluate(
        self, 
        start_time: datetime, 
        end_time: datetime, 
        context: Optional[Dict[str, Any]] = None
    ) -> float:
        if self._module and hasattr(self._module, "evaluate"):
            try:
                result = self._module.evaluate(start_time, end_time, context)
                return float(result)
            except Exception as e:
                logger.error(f"Error executing custom evaluator script: {e}")
        return 0.0
