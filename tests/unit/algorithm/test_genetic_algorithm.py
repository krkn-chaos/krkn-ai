"""
GeneticAlgorithm core functionality tests
"""

import datetime
import pytest
from unittest.mock import Mock, patch

from krkn_ai.algorithm.genetic import GeneticAlgorithm
from krkn_ai.models.app import CommandRunResult, FitnessResult
from krkn_ai.models.cluster_components import ClusterComponents
from krkn_ai.models.custom_errors import PopulationSizeError
from krkn_ai.models.scenario.scenario_dummy import DummyScenario


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


class TestCompletedGenerations:
    """Regression tests for completed_generations tracking"""

    def test_completed_generations_starts_at_zero(self, genetic_algorithm):
        """completed_generations is 0 before simulate() runs"""
        assert genetic_algorithm.completed_generations == 0

    def test_completed_generations_updated_after_simulate(
        self, minimal_config, temp_output_dir
    ):
        """simulate() must update completed_generations to the actual count, not leave it at 0"""
        minimal_config.generations = 2
        minimal_config.population_size = 2

        with patch("krkn_ai.algorithm.genetic.KrknRunner"):
            with patch(
                "krkn_ai.algorithm.genetic.ScenarioFactory.generate_valid_scenarios"
            ) as mock_gen:
                mock_gen.return_value = [("pod_scenarios", Mock)]
                ga = GeneticAlgorithm(
                    config=minimal_config, output_dir=temp_output_dir, format="yaml"
                )

        dummy = DummyScenario(cluster_components=ClusterComponents())
        mock_result = CommandRunResult(
            generation_id=0,
            scenario_id=1,
            scenario=dummy,
            cmd="test",
            log="",
            returncode=0,
            start_time=datetime.datetime.now(),
            end_time=datetime.datetime.now(),
            fitness_result=FitnessResult(fitness_score=1.0),
            health_check_results={},
        )

        with patch.object(ga, "run_baseline"):
            with patch.object(ga, "create_population", return_value=[dummy, dummy]):
                with patch.object(ga, "calculate_fitness", return_value=mock_result):
                    with patch.object(ga, "save_scenario_result"):
                        with patch.object(ga.health_check_reporter, "plot_report"):
                            with patch.object(
                                ga.health_check_reporter, "write_fitness_result"
                            ):
                                with patch.object(
                                    ga, "select_parents", return_value=(dummy, dummy)
                                ):
                                    with patch.object(
                                        ga,
                                        "crossover",
                                        return_value=(dummy, dummy),
                                    ):
                                        with patch.object(
                                            ga, "composition", return_value=dummy
                                        ):
                                            with patch.object(
                                                ga, "mutate", side_effect=lambda s: s
                                            ):
                                                ga.simulate()

        assert ga.completed_generations == 2

    def test_results_json_records_correct_generations_completed(
        self, genetic_algorithm, temp_output_dir
    ):
        """results.json summary.generations_completed must reflect the actual run count"""
        import json

        genetic_algorithm.completed_generations = 3

        with patch.object(genetic_algorithm.generations_reporter, "save_best_generations"):
            with patch.object(
                genetic_algorithm.generations_reporter, "save_best_generation_graph"
            ):
                with patch.object(genetic_algorithm.health_check_reporter, "save_report"):
                    with patch.object(
                        genetic_algorithm.health_check_reporter, "sort_fitness_result_csv"
                    ):
                        genetic_algorithm.seen_population = {}
                        genetic_algorithm.best_of_generation = []
                        genetic_algorithm.save()

        results_path = f"{temp_output_dir}/results.json"
        with open(results_path) as f:
            data = json.load(f)

        assert data["summary"]["generations_completed"] == 3

    def test_seed_assigned_from_config_on_init(self, minimal_config, temp_output_dir):
        """self.seed must be set from config.seed at init, not left as None"""
        minimal_config.seed = 42

        with patch("krkn_ai.algorithm.genetic.KrknRunner"):
            with patch(
                "krkn_ai.algorithm.genetic.ScenarioFactory.generate_valid_scenarios"
            ) as mock_gen:
                mock_gen.return_value = [("pod_scenarios", Mock)]
                ga = GeneticAlgorithm(
                    config=minimal_config, output_dir=temp_output_dir, format="yaml"
                )

        assert ga.seed == 42

    def test_results_json_records_correct_seed(self, minimal_config, temp_output_dir):
        """results.json seed must reflect config.seed, not always null"""
        import json

        minimal_config.seed = 42

        with patch("krkn_ai.algorithm.genetic.KrknRunner"):
            with patch(
                "krkn_ai.algorithm.genetic.ScenarioFactory.generate_valid_scenarios"
            ) as mock_gen:
                mock_gen.return_value = [("pod_scenarios", Mock)]
                ga = GeneticAlgorithm(
                    config=minimal_config, output_dir=temp_output_dir, format="yaml"
                )

        with patch.object(ga.generations_reporter, "save_best_generations"):
            with patch.object(ga.generations_reporter, "save_best_generation_graph"):
                with patch.object(ga.health_check_reporter, "save_report"):
                    with patch.object(ga.health_check_reporter, "sort_fitness_result_csv"):
                        ga.seen_population = {}
                        ga.best_of_generation = []
                        ga.save()

        with open(f"{temp_output_dir}/results.json") as f:
            data = json.load(f)

        assert data["seed"] == 42
