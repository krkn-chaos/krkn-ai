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

    def test_calculate_fitness_handles_run_exception(
        self, genetic_algorithm_with_mock_runner
    ):
        """A scenario that raises during execution gets a penalty result
        instead of crashing the genetic run."""
        scenario = DummyScenario(cluster_components=ClusterComponents())
        generation_id = 0

        genetic_algorithm_with_mock_runner.krkn_client.run = Mock(
            side_effect=Exception("simulated timeout")
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

                    assert isinstance(result, CommandRunResult)
                    assert result.fitness_result.fitness_score == -1.0
                    assert result.returncode != 0
                    assert result.generation_id == generation_id
                    assert (
                        scenario in genetic_algorithm_with_mock_runner.seen_population
                    )
                    genetic_algorithm_with_mock_runner.krkn_client.run.assert_called_once_with(
                        scenario, generation_id
                    )

    def test_calculate_fitness_caches_failed_scenario(
        self, genetic_algorithm_with_mock_runner
    ):
        """A failed scenario is cached so an identical scenario is not re-run."""
        scenario = DummyScenario(cluster_components=ClusterComponents())

        genetic_algorithm_with_mock_runner.krkn_client.run = Mock(
            side_effect=Exception("simulated timeout")
        )

        with patch.object(genetic_algorithm_with_mock_runner, "save_scenario_result"):
            with patch.object(
                genetic_algorithm_with_mock_runner.health_check_reporter, "plot_report"
            ):
                with patch.object(
                    genetic_algorithm_with_mock_runner.health_check_reporter,
                    "write_fitness_result",
                ):
                    genetic_algorithm_with_mock_runner.calculate_fitness(scenario, 0)
                    result = genetic_algorithm_with_mock_runner.calculate_fitness(
                        scenario, 1
                    )

        # Second call returns the cached fallback with the updated generation_id
        assert result.fitness_result.fitness_score == -1.0
        assert result.generation_id == 1
        # krkn_client.run was only attempted once (failure cached, not retried)
        genetic_algorithm_with_mock_runner.krkn_client.run.assert_called_once_with(
            scenario, 0
        )
