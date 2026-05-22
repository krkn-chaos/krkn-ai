from typing import Dict, List, Optional
from krkn_ai.fitness.base import BaseFitnessEvaluator
from krkn_ai.models.app import CommandRunResult
from krkn_ai.chaos_engines.health_check_watcher import HealthCheckWatcher
from krkn_ai.models.config import HealthCheckConfig

class HealthCheckEvaluator(BaseFitnessEvaluator):
    def __init__(self, metric: str = "success_rate"):
        self.metric = metric

    def calculate(self, result: CommandRunResult) -> float:
        health_check_results = result.health_check_results
        if not health_check_results:
            return 0.0
            
        # Instantiate a dummy HealthCheckWatcher with an empty HealthCheckConfig to use its helper methods
        watcher = HealthCheckWatcher(HealthCheckConfig(applications=[]))
        
        if self.metric in ("success_rate", "failure_rate"):
            return watcher.summarize_success_rate(health_check_results)
        elif self.metric in ("response_time", "outliers"):
            return watcher.summarize_response_time(health_check_results)
            
        return 0.0
