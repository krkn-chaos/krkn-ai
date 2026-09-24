"""
GeneticAlgorithm core functionality tests
"""

import pytest
from unittest.mock import Mock, patch
from pydantic import ValidationError

from krkn_ai.algorithm.genetic import GeneticAlgorithm
from krkn_ai.models.config import GeneticAlgorithmConfig


class TestGeneticAlgorithmInitialization:
    """Test GeneticAlgorithm initialization"""

    def test_init_with_valid_config(self, minimal_config, temp_output_dir):
        """Test initialization with valid config and config file creation"""
        with patch("krkn_ai.algorithm.base.KrknRunner"):
            with patch(
                "krkn_ai.algorithm.base.ScenarioFactory.generate_valid_scenarios"
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

    def test_init_skips_elasticsearch_without_config(
        self, minimal_config, temp_output_dir
    ):
        """ElasticSearchClient is opt-in."""
        assert minimal_config.elastic is None
        with patch("krkn_ai.algorithm.genetic.KrknRunner"):
            with patch(
                "krkn_ai.algorithm.genetic.ScenarioFactory.generate_valid_scenarios"
            ) as mock_gen:
                with patch(
                    "krkn_ai.algorithm.genetic.ElasticSearchClient"
                ) as mock_elastic:
                    mock_gen.return_value = [("pod_scenarios", Mock)]
                    ga = GeneticAlgorithm(
                        config=minimal_config,
                        output_dir=temp_output_dir,
                        format="yaml",
                    )

                    assert ga.elastic_client is None
                    mock_elastic.assert_not_called()

    def test_init_generates_unique_run_uuid(self, minimal_config, temp_output_dir):
        """Test initialization generates a unique run UUID per instance"""
        with patch("krkn_ai.algorithm.base.KrknRunner"):
            with patch(
                "krkn_ai.algorithm.base.ScenarioFactory.generate_valid_scenarios"
            ) as mock_gen:
                mock_gen.return_value = [("pod_scenarios", Mock)]
                first = GeneticAlgorithm(
                    config=minimal_config, output_dir=temp_output_dir, format="yaml"
                )
                second = GeneticAlgorithm(
                    config=minimal_config, output_dir=temp_output_dir, format="yaml"
                )

                assert first.run_uuid != second.run_uuid

    def test_init_with_population_size_less_than_2(self):
        """Test raises ValidationError when population size is less than 2"""
        with pytest.raises(ValidationError, match="population_size"):
            GeneticAlgorithmConfig(population_size=1)

    def test_init_with_odd_population_size(self, minimal_config, temp_output_dir):
        """Test odd population size is adjusted to even"""
        minimal_config.genetic.population_size = 5
        with patch("krkn_ai.algorithm.base.KrknRunner"):
            with patch(
                "krkn_ai.algorithm.base.ScenarioFactory.generate_valid_scenarios"
            ) as mock_gen:
                mock_gen.return_value = [("pod_scenarios", Mock)]
                ga = GeneticAlgorithm(
                    config=minimal_config, output_dir=temp_output_dir, format="yaml"
                )
                assert ga.algo_config.population_size == 6


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
                            "krkn_ai.algorithm.genetic.engine.JSONSummaryReporter"
                        ) as mock_summary_reporter:
                            mock_reporter_instance = Mock()
                            mock_summary_reporter.return_value = mock_reporter_instance
                            genetic_algorithm.best_of_generation = [Mock()]
                            genetic_algorithm.seen_population = {Mock(): Mock()}
                            final_rate = 0.42
                            genetic_algorithm.current_scenario_mutation_rate = (
                                final_rate
                            )
                            genetic_algorithm.completed_generations = 2
                            genetic_algorithm.save()

                            assert mock_save_gen.called
                            assert mock_graph.called
                            assert mock_save_report.called
                            assert mock_sort.called
                            assert mock_summary_reporter.called
                            assert (
                                mock_summary_reporter.call_args.kwargs[
                                    "scenario_mutation_rate"
                                ]
                                == final_rate
                            )
                            assert (
                                mock_summary_reporter.call_args.kwargs[
                                    "completed_generations"
                                ]
                                == 2
                            )
                            assert mock_reporter_instance.save.called
