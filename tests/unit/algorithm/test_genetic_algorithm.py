"""
GeneticAlgorithm core functionality tests
"""

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
                run_uuid = "test-run-uuid"
                ga = GeneticAlgorithm(
                    config=minimal_config,
                    output_dir=temp_output_dir,
                    format="yaml",
                    run_uuid=run_uuid,
                )
                assert ga.config == minimal_config
                assert ga.output_dir == temp_output_dir
                assert ga.run_uuid == run_uuid
                assert ga.format == "yaml"
                assert ga.population == []
                assert len(ga.best_of_generation) == 0

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
                        with patch(
                            "krkn_ai.algorithm.genetic.JSONSummaryReporter"
                        ) as mock_summary_reporter:
                            mock_reporter_instance = Mock()
                            mock_summary_reporter.return_value = mock_reporter_instance
                            genetic_algorithm.best_of_generation = [Mock()]
                            genetic_algorithm.seen_population = {Mock(): Mock()}
                            genetic_algorithm.save()

                            # Verify all reporter methods are called
                            assert mock_save_gen.called
                            assert mock_graph.called
                            assert mock_save_report.called
                            assert mock_sort.called
                            assert mock_summary_reporter.called
                            assert mock_reporter_instance.save.called
