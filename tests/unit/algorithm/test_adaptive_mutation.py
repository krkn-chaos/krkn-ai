"""
Tests for GeneticAlgorithm.adapt_mutation_rate method
"""

from unittest.mock import Mock

import pytest
import yaml

from krkn_ai.models.config import AdaptiveMutation
from krkn_ai.models.app import FitnessResult


def make_generation_result(fitness_score):
    """Helper to create mock generation result with given fitness score"""
    result = Mock()
    result.fitness_result = FitnessResult(fitness_score=fitness_score)
    return result


class TestAdaptMutationRateEarlyReturns:
    """Test early return conditions"""

    def test_returns_early_when_disabled(self, genetic_algorithm):
        """Should return immediately when adaptive mutation is disabled"""
        genetic_algorithm.config.adaptive_mutation.enable = False
        genetic_algorithm.stagnant_generations = 10
        original_rate = genetic_algorithm.config.scenario_mutation_rate
        original_current_rate = genetic_algorithm.current_scenario_mutation_rate

        genetic_algorithm.adapt_mutation_rate()

        assert genetic_algorithm.stagnant_generations == 10
        assert genetic_algorithm.config.scenario_mutation_rate == original_rate
        assert genetic_algorithm.current_scenario_mutation_rate == original_current_rate

    @pytest.mark.parametrize("generations", [[], [make_generation_result(10.0)]])
    def test_returns_early_with_insufficient_generations(
        self, genetic_algorithm, generations
    ):
        """Should return when fewer than 2 generations exist"""
        genetic_algorithm.config.adaptive_mutation.enable = True
        genetic_algorithm.best_of_generation = generations
        genetic_algorithm.stagnant_generations = 5
        original_rate = genetic_algorithm.config.scenario_mutation_rate
        original_current_rate = genetic_algorithm.current_scenario_mutation_rate

        genetic_algorithm.adapt_mutation_rate()

        assert genetic_algorithm.stagnant_generations == 5
        assert genetic_algorithm.config.scenario_mutation_rate == original_rate
        assert genetic_algorithm.current_scenario_mutation_rate == original_current_rate


class TestAdaptMutationRateStagnantTracking:
    """Test stagnant generation counting"""

    @pytest.mark.parametrize(
        "prev,curr,expected_stagnant",
        [
            (10.0, 10.1, 3),  # Small improvement (0.1 < 0.5) -> increment
            (10.0, 10.0, 3),  # Zero improvement -> increment
            (12.0, 10.0, 3),  # Negative improvement -> increment
            (10.0, 11.0, 0),  # Good improvement (1.0 >= 0.5) -> reset
            (10.0, 10.5, 0),  # Exactly at threshold -> reset
        ],
    )
    def test_stagnant_tracking(self, genetic_algorithm, prev, curr, expected_stagnant):
        """Should track stagnant generations based on improvement vs threshold"""
        genetic_algorithm.config.adaptive_mutation = AdaptiveMutation(
            enable=True, threshold=0.5, generations=10, min=0.05, max=0.9
        )
        genetic_algorithm.best_of_generation = [
            make_generation_result(prev),
            make_generation_result(curr),
        ]
        genetic_algorithm.stagnant_generations = 2

        genetic_algorithm.adapt_mutation_rate()

        assert genetic_algorithm.stagnant_generations == expected_stagnant


