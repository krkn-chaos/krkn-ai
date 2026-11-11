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
from krkn_ai.models.app import FitnessScoreResult
from krkn_ai.models.config import FitnessFunctionItem, GeneticAlgorithmConfig
from krkn_ai.models.scenario.base import ScenarioOrigin
from krkn_ai.chaos_engines.cancellation import (
    CancellationRequested,
    CANCELLATION_EVENT,
    request_cancellation,
)
from krkn_ai.run_results import parse_run_artifacts, scenario_detail


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
        with patch("krkn_ai.algorithm.base.KrknRunner"):
            with patch(
                "krkn_ai.algorithm.base.ScenarioFactory.generate_valid_scenarios"
            ) as mock_gen:
                with patch(
                    "krkn_ai.algorithm.base.ElasticSearchClient"
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

    def test_scenario_artifact_progress_finality_and_hash(
        self, genetic_algorithm, mock_command_run_result
    ):
        engine = genetic_algorithm
        query = FitnessFunctionItem(query="up")
        engine.config.fitness_function.items = [query]
        mock_command_run_result.fitness_result.scores = [
            FitnessScoreResult(id=query.id, fitness_score=4.0, weighted_score=0.5)
        ]
        mock_command_run_result.scenario.origin = ScenarioOrigin.INITIAL
        engine.set_current_generation(0)
        engine.save_scenario_result(mock_command_run_result)
        result_path = Path(engine.output_dir) / "yaml/generation_0/scenario_1.yaml"
        progress_path = Path(engine.output_dir) / "progress.json"
        provisional = json.loads(progress_path.read_text())
        document = yaml.safe_load(result_path.read_text())
        assert document["scenario_id"] == 1
        assert document["scenario"]["origin"] == "initial"
        assert document["scenario"]["parameters"] == [
            {"name": "duration", "value": 10},
            {"name": "exit-status", "value": 0},
        ]
        assert "!!python/" not in result_path.read_text()
        artifact_bytes = result_path.read_bytes()
        progress_bytes = progress_path.read_bytes()
        parsed = parse_run_artifacts(
            {
                "yaml/generation_0/scenario_1.yaml": (
                    artifact_bytes,
                    hashlib.sha256(artifact_bytes).hexdigest(),
                ),
                "progress.json": (
                    progress_bytes,
                    hashlib.sha256(progress_bytes).hexdigest(),
                ),
            }
        )
        detail = scenario_detail(parsed.scenarios["0:1"], parsed, False)
        assert detail["origin"] == "initial"
        assert detail["parameters"] == document["scenario"]["parameters"]
        assert provisional["completedScenarios"] == 1
        assert provisional["currentGeneration"] == 0
        assert provisional["fitnessFinalByScenario"] == {"0:1": False}
        assert "up" == document["fitness_result"]["scores"][0]["query"]
        assert document["fitness_result"]["scores"][0]["query_type"] == "point"
        assert (
            provisional["resultChecksums"]["0:1"]
            == hashlib.sha256(result_path.read_bytes()).hexdigest()
        )
        assert (
            Path(engine.output_dir) / "logs/scenario_1.log"
        ).read_text() == "test-log"

        mock_command_run_result.fitness_result.scores[0].normalized_score = 0.5
        engine.config.fitness_function.items[0].query = "changed"
        engine.update_scenario_results([mock_command_run_result])
        interim_bytes = result_path.read_bytes()
        interim_progress_bytes = progress_path.read_bytes()
        interim = parse_run_artifacts(
            {
                "yaml/generation_0/scenario_1.yaml": (
                    interim_bytes,
                    hashlib.sha256(interim_bytes).hexdigest(),
                ),
                "progress.json": (
                    interim_progress_bytes,
                    hashlib.sha256(interim_progress_bytes).hexdigest(),
                ),
            }
        )
        interim_detail = scenario_detail(interim.scenarios["0:1"], interim, False)
        assert interim_detail["fitnessResult"]["fitnessScore"] is None
        assert interim_detail["fitnessResult"]["scores"][0] == {
            "id": query.id,
            "rawScore": 4.0,
            "normalizedScore": None,
            "query": "up",
            "queryType": "point",
        }
        engine.complete_generation(0, [mock_command_run_result])
        finalized = json.loads(progress_path.read_text())
        assert finalized["fitnessFinalByScenario"] == {"0:1": True}
        assert finalized["currentGeneration"] is None
        assert (
            finalized["resultChecksums"]["0:1"]
            == hashlib.sha256(result_path.read_bytes()).hexdigest()
        )
        artifact_bytes = result_path.read_bytes()
        progress_bytes = progress_path.read_bytes()
        parsed = parse_run_artifacts(
            {
                "yaml/generation_0/scenario_1.yaml": (
                    artifact_bytes,
                    hashlib.sha256(artifact_bytes).hexdigest(),
                ),
                "progress.json": (
                    progress_bytes,
                    hashlib.sha256(progress_bytes).hexdigest(),
                ),
            }
        )
        finalized_detail = scenario_detail(parsed.scenarios["0:1"], parsed, False)
        assert finalized_detail["fitnessResult"]["fitnessScore"] == 10.0
        assert finalized_detail["fitnessResult"]["scores"][0]["normalizedScore"] == 0.5
        assert finalized_detail["fitnessResult"]["scores"][0]["query"] == "up"

    def test_no_item_fitness_waits_for_generation_completion(
        self, genetic_algorithm, mock_command_run_result
    ):
        engine = genetic_algorithm
        engine.config.fitness_function.items = []
        engine.set_current_generation(0)
        engine.save_scenario_result(mock_command_run_result)

        progress_path = Path(engine.output_dir) / "progress.json"
        assert json.loads(progress_path.read_text())["bestFitness"] is None
        assert json.loads(progress_path.read_text())["fitnessFinalByScenario"] == {
            "0:1": False
        }

        engine.update_scenario_results([mock_command_run_result])
        assert json.loads(progress_path.read_text())["fitnessFinalByScenario"] == {
            "0:1": False
        }
        engine.complete_generation(0, [mock_command_run_result])

        progress = json.loads(progress_path.read_text())
        assert progress["bestFitness"] == 10.0
        assert progress["averageFitness"] == 10.0
        assert progress["fitnessFinalByScenario"] == {"0:1": True}

    def test_cancelled_generation_persists_raw_result_without_normalizing(
        self, genetic_algorithm, mock_command_run_result, mock_scenario
    ):
        engine = genetic_algorithm
        engine.run_baseline = Mock()
        engine.create_population = Mock(return_value=[mock_scenario, mock_scenario])
        engine._check_and_stop = Mock(return_value=False)

        result = mock_command_run_result
        result.outcome = "cancelled"
        result.fitness_result.scores = [
            FitnessScoreResult(id=1, fitness_score=4.0, weighted_score=4.0)
        ]
        engine.calculate_fitness = Mock(
            side_effect=lambda *_: (engine.save_scenario_result(result), result)[1]
        )
        CANCELLATION_EVENT.clear()

        with patch(
            "krkn_ai.algorithm.genetic.engine.normalize_generation_scores"
        ) as normalize:
            engine.simulate()

        engine.calculate_fitness.assert_called_once()
        normalize.assert_not_called()
        progress = json.loads((Path(engine.output_dir) / "progress.json").read_text())
        assert progress["status"] == "cancelled"
        assert progress["completedScenarios"] == 0
        assert progress["cancelledGeneration"] == 0
        assert progress["completedGenerations"] == 0
        assert progress["currentGeneration"] == 0
        assert progress["fitnessFinalByScenario"] == {"0:1": False}
        result_path = Path(engine.output_dir) / "yaml/generation_0/scenario_1.yaml"
        saved = yaml.safe_load(result_path.read_text())
        assert saved["outcome"] == "cancelled"
        assert saved["fitness_result"]["scores"][0]["fitness_score"] == 4.0
        assert saved["fitness_result"]["scores"][0]["normalized_score"] is None

    def test_cancellation_after_child_completion_rolls_back_generation_scores(
        self, genetic_algorithm, mock_command_run_result, mock_scenario
    ):
        engine = genetic_algorithm
        engine.run_baseline = Mock()
        engine.create_population = Mock(return_value=[mock_scenario])
        engine._check_and_stop = Mock(return_value=False)
        engine.config.fitness_function.items = [FitnessFunctionItem(query="up")]
        result = mock_command_run_result.model_copy(deep=True)
        result.generation_id = 0
        result.scenario_id = 1
        result.outcome = None
        result.fitness_result.fitness_score = 10.0
        result.fitness_result.scores = [
            FitnessScoreResult(
                id=engine.config.fitness_function.items[0].id,
                fitness_score=4.0,
                weighted_score=4.0,
            )
        ]
        engine.calculate_fitness = Mock(
            side_effect=lambda *_: (engine.save_scenario_result(result), result)[1]
        )
        CANCELLATION_EVENT.clear()

        def normalize_then_cancel(results, *_args):
            for member in results:
                for score in member.fitness_result.scores:
                    score.normalized_score = 0.75
                    score.weighted_score = 0.75
                member.fitness_result.fitness_score = 75.0
            request_cancellation()

        with patch(
            "krkn_ai.algorithm.genetic.engine.normalize_generation_scores",
            side_effect=normalize_then_cancel,
        ) as normalize:
            engine.simulate()

        normalize.assert_called_once()
        engine.calculate_fitness.assert_called_once()
        progress = json.loads((Path(engine.output_dir) / "progress.json").read_text())
        assert progress["status"] == "cancelled"
        assert progress["completedGenerations"] == 0
        assert progress["cancelledGeneration"] == 0
        assert progress["fitnessFinalByScenario"] == {"0:1": False}
        assert result.fitness_result.fitness_score == 10.0
        assert result.fitness_result.scores[0].fitness_score == 4.0
        assert result.fitness_result.scores[0].weighted_score == 4.0
        assert result.fitness_result.scores[0].normalized_score is None
        saved = yaml.safe_load(
            (Path(engine.output_dir) / "yaml/generation_0/scenario_1.yaml").read_text()
        )
        assert saved["fitness_result"]["scores"][0]["normalized_score"] is None

    def test_mark_cancelled_keeps_completed_generations_final(
        self, genetic_algorithm, mock_command_run_result
    ):
        engine = genetic_algorithm
        engine.set_current_generation(0)
        engine.save_scenario_result(mock_command_run_result)
        engine.complete_generation(0, [mock_command_run_result])

        partial = mock_command_run_result.model_copy(deep=True)
        partial.generation_id = 1
        partial.scenario_id = 2
        engine.set_current_generation(1)
        engine.save_scenario_result(partial)
        engine.mark_cancelled(1)

        progress = json.loads((Path(engine.output_dir) / "progress.json").read_text())
        assert progress["completedGenerations"] == 1
        assert progress["cancelledGeneration"] == 1
        assert progress["currentGeneration"] == 1
        assert progress["fitnessFinalByScenario"] == {"0:1": True, "1:2": False}

    def test_cached_member_is_written_without_old_normalized_score(
        self, genetic_algorithm, mock_command_run_result
    ):
        engine = genetic_algorithm
        CANCELLATION_EVENT.clear()
        query = FitnessFunctionItem(query="up")
        engine.config.fitness_function.items = [query]
        cached = mock_command_run_result.model_copy(deep=True)
        cached.fitness_result.scores = [
            FitnessScoreResult(
                id=query.id,
                fitness_score=4.0,
                weighted_score=0.5,
                normalized_score=0.5,
            )
        ]
        engine.seen_population[cached.scenario] = cached

        current = engine.calculate_fitness(cached.scenario, generation_id=1)

        assert current.fitness_result.scores[0].fitness_score == 4.0
        assert current.fitness_result.scores[0].normalized_score is None
        assert cached.fitness_result.scores[0].normalized_score == 0.5
        assert current.fitness_result.scores[0].weighted_score == 4.0

    def test_baseline_cancellation_stops_before_population_creation(
        self, genetic_algorithm
    ):
        engine = genetic_algorithm
        engine.run_baseline = Mock(side_effect=CancellationRequested)
        engine.create_population = Mock()
        CANCELLATION_EVENT.clear()

        engine.simulate()

        engine.create_population.assert_not_called()
        assert engine.cancelled is True
        assert engine.cancelled_generation is None
        progress = json.loads((Path(engine.output_dir) / "progress.json").read_text())
        assert progress["status"] == "cancelled"
        assert progress["cancelledGeneration"] is None
        assert progress["currentGeneration"] is None
