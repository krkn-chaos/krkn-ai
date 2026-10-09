"""
GeneticAlgorithm core functionality tests
"""

import datetime
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml
from pydantic import ValidationError

from krkn_ai.algorithm.genetic import GeneticAlgorithm
from krkn_ai.models.app import CommandRunResult, FitnessResult, FitnessScoreResult
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.scenario.scenario_dummy import DummyScenario
from krkn_ai.models.config import FitnessFunctionItem, GeneticAlgorithmConfig
from krkn_ai.models.scenario.base import ScenarioOrigin
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


class TestGenerationAverages:
    """Engine bookkeeping that feeds results.json fitness_progression (#348)"""

    def _result(self, gen_id, sid, score, scenario, now):
        return CommandRunResult(
            generation_id=gen_id,
            scenario_id=sid,
            scenario=scenario,
            cmd="test",
            log="test",
            returncode=0,
            start_time=now,
            end_time=now,
            fitness_result=FitnessResult(fitness_score=score),
        )

    def test_cache_hit_counts_toward_its_generation(self, genetic_algorithm):
        engine = genetic_algorithm
        now = datetime.datetime.now(datetime.timezone.utc)
        scenario = DummyScenario(cluster_components=ClusterComponents())
        other = DummyScenario(cluster_components=ClusterComponents())
        other.end.value = 99  # distinct identity from `scenario`

        first = self._result(0, 1, 80.0, scenario, now)
        engine.seen_population[scenario] = first
        engine.complete_generation(0, [first])

        # Generation 1 re-evaluates the cached scenario and one new one.
        cached = engine.calculate_fitness(scenario, generation_id=1)
        fresh = self._result(1, 2, 20.0, other, now)
        engine.seen_population[other] = fresh
        engine.complete_generation(1, [cached, fresh])

        assert cached.generation_id == 1
        assert engine.seen_population[scenario].generation_id == 0
        assert engine.generation_averages == {0: 80.0, 1: 50.0}

    def test_save_passes_generation_averages_to_reporter(self, genetic_algorithm):
        engine = genetic_algorithm
        now = datetime.datetime.now(datetime.timezone.utc)
        scenario = DummyScenario(cluster_components=ClusterComponents())
        first = self._result(0, 1, 80.0, scenario, now)
        engine.seen_population[scenario] = first
        engine.best_of_generation.append(first)
        engine.complete_generation(0, [first])
        cached = engine.calculate_fitness(scenario, generation_id=1)
        engine.best_of_generation.append(cached)
        engine.complete_generation(1, [cached])

        with patch(
            "krkn_ai.algorithm.genetic.engine.JSONSummaryReporter"
        ) as mock_reporter:
            engine.save()

        kwargs = mock_reporter.call_args.kwargs
        assert kwargs["generation_averages"] == {0: 80.0, 1: 80.0}