class TestAdaptMutationRateUpdate:
    """Test mutation rate updates when threshold is reached"""

    def test_no_update_when_below_stagnant_threshold(self, genetic_algorithm):
        """Should not update rate when stagnant_generations < required"""
        genetic_algorithm.config.adaptive_mutation = AdaptiveMutation(
            enable=True, threshold=0.5, generations=5, min=0.05, max=0.9
        )
        genetic_algorithm.best_of_generation = [
            make_generation_result(10.0),
            make_generation_result(10.1),
        ]
        genetic_algorithm.stagnant_generations = 3  # Will become 4, still < 5
        original_rate = genetic_algorithm.config.scenario_mutation_rate
        original_current_rate = genetic_algorithm.current_scenario_mutation_rate

        genetic_algorithm.adapt_mutation_rate()

        assert genetic_algorithm.stagnant_generations == 4
        assert genetic_algorithm.config.scenario_mutation_rate == original_rate
        assert genetic_algorithm.current_scenario_mutation_rate == original_current_rate

    def test_increases_rate_when_stagnating(self, genetic_algorithm):
        """Should multiply rate by 1.2 when stagnating"""
        genetic_algorithm.config.adaptive_mutation = AdaptiveMutation(
            enable=True, threshold=0.5, generations=5, min=0.05, max=0.9
        )
        genetic_algorithm.config.scenario_mutation_rate = 0.3
        genetic_algorithm.current_scenario_mutation_rate = 0.3
        genetic_algorithm.best_of_generation = [
            make_generation_result(10.0),
            make_generation_result(10.1),
        ]
        genetic_algorithm.stagnant_generations = 4  # Will become 5, trigger update

        genetic_algorithm.adapt_mutation_rate()

        assert genetic_algorithm.config.scenario_mutation_rate == pytest.approx(0.3)
        assert genetic_algorithm.current_scenario_mutation_rate == pytest.approx(0.36)
        assert genetic_algorithm.stagnant_generations == 0

    def test_clamps_current_rate_only(self, genetic_algorithm):
        """Should clamp the current rate while preserving the configured rate"""
        genetic_algorithm.config.adaptive_mutation = AdaptiveMutation(
            enable=True, threshold=0.5, generations=1, min=0.05, max=0.35
        )
        genetic_algorithm.config.scenario_mutation_rate = 0.3
        genetic_algorithm.current_scenario_mutation_rate = 0.3
        genetic_algorithm.best_of_generation = [
            make_generation_result(10.0),
            make_generation_result(10.1),
        ]

        genetic_algorithm.adapt_mutation_rate()

        assert genetic_algorithm.config.scenario_mutation_rate == pytest.approx(0.3)
        assert genetic_algorithm.current_scenario_mutation_rate == pytest.approx(0.35)

    def test_raises_when_min_exceeds_max(self, genetic_algorithm):
        """Should reject invalid adaptive mutation bounds"""
        genetic_algorithm.config.adaptive_mutation = AdaptiveMutation(
            enable=True, threshold=0.5, generations=1, min=0.8, max=0.2
        )
        genetic_algorithm.current_scenario_mutation_rate = 0.3
        genetic_algorithm.best_of_generation = [
            make_generation_result(10.0),
            make_generation_result(10.1),
        ]

        with pytest.raises(ValueError, match="Invalid adaptive mutation configuration"):
            genetic_algorithm.adapt_mutation_rate()

        assert genetic_algorithm.current_scenario_mutation_rate == pytest.approx(0.3)

    def test_save_config_uses_original_rate_after_adaptation(self, genetic_algorithm):
        """Saving config after adaptive mutation should keep the configured rate"""
        genetic_algorithm.config.adaptive_mutation = AdaptiveMutation(
            enable=True, threshold=0.5, generations=1, min=0.05, max=0.9
        )
        original_rate = genetic_algorithm.config.scenario_mutation_rate
        genetic_algorithm.best_of_generation = [
            make_generation_result(10.0),
            make_generation_result(10.1),
        ]

        genetic_algorithm.adapt_mutation_rate()
        genetic_algorithm.save_config()

        config_path = f"{genetic_algorithm.output_dir}/krkn-ai.yaml"
        with open(config_path, encoding="utf-8") as f:
            saved_config = yaml.safe_load(f)

        assert genetic_algorithm.current_scenario_mutation_rate != original_rate
        assert saved_config["scenario_mutation_rate"] == original_rate
