"""
Tests for StoppingCriteriaEvaluator
"""

from unittest.mock import Mock

import pytest

from krkn_ai.algorithm.genetic.stopping import StoppingCriteriaEvaluator
from krkn_ai.models.app import FitnessResult
from krkn_ai.models.config import GeneticAlgorithmConfig, StoppingCriteria


def make_generation_result(fitness_score: float):
    result = Mock()
    result.fitness_result = FitnessResult(fitness_score=fitness_score)
    return result


class TestStoppingCriteriaEvaluator:
    def test_stops_on_generation_limit(self):
        config = GeneticAlgorithmConfig(generations=5)
        evaluator = StoppingCriteriaEvaluator(config, [])

        should_stop, _ = evaluator.evaluate(
            cur_generation=4, elapsed_time=10.0, population_size=10
        )
        assert should_stop is False

        should_stop, reason = evaluator.evaluate(
            cur_generation=5, elapsed_time=10.0, population_size=10
        )
        assert should_stop is True
        assert "Completed 5 generations" in reason

    def test_stops_on_duration_limit(self):
        config = GeneticAlgorithmConfig(generations=100, duration=60)
        evaluator = StoppingCriteriaEvaluator(config, [])

        should_stop, _ = evaluator.evaluate(
            cur_generation=2, elapsed_time=59.0, population_size=10
        )
        assert should_stop is False

        should_stop, reason = evaluator.evaluate(
            cur_generation=2, elapsed_time=60.0, population_size=10
        )
        assert should_stop is True
        assert "Duration limit reached (60 seconds)" in reason

    def test_stops_on_empty_population(self):
        config = GeneticAlgorithmConfig(generations=10)
        evaluator = StoppingCriteriaEvaluator(config, [])

        should_stop, reason = evaluator.evaluate(
            cur_generation=1, elapsed_time=5.0, population_size=0
        )
        assert should_stop is True
        assert "No more population found" in reason

    def test_stops_on_fitness_threshold(self):
        criteria = StoppingCriteria(fitness_threshold=80.0)
        config = GeneticAlgorithmConfig(generations=20, stopping_criteria=criteria)
        best_results = [make_generation_result(75.0)]
        evaluator = StoppingCriteriaEvaluator(config, best_results)

        should_stop, _ = evaluator.evaluate(
            cur_generation=1, elapsed_time=10.0, population_size=10
        )
        assert should_stop is False

        best_results.append(make_generation_result(82.5))
        should_stop, reason = evaluator.evaluate(
            cur_generation=2, elapsed_time=20.0, population_size=10
        )
        assert should_stop is True
        assert "Fitness threshold reached" in reason

    def test_stops_on_generation_saturation(self):
        criteria = StoppingCriteria(generation_saturation=2)
        config = GeneticAlgorithmConfig(generations=20, stopping_criteria=criteria)
        best_results = [make_generation_result(50.0), make_generation_result(50.0)]
        evaluator = StoppingCriteriaEvaluator(config, best_results)

        # First stagnant generation
        evaluator.update_saturation_tracking()
        assert evaluator.saturation_stagnant_generations == 1
        should_stop, _ = evaluator.evaluate(
            cur_generation=1, elapsed_time=10.0, population_size=10
        )
        assert should_stop is False

        # Second stagnant generation reaches saturation limit
        evaluator.update_saturation_tracking()
        assert evaluator.saturation_stagnant_generations == 2
        should_stop, reason = evaluator.evaluate(
            cur_generation=2, elapsed_time=20.0, population_size=10
        )
        assert should_stop is True
        assert "Generation saturation reached" in reason

    def test_saturation_tracking_resets_on_improvement(self):
        criteria = StoppingCriteria(generation_saturation=3)
        config = GeneticAlgorithmConfig(generations=20, stopping_criteria=criteria)
        best_results = [make_generation_result(50.0), make_generation_result(50.0)]
        evaluator = StoppingCriteriaEvaluator(config, best_results)

        evaluator.update_saturation_tracking()
        assert evaluator.saturation_stagnant_generations == 1

        # Score improves significantly
        best_results.append(make_generation_result(60.0))
        evaluator.update_saturation_tracking()
        assert evaluator.saturation_stagnant_generations == 0

    def test_stops_on_exploration_saturation(self):
        criteria = StoppingCriteria(exploration_saturation=2)
        config = GeneticAlgorithmConfig(generations=20, stopping_criteria=criteria)
        evaluator = StoppingCriteriaEvaluator(config, [])

        evaluator.update_exploration_tracking()
        assert evaluator.exploration_stagnant_generations == 1
        should_stop, _ = evaluator.evaluate(
            cur_generation=1, elapsed_time=10.0, population_size=10
        )
        assert should_stop is False

        evaluator.update_exploration_tracking()
        assert evaluator.exploration_stagnant_generations == 2
        should_stop, reason = evaluator.evaluate(
            cur_generation=2, elapsed_time=20.0, population_size=10
        )
        assert should_stop is True
        assert "Exploration limit reached" in reason

    def test_stops_with_null_generations_when_duration_and_stopping_criteria_set(self):
        criteria = StoppingCriteria(generation_saturation=2)
        config = GeneticAlgorithmConfig(
            generations=None, duration=3600, stopping_criteria=criteria
        )
        best_results = [make_generation_result(50.0), make_generation_result(50.0)]
        evaluator = StoppingCriteriaEvaluator(config, best_results)

        evaluator.update_saturation_tracking()
        evaluator.update_saturation_tracking()
        should_stop, reason = evaluator.evaluate(
            cur_generation=2, elapsed_time=20.0, population_size=10
        )
        assert should_stop is True
        assert "Generation saturation reached" in reason

    def test_saturation_tracking_handles_nan_fitness_without_reset(self):
        criteria = StoppingCriteria(generation_saturation=2)
        config = GeneticAlgorithmConfig(generations=10, stopping_criteria=criteria)
        best_results = [
            make_generation_result(50.0),
            make_generation_result(float("nan")),
        ]
        evaluator = StoppingCriteriaEvaluator(config, best_results)

        evaluator.update_saturation_tracking()
        assert evaluator.saturation_stagnant_generations == 1

        best_results.append(make_generation_result(float("nan")))
        evaluator.update_saturation_tracking()
        assert evaluator.saturation_stagnant_generations == 2

        should_stop, reason = evaluator.evaluate(
            cur_generation=3, elapsed_time=10.0, population_size=10
        )
        assert should_stop is True
        assert "Generation saturation reached" in reason

    @pytest.mark.parametrize(
        "non_finite_score", [float("nan"), float("inf"), float("-inf")]
    )
    def test_finite_fitness_recovery_restarts_saturation_tracking(
        self, non_finite_score
    ):
        criteria = StoppingCriteria(generation_saturation=2)
        config = GeneticAlgorithmConfig(generations=10, stopping_criteria=criteria)
        best_results = [make_generation_result(50.0)]
        evaluator = StoppingCriteriaEvaluator(config, best_results)

        for generation, (score, expected_stop) in enumerate(
            [
                (non_finite_score, False),
                (60.0, False),
                (60.0, False),
                (60.0, True),
            ],
            start=2,
        ):
            best_results.append(make_generation_result(score))
            evaluator.update_saturation_tracking()
            should_stop, _ = evaluator.evaluate(
                cur_generation=generation,
                elapsed_time=float(generation),
                population_size=10,
            )
            assert should_stop is expected_stop
