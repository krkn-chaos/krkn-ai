import pytest
from unittest.mock import Mock, patch
import datetime
from krkn_ai.models.app import CommandRunResult, FitnessResult, HealthCheckResult
from krkn_ai.models.config import EvaluatorConfig, FitnessFunctionType
from krkn_ai.fitness.factory import FitnessEvaluatorFactory, RetryEvaluator
from krkn_ai.fitness.prometheus import PrometheusEvaluator
from krkn_ai.fitness.health_check import HealthCheckEvaluator
from krkn_ai.fitness.aggregator import WeightedAggregator
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.cluster_components import ClusterComponents

def test_health_check_evaluator_success_rate():
    evaluator = HealthCheckEvaluator(metric="success_rate")
    
    # 2 successes, 2 failures -> 50% success/failure rate -> (2/4)*10 = 5.0 score
    health_results = {
        "http://app1": [
            HealthCheckResult(name="app1", status_code=200, success=True, response_time=0.1),
            HealthCheckResult(name="app1", status_code=200, success=True, response_time=0.12),
            HealthCheckResult(name="app1", status_code=500, success=False, error="Error", response_time=-1),
            HealthCheckResult(name="app1", status_code=500, success=False, error="Error", response_time=-1),
        ]
    }
    
    result = CommandRunResult(
        generation_id=0,
        scenario=DummyScenario(cluster_components=ClusterComponents()),
        cmd="", log="", returncode=0, duration_seconds=0,
        start_time=datetime.datetime.now(),
        end_time=datetime.datetime.now(),
        fitness_result=FitnessResult(),
        health_check_results=health_results
    )
    
    score = evaluator.calculate(result)
    assert score == 5.0

def test_health_check_evaluator_no_results():
    evaluator = HealthCheckEvaluator(metric="success_rate")
    result = CommandRunResult(
        generation_id=0,
        scenario=DummyScenario(cluster_components=ClusterComponents()),
        cmd="", log="", returncode=0, duration_seconds=0,
        start_time=datetime.datetime.now(),
        end_time=datetime.datetime.now(),
        fitness_result=FitnessResult(),
        health_check_results={}
    )
    score = evaluator.calculate(result)
    assert score == 0.0

def test_fitness_evaluator_factory_creation():
    context = {"prom_client": Mock()}
    
    # Prometheus config
    prom_config = EvaluatorConfig(
        name="prometheus",
        weight=1.5,
        properties={"query": "up", "type": "point"}
    )
    evaluator = FitnessEvaluatorFactory.create_evaluator(prom_config, context)
    assert isinstance(evaluator, PrometheusEvaluator)
    assert evaluator.query == "up"
    assert evaluator.fitness_type == FitnessFunctionType.point
    
    # Health check config
    hc_config = EvaluatorConfig(
        name="health_check",
        weight=2.0,
        properties={"metric": "outliers"}
    )
    evaluator = FitnessEvaluatorFactory.create_evaluator(hc_config, context)
    assert isinstance(evaluator, HealthCheckEvaluator)
    assert evaluator.metric == "outliers"

def test_weighted_aggregator():
    # Configure two evaluators: one health check success_rate and one health check outliers
    eval_configs = [
        EvaluatorConfig(
            name="health_check",
            weight=0.6,
            properties={"id": 1, "metric": "success_rate"}
        ),
        EvaluatorConfig(
            name="health_check",
            weight=0.4,
            properties={"id": 2, "metric": "outliers"}
        )
    ]
    
    # Mock health results to have 25% failure (2.5 score) and 0 outliers (0.0 score)
    health_results = {
        "http://app1": [
            HealthCheckResult(name="app1", status_code=200, success=True, response_time=0.1),
            HealthCheckResult(name="app1", status_code=200, success=True, response_time=0.12),
            HealthCheckResult(name="app1", status_code=200, success=True, response_time=0.13),
            HealthCheckResult(name="app1", status_code=500, success=False, error="Error", response_time=-1),
        ]
    }
    
    result = CommandRunResult(
        generation_id=0,
        scenario=DummyScenario(cluster_components=ClusterComponents()),
        cmd="", log="", returncode=0, duration_seconds=0,
        start_time=datetime.datetime.now(),
        end_time=datetime.datetime.now(),
        fitness_result=FitnessResult(),
        health_check_results=health_results
    )
    
    aggregator = WeightedAggregator(eval_configs, {})
    fitness_res = aggregator.aggregate(result)
    
    # Expected scores:
    # id 1: raw score = 2.5, weighted = 0.6 * 2.5 = 1.5
    # id 2: raw score = 0.0, weighted = 0.4 * 0.0 = 0.0
    # Overall score = 1.5 + 0.0 = 1.5
    assert fitness_res.fitness_score == 1.5
    assert len(fitness_res.scores) == 2
    assert fitness_res.scores[0].id == 1
    assert fitness_res.scores[0].fitness_score == 2.5
    assert fitness_res.scores[0].weighted_score == 1.5
    assert fitness_res.scores[1].id == 2
    assert fitness_res.scores[1].fitness_score == 0.0
    assert fitness_res.scores[1].weighted_score == 0.0
