"""
Fitness calculation tests
"""

import datetime
from unittest.mock import Mock, patch

from krkn_ai.models.app import CommandRunResult, FitnessResult
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.cluster_components import ClusterComponents


class TestFitnessCalculation:
    """Test fitness calculation functionality"""

    def test_calculate_fitness_for_new_scenario(
        self, genetic_algorithm_with_mock_runner
    ):
        """Test fitness calculation for a new scenario"""
        scenario = DummyScenario(cluster_components=ClusterComponents())
        generation_id = 0

        # Create mock run result
        mock_result = CommandRunResult(
            generation_id=generation_id,
            scenario_id=1,
            scenario=scenario,
            cmd="test-command",
            log="test-log",
            returncode=0,
            start_time=datetime.datetime.now(),
            end_time=datetime.datetime.now(),
            fitness_result=FitnessResult(fitness_score=15.5),
            health_check_results={},
        )

        genetic_algorithm_with_mock_runner.krkn_client.run = Mock(
            return_value=mock_result
        )

        with patch.object(genetic_algorithm_with_mock_runner, "save_scenario_result"):
            with patch.object(
                genetic_algorithm_with_mock_runner.health_check_reporter, "plot_report"
            ):
                with patch.object(
                    genetic_algorithm_with_mock_runner.health_check_reporter,
                    "write_fitness_result",
                ):
                    result = genetic_algorithm_with_mock_runner.calculate_fitness(
                        scenario, generation_id
                    )

                    assert result.fitness_result.fitness_score == 15.5
                    assert (
                        scenario in genetic_algorithm_with_mock_runner.seen_population
                    )
                    genetic_algorithm_with_mock_runner.krkn_client.run.assert_called_once_with(
                        scenario, generation_id
                    )

    def test_calculate_fitness_for_seen_scenario(
        self, genetic_algorithm_with_mock_runner
    ):
        """Test fitness calculation for a seen scenario (cache mechanism)"""
        scenario = DummyScenario(cluster_components=ClusterComponents())

        # Create existing result for seen scenario
        existing_result = CommandRunResult(
            generation_id=0,
            scenario_id=1,
            scenario=scenario,
            cmd="test-command",
            log="test-log",
            returncode=0,
            start_time=datetime.datetime.now(),
            end_time=datetime.datetime.now(),
            fitness_result=FitnessResult(fitness_score=20.0),
            health_check_results={},
        )

        genetic_algorithm_with_mock_runner.seen_population[scenario] = existing_result

        # New generation ID
        new_generation_id = 1
        result = genetic_algorithm_with_mock_runner.calculate_fitness(
            scenario, new_generation_id
        )

        # Should return cached result but with updated generation_id
        assert result.fitness_result.fitness_score == 20.0
        assert result.generation_id == new_generation_id
        # Should not call krkn_client.run (using cache)
        genetic_algorithm_with_mock_runner.krkn_client.run.assert_not_called()

    def test_all_evaluated_results_populated_for_fresh_scenario(
        self, genetic_algorithm_with_mock_runner
    ):
        """Fresh scenario run must be appended to all_evaluated_results."""
        scenario = DummyScenario(cluster_components=ClusterComponents())
        generation_id = 0
        mock_result = CommandRunResult(
            generation_id=generation_id,
            scenario_id=1,
            scenario=scenario,
            cmd="test-command",
            log="test-log",
            returncode=0,
            start_time=datetime.datetime.now(),
            end_time=datetime.datetime.now(),
            fitness_result=FitnessResult(fitness_score=42.0),
            health_check_results={},
        )
        genetic_algorithm_with_mock_runner.krkn_client.run = Mock(
            return_value=mock_result
        )

        with patch.object(genetic_algorithm_with_mock_runner, "save_scenario_result"):
            with patch.object(
                genetic_algorithm_with_mock_runner.health_check_reporter, "plot_report"
            ):
                with patch.object(
                    genetic_algorithm_with_mock_runner.health_check_reporter,
                    "write_fitness_result",
                ):
                    assert (
                        len(genetic_algorithm_with_mock_runner.all_evaluated_results)
                        == 0
                    )
                    genetic_algorithm_with_mock_runner.calculate_fitness(
                        scenario, generation_id
                    )
                    assert (
                        len(genetic_algorithm_with_mock_runner.all_evaluated_results)
                        == 1
                    )
                    assert (
                        genetic_algorithm_with_mock_runner.all_evaluated_results[
                            0
                        ].fitness_result.fitness_score
                        == 42.0
                    )

    def test_all_evaluated_results_populated_for_cache_hit(
        self, genetic_algorithm_with_mock_runner
    ):
        """Cache-hit result (with corrected generation_id) must be appended to all_evaluated_results."""
        scenario = DummyScenario(cluster_components=ClusterComponents())
        existing_result = CommandRunResult(
            generation_id=0,
            scenario_id=1,
            scenario=scenario,
            cmd="test-command",
            log="test-log",
            returncode=0,
            start_time=datetime.datetime.now(),
            end_time=datetime.datetime.now(),
            fitness_result=FitnessResult(fitness_score=99.0),
            health_check_results={},
        )
        genetic_algorithm_with_mock_runner.seen_population[scenario] = existing_result

        assert len(genetic_algorithm_with_mock_runner.all_evaluated_results) == 0
        genetic_algorithm_with_mock_runner.calculate_fitness(scenario, 2)

        # Cache-hit copy must be tracked with the new generation_id
        assert len(genetic_algorithm_with_mock_runner.all_evaluated_results) == 1
        tracked = genetic_algorithm_with_mock_runner.all_evaluated_results[0]
        assert tracked.generation_id == 2
        assert tracked.fitness_result.fitness_score == 99.0
        # Original in seen_population must remain untouched (generation_id=0)
        assert (
            genetic_algorithm_with_mock_runner.seen_population[scenario].generation_id
            == 0
        )
