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

    def test_calculate_fitness_handles_timeout_prevents_population_collapse(
        self, genetic_algorithm_with_mock_runner
    ):
        """Test that execution timeouts are handled and do not cause population collapse"""
        from krkn_ai.models.custom_errors import ShellCommandTimeoutError

        scenario = DummyScenario(cluster_components=ClusterComponents())
        generation_id = 0

        # Mock krkn_client.run to raise ShellCommandTimeoutError
        genetic_algorithm_with_mock_runner.krkn_client.run = Mock(
            side_effect=ShellCommandTimeoutError("Command timed out")
        )

        with patch.object(genetic_algorithm_with_mock_runner, "save_scenario_result"):
            with patch.object(
                genetic_algorithm_with_mock_runner.health_check_reporter, "plot_report"
            ):
                with patch.object(
                    genetic_algorithm_with_mock_runner.health_check_reporter,
                    "write_fitness_result",
                ):
                    # This should not raise an exception, preventing algorithm crash
                    result = genetic_algorithm_with_mock_runner.calculate_fitness(
                        scenario, generation_id
                    )

                    # Assert the returned result has highly penalized fitness scores
                    assert result.fitness_result.fitness_score == -1.0
                    assert result.fitness_result.krkn_failure_score == -1.0
                    assert result.returncode == -1
                    assert "timeout" in result.cmd

                    # Crucially, assert the scenario is added to the seen_population
                    # so that population size doesn't decrease and collapse
                    assert (
                        scenario in genetic_algorithm_with_mock_runner.seen_population
                    )
