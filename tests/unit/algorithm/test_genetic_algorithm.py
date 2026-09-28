"""
GeneticAlgorithm core functionality tests
"""

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml
from pydantic import ValidationError

from krkn_ai.algorithm.genetic import GeneticAlgorithm
from krkn_ai.models.config import FitnessFunctionItem, GeneticAlgorithmConfig


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

    def test_scenario_artifact_progress_finality_and_hash(
        self, genetic_algorithm, mock_command_run_result
    ):
        engine = genetic_algorithm
        engine.config.fitness_function.items = [FitnessFunctionItem(query="up")]

        engine.save_scenario_result(mock_command_run_result)
        result_path = Path(engine.output_dir) / "yaml/generation_0/scenario_1.yaml"
        progress_path = Path(engine.output_dir) / "progress.json"
        provisional = json.loads(progress_path.read_text())
        assert yaml.safe_load(result_path.read_text())["scenario_id"] == 1
        assert provisional["completedScenarios"] == 1
        assert provisional["fitnessFinalByScenario"] == {"0:1": False}
        assert (
            provisional["resultChecksums"]["0:1"]
            == hashlib.sha256(result_path.read_bytes()).hexdigest()
        )
        assert (
            Path(engine.output_dir) / "logs/scenario_1.log"
        ).read_text() == "test-log"

        engine.update_scenario_results([mock_command_run_result])
        finalized = json.loads(progress_path.read_text())
        assert finalized["fitnessFinalByScenario"] == {"0:1": True}
        assert (
            finalized["resultChecksums"]["0:1"]
            == hashlib.sha256(result_path.read_bytes()).hexdigest()
        )
