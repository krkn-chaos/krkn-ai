import pytest
from datetime import datetime
from unittest.mock import Mock, patch
from krkn_ai.fitness.prometheus import PrometheusEvaluator
from krkn_ai.fitness.health_check import HealthCheckEvaluator
from krkn_ai.fitness.python_script import PythonScriptEvaluator
from krkn_ai.fitness.aggregator import WeightedAggregator
from krkn_ai.models.config import FitnessFunctionType, HealthCheckResult
from krkn_ai.models.custom_errors import FitnessFunctionCalculationError

class TestPrometheusEvaluator:
    def test_evaluate_point_success(self):
        mock_prom = Mock()
        mock_prom.process_prom_query_in_range.side_effect = [
            [{"values": [[1000, "10"]]}], # start
            [{"values": [[2000, "25"]]}]  # end
        ]
        
        evaluator = PrometheusEvaluator(mock_prom, "my_query", FitnessFunctionType.point, retries=1)
        score = evaluator.evaluate(datetime.now(), datetime.now())
        assert score == 15.0

    def test_evaluate_range_success(self):
        mock_prom = Mock()
        mock_prom.process_prom_query_in_range.return_value = [{"values": [[1000, "50"]]}]
        
        evaluator = PrometheusEvaluator(mock_prom, "my_query", FitnessFunctionType.range, retries=1)
        score = evaluator.evaluate(datetime.now(), datetime.now())
        assert score == 50.0

    def test_evaluate_retries(self):
        mock_prom = Mock()
        mock_prom.process_prom_query_in_range.side_effect = [
            Exception("fail"),
            [{"values": [[1000, "10"]]}],
            [{"values": [[2000, "15"]]}]
        ]
        
        with patch("time.sleep"): # avoid actual sleeping
            evaluator = PrometheusEvaluator(mock_prom, "query", retries=2)
            score = evaluator.evaluate(datetime.now(), datetime.now())
            assert score == 5.0

class TestHealthCheckEvaluator:
    def test_success_rate_mode(self):
        evaluator = HealthCheckEvaluator(mode="success_rate")
        context = {
            "health_check_results": {
                "url1": [
                    HealthCheckResult(name="t1", status_code=200, success=True, response_time=0.1),
                    HealthCheckResult(name="t1", status_code=500, success=False, response_time=0.1)
                ]
            }
        }
        score = evaluator.evaluate(datetime.now(), datetime.now(), context)
        assert score == 5.0 # 50% failure * 10

    def test_response_time_mode(self):
        evaluator = HealthCheckEvaluator(mode="response_time")
        # Need at least 4 successful results to calculate IQR
        times = [0.1, 0.1, 0.1, 1.0] # 1.0 is clearly an outlier
        results = [HealthCheckResult(name="t", status_code=200, success=True, response_time=t) for t in times]
        context = {"health_check_results": {"url": results}}
        
        score = evaluator.evaluate(datetime.now(), datetime.now(), context)
        assert score > 0

class TestWeightedAggregator:
    def test_aggregation(self):
        eval1 = Mock()
        eval1.evaluate.return_value = 10.0
        eval1.name = "e1"
        
        eval2 = Mock()
        eval2.evaluate.return_value = 5.0
        eval2.name = "e2"
        
        aggregator = WeightedAggregator([
            (eval1, 0.6),
            (eval2, 0.4)
        ])
        
        score = aggregator.evaluate(datetime.now(), datetime.now())
        assert score == (10 * 0.6) + (5 * 0.4) # 6 + 2 = 8.0
