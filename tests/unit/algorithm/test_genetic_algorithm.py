"""
GeneticAlgorithm core functionality tests
"""

import os
import pytest
from unittest.mock import Mock, patch

from krkn_ai.algorithm.genetic import GeneticAlgorithm
from krkn_ai.models.custom_errors import PopulationSizeError


class TestGeneticAlgorithmInitialization:
    """Test GeneticAlgorithm initialization"""

    def test_init_with_valid_config(self, minimal_config, temp_output_dir):
        """Test initialization with valid config and config file creation"""
        with patch("krkn_ai.algorithm.genetic.KrknRunner"):
            with patch(
                "krkn_ai.algorithm.genetic.ScenarioFactory.generate_valid_scenarios"
            ) as mock_gen:
                mock_gen.return_value = [("pod_scenarios", Mock)]
                ga = GeneticAlgorithm(
                    config=minimal_config, output_dir=temp_output_dir, format="yaml"
                )
                assert ga.config == minimal_config
                assert ga.output_dir == temp_output_dir
                assert ga.format == "yaml"
                assert ga.population == []
                assert len(ga.best_of_generation) == 0
                # Verify config file is saved during initialization
                config_path = os.path.join(temp_output_dir, "krkn-ai.yaml")
                assert os.path.exists(config_path)

    def test_init_with_population_size_less_than_2(
        self, minimal_config, temp_output_dir
    ):
        """Test raises error when population size is less than 2"""
        minimal_config.population_size = 1
        with patch("krkn_ai.algorithm.genetic.KrknRunner"):
            with patch(
                "krkn_ai.algorithm.genetic.ScenarioFactory.generate_valid_scenarios"
            ) as mock_gen:
                mock_gen.return_value = [("pod_scenarios", Mock)]
                with pytest.raises(
                    PopulationSizeError, match="Population size should be at least 2"
                ):
                    GeneticAlgorithm(
                        config=minimal_config, output_dir=temp_output_dir, format="yaml"
                    )

    def test_init_with_odd_population_size(self, minimal_config, temp_output_dir):
        """Test odd population size is adjusted to even"""
        minimal_config.population_size = 5
        with patch("krkn_ai.algorithm.genetic.KrknRunner"):
            with patch(
                "krkn_ai.algorithm.genetic.ScenarioFactory.generate_valid_scenarios"
            ) as mock_gen:
                mock_gen.return_value = [("pod_scenarios", Mock)]
                ga = GeneticAlgorithm(
                    config=minimal_config, output_dir=temp_output_dir, format="yaml"
                )
                assert ga.config.population_size == 6


class TestGeneticAlgorithmCoreMethods:
    """Test GeneticAlgorithm core methods"""

    def test_save_method_calls_reporters(self, genetic_algorithm):
        """Test save method calls all reporters"""
        with patch.object(
            genetic_algorithm, "save_results_summary"
        ) as mock_save_summary:
            with patch.object(
                genetic_algorithm.generations_reporter, "save_best_generations"
            ) as mock_save_gen:
                with patch.object(
                    genetic_algorithm.generations_reporter, "save_best_generation_graph"
                ) as mock_graph:
                    with patch.object(
                        genetic_algorithm.health_check_reporter, "save_report"
                    ) as mock_save_report:
                        with patch.object(
                            genetic_algorithm.health_check_reporter,
                            "sort_fitness_result_csv",
                        ) as mock_sort:
                            genetic_algorithm.best_of_generation = [Mock()]
                            genetic_algorithm.seen_population = {Mock(): Mock()}
                            genetic_algorithm.save()

                            # Verify all reporter methods are called
                            assert mock_save_summary.called
                            assert mock_save_gen.called
                            assert mock_graph.called
                            assert mock_save_report.called
                            assert mock_sort.called


class TestResultsSummary:
    """Test results summary generation"""

    def test_save_results_summary_creates_file(
        self, genetic_algorithm, mock_command_run_result
    ):
        """Test that save_results_summary creates results.json file"""
        import json
        import datetime

        # Setup test data
        genetic_algorithm.run_start_time = datetime.datetime.now()
        genetic_algorithm.run_end_time = datetime.datetime.now()
        genetic_algorithm.generations_completed = 2
        genetic_algorithm.best_of_generation = [mock_command_run_result]
        genetic_algorithm.seen_population = {
            mock_command_run_result.scenario: mock_command_run_result
        }

        genetic_algorithm.save_results_summary()

        # Verify results.json was created
        results_path = os.path.join(genetic_algorithm.output_dir, "results.json")
        assert os.path.exists(results_path)

        # Verify contents
        with open(results_path) as f:
            results = json.load(f)

        assert "run_id" in results
        assert "start_time" in results
        assert "end_time" in results
        assert "config" in results
        assert "statistics" in results
        assert "fitness_progression" in results
        assert "best_scenarios" in results

    def test_save_results_summary_statistics(
        self, genetic_algorithm, mock_command_run_result
    ):
        """Test that statistics are correctly calculated"""
        import json
        import datetime

        # Setup test data with known values
        genetic_algorithm.run_start_time = datetime.datetime.now()
        genetic_algorithm.run_end_time = datetime.datetime.now()
        genetic_algorithm.generations_completed = 3
        genetic_algorithm.best_of_generation = [mock_command_run_result]
        genetic_algorithm.seen_population = {
            mock_command_run_result.scenario: mock_command_run_result
        }

        genetic_algorithm.save_results_summary()

        results_path = os.path.join(genetic_algorithm.output_dir, "results.json")
        with open(results_path) as f:
            results = json.load(f)

        stats = results["statistics"]
        assert stats["total_scenarios_executed"] == 1
        assert stats["unique_scenarios"] == 1
        assert stats["generations_completed"] == 3
        assert stats["best_fitness_score"] == 10.0
        assert stats["average_fitness_score"] == 10.0

    def test_save_results_summary_handles_empty_data(self, genetic_algorithm):
        """Test that save_results_summary handles empty data gracefully"""
        import json

        # No data set - should handle gracefully
        genetic_algorithm.save_results_summary()

        results_path = os.path.join(genetic_algorithm.output_dir, "results.json")
        assert os.path.exists(results_path)

        with open(results_path) as f:
            results = json.load(f)

        assert results["statistics"]["total_scenarios_executed"] == 0
        assert results["statistics"]["best_fitness_score"] == 0.0
        assert results["statistics"]["average_fitness_score"] == 0.0
        assert results["fitness_progression"] == []
        assert results["best_scenarios"] == []
