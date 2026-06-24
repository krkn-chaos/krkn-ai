"""
AppContext and CommandRunResult model tests
"""

import datetime

import pytest

from krkn_ai.models.app import (
    CommandRunResult,
    FitnessResult,
    FitnessScoreResult,
)
from krkn_ai.models.config import HealthCheckResult
from krkn_ai.models.scenario.base import BaseScenario


class MockScenario(BaseScenario):
    """Mock scenario for testing"""

    pass


class TestCommandRunResult:
    """Test CommandRunResult model"""

    def test_create_command_run_result_with_required_fields(self):
        """Test creating CommandRunResult with required fields"""
        scenario = MockScenario(
            name="test-scenario",
            krknctl_name="test-scenario",
            krknhub_image="test-image",
        )
        start_time = datetime.datetime.now()
        end_time = start_time + datetime.timedelta(seconds=30)
        fitness_result = FitnessResult(fitness_score=10.0)

        result = CommandRunResult(
            generation_id=0,
            scenario=scenario,
            cmd="krknctl run test-scenario",
            log="test log output",
            returncode=0,
            start_time=start_time,
            end_time=end_time,
            fitness_result=fitness_result,
        )
        assert result.generation_id == 0
        assert result.scenario.name == "test-scenario"
        assert result.cmd == "krknctl run test-scenario"
        assert result.log == "test log output"
        assert result.returncode == 0
        assert result.start_time == start_time
        assert result.end_time == end_time
        assert result.fitness_result.fitness_score == 10.0
        assert result.health_check_results == {}
        assert result.scenario_id > 0  # Auto-generated ID

    def test_command_run_result_auto_increments_scenario_id(self):
        """Test that CommandRunResult auto-increments scenario_id"""
        scenario = MockScenario(name="test", krknctl_name="test", krknhub_image="test")
        fitness = FitnessResult(fitness_score=0.0)
        now = datetime.datetime.now()

        result1 = CommandRunResult(
            generation_id=0,
            scenario=scenario,
            cmd="cmd1",
            log="log1",
            returncode=0,
            start_time=now,
            end_time=now,
            fitness_result=fitness,
        )
        result2 = CommandRunResult(
            generation_id=0,
            scenario=scenario,
            cmd="cmd2",
            log="log2",
            returncode=0,
            start_time=now,
            end_time=now,
            fitness_result=fitness,
        )
        assert result2.scenario_id > result1.scenario_id

    def test_command_run_result_with_health_check_results(self):
        """Test CommandRunResult with health check results"""
        scenario = MockScenario(name="test", krknctl_name="test", krknhub_image="test")
        fitness = FitnessResult(fitness_score=5.0)
        now = datetime.datetime.now()

        health_check_results = {
            "app1": [
                HealthCheckResult(
                    name="app1", response_time=0.1, status_code=200, success=True
                ),
                HealthCheckResult(
                    name="app1", response_time=0.2, status_code=200, success=True
                ),
            ],
            "app2": [
                HealthCheckResult(
                    name="app2",
                    response_time=0.15,
                    status_code=500,
                    success=False,
                    error="Internal Server Error",
                )
            ],
        }

        result = CommandRunResult(
            generation_id=1,
            scenario=scenario,
            cmd="test-cmd",
            log="test-log",
            returncode=0,
            start_time=now,
            end_time=now,
            fitness_result=fitness,
            health_check_results=health_check_results,
        )
        assert len(result.health_check_results) == 2
        assert len(result.health_check_results["app1"]) == 2
        assert len(result.health_check_results["app2"]) == 1
        assert result.health_check_results["app2"][0].success is False


class TestFitnessResult:
    """Test FitnessResult model"""

    def test_fitness_result_creation_with_defaults_and_all_fields(self):
        """Test FitnessResult with default values and all fields"""
        # Test default values
        fitness_default = FitnessResult()
        assert fitness_default.scores == []
        assert fitness_default.health_check_failure_score == 0.0
        assert fitness_default.health_check_response_time_score == 0.0
        assert fitness_default.krkn_failure_score == 0.0
        assert fitness_default.fitness_score == 0.0

        # Test with all fields (including FitnessScoreResult)
        scores = [
            FitnessScoreResult(id=1, fitness_score=10.0, weighted_score=5.0),
            FitnessScoreResult(id=2, fitness_score=20.0, weighted_score=10.0),
        ]
        fitness = FitnessResult(
            scores=scores,
            health_check_failure_score=1.0,
            health_check_response_time_score=2.0,
            krkn_failure_score=0.5,
            fitness_score=15.0,
        )
        assert len(fitness.scores) == 2
        assert fitness.scores[0].id == 1
        assert fitness.scores[0].fitness_score == 10.0
        assert fitness.health_check_failure_score == 1.0
        assert fitness.health_check_response_time_score == 2.0
        assert fitness.krkn_failure_score == 0.5
        assert fitness.fitness_score == 15.0


class TestFitnessResultNonFiniteInvariant:
    """A fitness score must always be finite. PromQL can emit NaN/±Inf, which
    otherwise crashes roulette selection and corrupts sorted() ranking."""

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_coerced_on_construction(self, bad):
        assert FitnessResult(fitness_score=bad).fitness_score == 0.0

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_coerced_on_assignment(self, bad):
        # validate_assignment must catch the post-construction aggregate reassignment
        result = FitnessResult()
        result.fitness_score = bad
        assert result.fitness_score == 0.0

    def test_all_score_fields_coerced(self):
        result = FitnessResult(
            health_check_failure_score=float("nan"),
            health_check_response_time_score=float("inf"),
            krkn_failure_score=float("-inf"),
            fitness_score=float("nan"),
        )
        assert result.health_check_failure_score == 0.0
        assert result.health_check_response_time_score == 0.0
        assert result.krkn_failure_score == 0.0
        assert result.fitness_score == 0.0

    def test_per_item_scores_coerced(self):
        item = FitnessScoreResult(
            id=1, fitness_score=float("nan"), weighted_score=float("inf")
        )
        assert item.fitness_score == 0.0
        assert item.weighted_score == 0.0

    def test_finite_values_preserved(self):
        # Includes the -1.0 misconfiguration sentinel, which must pass through.
        result = FitnessResult(fitness_score=-1.0)
        assert result.fitness_score == -1.0
        result.fitness_score = 7.5
        assert result.fitness_score == 7.5
